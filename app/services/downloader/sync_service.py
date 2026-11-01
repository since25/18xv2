from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.downloader import (
    DownloaderPackage,
    DownloaderPackageCandidate,
    DownloaderSubmission,
    DownloaderSyncRun,
    DownloaderTaskFileHistory,
    DownloaderTaskHistory,
    DownloaderTaskSnapshot,
)
from app.models.keywords import KeywordEntry
from app.services.keywords.registry_service import normalize_keyword_text
from app.services.downloader.client import DownloaderRemoteError


@dataclass(frozen=True)
class SyncSummary:
    packages_seen: int
    packages_updated: int
    candidates_created: int
    candidates_dismissed: int


@dataclass(frozen=True)
class SubmissionSummary:
    submitted: int
    skipped: int
    failed: int
    items: list[dict[str, Any]]


@dataclass(frozen=True)
class TaskSyncSummary:
    tasks_seen: int
    tasks_updated: int


_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _bytes(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        return max(int(value), 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _task_structured_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """把 RN 任务载荷的时间和字节字段转换为可查询的结构化值。"""
    files = payload.get("files")
    total_bytes = downloaded_bytes = 0
    if isinstance(files, list):
        for file_payload in files:
            if not isinstance(file_payload, dict):
                continue
            total_bytes += _bytes(file_payload.get("total_size_bytes"))
            downloaded_bytes += _bytes(file_payload.get("downloaded_size_bytes"))
    return {
        "remote_created_at": _timestamp(payload.get("created_at")),
        "remote_updated_at": _timestamp(payload.get("updated_at")),
        "finished_at": _timestamp(payload.get("updated_at"))
        if str(payload.get("status") or "") in _TERMINAL_STATUSES
        else None,
        "total_bytes": total_bytes,
        "downloaded_bytes": downloaded_bytes,
        "channel_title": payload.get("chat_title") or None,
    }


def _channel_titles_by_chat(db: Session) -> dict[int, str]:
    """RN 任务载荷只带 chat_id，用已同步资源包的频道名补齐。"""
    rows = db.execute(
        select(DownloaderPackage.source_chat_id, DownloaderPackage.channel_title)
        .where(DownloaderPackage.source_chat_id.is_not(None), DownloaderPackage.channel_title.is_not(None))
        .distinct()
    ).all()
    return {int(chat_id): title for chat_id, title in rows if title}


def _unchanged_terminal(snapshot: DownloaderTaskSnapshot, summary: dict[str, Any]) -> bool:
    """已结束且 RN 侧没有再更新的任务，不必重新拉取详情。"""
    if snapshot.status not in _TERMINAL_STATUSES or str(summary.get("status") or "") != snapshot.status:
        return False
    remote_updated = _timestamp(summary.get("updated_at"))
    stored = snapshot.remote_updated_at
    if remote_updated is None or stored is None:
        return False
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    return abs((remote_updated - stored).total_seconds()) < 0.001


def _terms(entry: KeywordEntry) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = [(entry.canonical_name, normalize_keyword_text(entry.canonical_name))]
    for alias in entry.aliases:
        values.append((alias.alias, normalize_keyword_text(alias.alias)))
    return [(display, normalized.casefold()) for display, normalized in values if normalized]


def _package_values(payload: dict[str, Any], *, node_key: str, now: datetime) -> dict[str, Any]:
    return {
        "node_key": node_key,
        "remote_package_id": _int(payload.get("id")),
        "library_id": _int(payload.get("library_id"), 0) or None,
        "title": str(payload.get("title") or ""),
        "channel_title": payload.get("channel_title") or payload.get("source_title"),
        "source_chat_id": _int(payload.get("source_chat_id") or payload.get("chat_id"), 0) or None,
        "published_at": payload.get("published_at"),
        "boundary_status": str(payload.get("boundary_status") or "unknown"),
        "media_count": _int(payload.get("media_count")),
        "known_total_size": _int(payload.get("known_total_size")),
        "current_download_status": str(payload.get("current_download_status") or payload.get("download_status") or "never"),
        "has_successful_attempt": bool(payload.get("has_successful_attempt", False)),
        "completed_revision": _int(payload.get("completed_revision"), 0) or None,
        "index_revision": _int(payload.get("index_revision"), 0) or None,
        "raw_payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "last_seen_at": now,
        "updated_at": now,
    }


def _load_terms(db: Session) -> tuple[list[tuple[KeywordEntry, list[tuple[str, str]]]], list[tuple[str, str]]]:
    """加载当前有效的白名单和黑名单词。"""
    entries = list(
        db.scalars(
            select(KeywordEntry)
            .where(KeywordEntry.status == "active", KeywordEntry.keyword_type.in_(["whitelist", "blacklist"]))
            .options(selectinload(KeywordEntry.aliases))
        ).all()
    )
    whitelist = [(entry, _terms(entry)) for entry in entries if entry.keyword_type == "whitelist"]
    blacklist = [term for entry in entries if entry.keyword_type == "blacklist" for term in _terms(entry)]
    return whitelist, blacklist


def _match_package(
    db: Session,
    package: DownloaderPackage,
    whitelist_terms: list[tuple[KeywordEntry, list[tuple[str, str]]]],
    blacklist_terms: list[tuple[str, str]],
) -> tuple[int, int]:
    """按当前规则匹配一个资源包，返回新建和作废候选数。"""
    normalized_title = normalize_keyword_text(package.title).casefold()
    package_revision = package.index_revision or 0
    matched_entries: list[tuple[KeywordEntry, str]] = []
    blocked = any(term in normalized_title for _, term in blacklist_terms)
    revision_needs_download = (
        not package.has_successful_attempt
        or package.completed_revision is None
        or package_revision > package.completed_revision
    )
    if package.ignored_at is None and package.boundary_status == "stable" and revision_needs_download and not blocked:
        for entry, terms in whitelist_terms:
            for display, term in terms:
                if term in normalized_title:
                    matched_entries.append((entry, display))
                    break

    existing_candidates = list(
        db.scalars(
            select(DownloaderPackageCandidate).where(DownloaderPackageCandidate.package_id == package.id)
        ).all()
    )
    matched_ids = {entry.id for entry, _ in matched_entries}
    created = dismissed = 0
    for candidate in existing_candidates:
        if package.ignored_at is not None:
            if candidate.status in {"pending", "selected"}:
                candidate.status = "dismissed"
                candidate.dismissed_reason = "ignored"
                dismissed += 1
            continue
        if candidate.package_revision != package_revision and candidate.status in {"pending", "selected"}:
            candidate.status = "dismissed"
            candidate.dismissed_reason = "资源包新版本已生成候选"
            dismissed += 1
        elif (
            candidate.package_revision == package_revision
            and candidate.keyword_entry_id not in matched_ids
            and candidate.status in {"pending", "selected"}
        ):
            candidate.status = "dismissed"
            candidate.dismissed_reason = "资源包状态或黑名单规则已排除"
            dismissed += 1
    for entry, display in matched_entries:
        existing = next(
            (
                item
                for item in existing_candidates
                if item.keyword_entry_id == entry.id and item.package_revision == package_revision
            ),
            None,
        )
        if existing is None:
            db.add(
                DownloaderPackageCandidate(
                    package_id=package.id,
                    keyword_entry_id=entry.id,
                    package_revision=package_revision,
                    matched_term=display,
                    match_reason=f"标题命中白名单：{display}",
                )
            )
            created += 1
        elif existing.status == "dismissed" and existing.dismissed_reason in {
            "资源包状态或黑名单规则已排除",
            "ignored",
        }:
            existing.status = "pending"
            existing.dismissed_reason = None
            existing.matched_term = display
    return created, dismissed


def _record_task_history(db: Session, payload: dict[str, Any], *, node_key: str, task_id: str) -> None:
    raw_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    exists = db.scalar(
        select(DownloaderTaskHistory).where(
            DownloaderTaskHistory.node_key == node_key,
            DownloaderTaskHistory.remote_task_id == task_id,
            DownloaderTaskHistory.payload_hash == payload_hash,
        )
    )
    if exists is not None:
        return
    current_file = payload.get("current_file")
    history = DownloaderTaskHistory(
        node_key=node_key,
        remote_task_id=task_id,
        payload_hash=payload_hash,
        source=payload.get("source"),
        task_type=payload.get("task_type"),
        title=payload.get("title"),
        status=str(payload.get("status") or "unknown"),
        total_count=_int(payload.get("total_count")),
        success_count=_int(payload.get("success_count")),
        failed_count=_int(payload.get("failed_count")),
        current_file_json=json.dumps(current_file, ensure_ascii=False) if current_file is not None else None,
        raw_payload_json=raw_payload,
        observed_at=datetime.now(UTC),
    )
    db.add(history)
    db.flush()
    files = payload.get("files")
    if not isinstance(files, list):
        return
    for index, file_payload in enumerate(files):
        if not isinstance(file_payload, dict):
            continue
        message_id = str(
            file_payload.get("message_id")
            or file_payload.get("id")
            or file_payload.get("source_message_id")
            or index
        )
        db.add(
            DownloaderTaskFileHistory(
                history_id=history.id,
                message_id=message_id,
                status=file_payload.get("status"),
                filename=file_payload.get("filename") or file_payload.get("file_name"),
                total_size=_bytes(file_payload.get("total_size_bytes"), _int(file_payload.get("total_size"))),
                downloaded_size=_bytes(
                    file_payload.get("downloaded_size_bytes"), _int(file_payload.get("downloaded_size"))
                ),
                download_speed=_bytes(
                    file_payload.get("download_speed_bytes"), _int(file_payload.get("download_speed"))
                ),
                save_path=file_payload.get("save_path"),
                error=file_payload.get("error"),
                uploaded_size=_int(file_payload.get("uploaded_size")),
                upload_speed=_int(file_payload.get("upload_speed")),
                raw_payload_json=json.dumps(file_payload, ensure_ascii=False, sort_keys=True),
            )
        )


class DownloaderSyncService:
    """在 18x 数据库中同步资源包、候选和下载任务。"""

    @staticmethod
    def sync_packages(db: Session, client: Any, *, node_key: str = "rn") -> SyncSummary:
        run = DownloaderSyncRun(kind="packages", status="running")
        db.add(run)
        db.flush()
        now = datetime.now(UTC)
        whitelist_terms, blacklist_terms = _load_terms(db)
        cursor: str | None = None
        seen = updated = created = dismissed = 0
        try:
            while True:
                page = client.list_packages(cursor=cursor, page_size=200)
                items = page.get("items", []) if isinstance(page, dict) else []
                if not isinstance(items, list):
                    raise ValueError("下载器资源包列表格式无效")
                for payload in items:
                    if not isinstance(payload, dict) or not payload.get("id"):
                        continue
                    seen += 1
                    values = _package_values(payload, node_key=node_key, now=now)
                    package = db.scalar(
                        select(DownloaderPackage).where(
                            DownloaderPackage.node_key == node_key,
                            DownloaderPackage.remote_package_id == values["remote_package_id"],
                        )
                    )
                    if package is None:
                        package = DownloaderPackage(first_seen_at=now, **values)
                        db.add(package)
                        db.flush()
                    else:
                        for key, value in values.items():
                            setattr(package, key, value)
                    updated += 1
                    if str(payload.get("current_download_status") or payload.get("download_status") or "") == "completed":
                        package.completed_media_count = package.media_count
                    created_now, dismissed_now = _match_package(
                        db, package, whitelist_terms, blacklist_terms
                    )
                    created += created_now
                    dismissed += dismissed_now
                cursor = page.get("next_cursor")
                if not cursor:
                    break
            run.status = "completed"
            run.packages_seen = seen
            run.candidates_created = created
            run.finished_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:
            db.rollback()
            run = DownloaderSyncRun(kind="packages", status="failed", error_message=str(exc), packages_seen=seen, candidates_created=created)
            run.finished_at = datetime.now(UTC)
            db.add(run)
            db.commit()
            raise
        return SyncSummary(seen, updated, created, dismissed)

    @staticmethod
    def list_candidates(
        db: Session,
        *,
        candidate_status: str | None = "pending",
        keyword_entry_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = (
            select(DownloaderPackageCandidate, DownloaderPackage, KeywordEntry)
            .join(DownloaderPackage, DownloaderPackage.id == DownloaderPackageCandidate.package_id)
            .join(KeywordEntry, KeywordEntry.id == DownloaderPackageCandidate.keyword_entry_id)
        )
        if candidate_status:
            stmt = stmt.where(DownloaderPackageCandidate.status == candidate_status)
        if keyword_entry_id is not None:
            stmt = stmt.where(DownloaderPackageCandidate.keyword_entry_id == keyword_entry_id)
        if search:
            stmt = stmt.where(DownloaderPackage.title.contains(search))
        count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.execute(
            stmt.order_by(DownloaderPackage.updated_at.desc(), DownloaderPackageCandidate.id.desc())
            .offset((max(page, 1) - 1) * max(page_size, 1))
            .limit(min(max(page_size, 1), 200))
        ).all()
        result = []
        for candidate, package, keyword in rows:
            result.append(
                {
                    "candidate_id": candidate.id,
                    "package_id": package.id,
                    "remote_package_id": package.remote_package_id,
                    "library_id": package.library_id,
                    "title": package.title,
                    "channel_title": package.channel_title,
                    "published_at": package.published_at,
                    "boundary_status": package.boundary_status,
                    "media_count": package.media_count,
                    "known_total_size": package.known_total_size,
                    "current_download_status": package.current_download_status,
                    "completed_revision": package.completed_revision,
                    "package_revision": candidate.package_revision,
                    "keyword_entry_id": keyword.id,
                    "keyword": keyword.canonical_name,
                    "matched_term": candidate.matched_term,
                    "match_reason": candidate.match_reason,
                    "status": candidate.status,
                    "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None,
                }
            )
        return result, int(count)

    @staticmethod
    def select_candidate(db: Session, candidate_id: int, selected: bool) -> DownloaderPackageCandidate:
        candidate = db.get(DownloaderPackageCandidate, candidate_id)
        if candidate is None:
            raise LookupError(f"candidate {candidate_id} not found")
        if candidate.status not in {"pending", "selected"}:
            raise ValueError("只有待确认候选可以选择")
        candidate.status = "selected" if selected else "pending"
        db.commit()
        db.refresh(candidate)
        return candidate

    @staticmethod
    def submit_selected(db: Session, client: Any, candidate_ids: list[int], *, node_key: str = "rn") -> SubmissionSummary:
        if not candidate_ids:
            raise ValueError("至少选择一个候选资源包")
        submitted = skipped = failed = 0
        items: list[dict[str, Any]] = []
        for candidate_id in dict.fromkeys(candidate_ids):
            candidate = db.scalar(
                select(DownloaderPackageCandidate)
                .where(DownloaderPackageCandidate.id == int(candidate_id))
                .with_for_update()
            )
            if candidate is None:
                raise LookupError(f"candidate {candidate_id} not found")
            if candidate.status not in {"pending", "selected", "submitted"}:
                raise ValueError(f"candidate {candidate_id} 不是待确认或已选择状态")
            package = db.get(DownloaderPackage, candidate.package_id)
            if package is None or package.boundary_status != "stable":
                raise ValueError(f"candidate {candidate_id} 对应资源包已不可下载")
            revision = package.index_revision or 0
            if candidate.package_revision != revision:
                raise ValueError(f"candidate {candidate_id} 对应的资源包版本已更新，请重新同步")
            outcome, item = DownloaderSyncService._submit_package(db, client, package, candidate, node_key=node_key)
            items.append(item)
            if outcome == "submitted":
                submitted += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
        db.commit()
        return SubmissionSummary(submitted, skipped, failed, items)

    @staticmethod
    def _submit_package(
        db: Session,
        client: Any,
        package: DownloaderPackage,
        candidate: DownloaderPackageCandidate | None,
        *,
        node_key: str,
    ) -> tuple[str, dict[str, Any]]:
        """提交一个资源包的当前版本；candidate 为空表示未命中白名单、直接按资源包提交。

        返回 (submitted|skipped|failed, 明细)。远端错误会先落库再抛出。
        """
        revision = package.index_revision or 0
        mode = "incremental"
        key = f"18x:{node_key}:package:{package.remote_package_id}:r{revision}:{mode}"
        ref: dict[str, Any] = {"candidate_id": candidate.id} if candidate is not None else {"package_id": package.id}
        existing = db.scalar(select(DownloaderSubmission).where(DownloaderSubmission.idempotency_key == key))
        if existing is not None and existing.status == "submitted":
            if candidate is not None:
                candidate.status = "submitted"
            return "skipped", {**ref, "submission_id": existing.id, "remote_task_id": existing.remote_task_id, "status": existing.status}

        def ensure_submission() -> DownloaderSubmission:
            nonlocal existing
            if existing is None:
                existing = DownloaderSubmission(
                    package_id=package.id,
                    candidate_id=candidate.id if candidate is not None else None,
                    package_revision=revision,
                    download_mode=mode,
                    idempotency_key=key,
                )
                db.add(existing)
            return existing

        try:
            payload = client.submit_package(package.remote_package_id, key, mode=mode)
            batch = payload.get("batch") if isinstance(payload, dict) else {}
            batch = batch if isinstance(batch, dict) else {}
            submission = ensure_submission()
            if not batch:
                submission.status = "no_new_items"
                submission.remote_batch_id = None
                submission.remote_task_id = None
                submission.error_message = None
                if candidate is not None:
                    candidate.status = "no_new_items"
                return "skipped", {**ref, "submission_id": submission.id, "status": submission.status}
            submission.remote_batch_id = _int(batch.get("id"), 0) or None
            submission.remote_task_id = str(batch.get("task_id")) if batch.get("task_id") else None
            submission.status = "submitted"
            submission.error_message = None
            if candidate is not None:
                candidate.status = "submitted"
            return "submitted", {**ref, "submission_id": submission.id, "remote_task_id": submission.remote_task_id, "status": submission.status}
        except DownloaderRemoteError as exc:
            submission = ensure_submission()
            submission.status = "failed"
            submission.error_message = str(exc)
            db.commit()
            raise
        except Exception as exc:
            submission = ensure_submission()
            submission.status = "failed"
            submission.error_message = str(exc)
            return "failed", {**ref, "submission_id": submission.id, "status": "failed", "error": "remote submission failed"}

    @staticmethod
    def submit_packages(db: Session, client: Any, package_ids: list[int], *, node_key: str = "rn") -> SubmissionSummary:
        """按资源包直接提交下载，用于没有命中白名单的资源包。"""
        if not package_ids:
            raise ValueError("至少选择一个资源包")
        submitted = skipped = failed = 0
        items: list[dict[str, Any]] = []
        for package_id in dict.fromkeys(package_ids):
            package = db.scalar(
                select(DownloaderPackage).where(DownloaderPackage.id == int(package_id)).with_for_update()
            )
            if package is None:
                raise LookupError(f"package {package_id} not found")
            if package.boundary_status != "stable":
                raise ValueError(f"资源包 {package_id} 上游尚未整理完成，暂不可下载")
            outcome, item = DownloaderSyncService._submit_package(db, client, package, None, node_key=node_key)
            items.append(item)
            if outcome == "submitted":
                submitted += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
        db.commit()
        return SubmissionSummary(submitted, skipped, failed, items)

    @staticmethod
    def sync_tasks(db: Session, client: Any, *, node_key: str = "rn") -> TaskSyncSummary:
        tasks = client.list_tasks()
        channel_titles = _channel_titles_by_chat(db)
        updated = 0
        for summary in tasks:
            task_id = str(summary.get("task_id") or summary.get("id") or "")
            if not task_id:
                continue
            snapshot = db.scalar(
                select(DownloaderTaskSnapshot).where(
                    DownloaderTaskSnapshot.node_key == node_key,
                    DownloaderTaskSnapshot.remote_task_id == task_id,
                )
            )
            if snapshot is not None and _unchanged_terminal(snapshot, summary):
                # 只补齐旧快照缺失的频道名，不再逐个拉取详情
                if not snapshot.channel_title:
                    chat_id = summary.get("chat_id") or json.loads(snapshot.raw_payload_json or "{}").get("chat_id")
                    snapshot.channel_title = channel_titles.get(_int(chat_id, 0))
                continue
            try:
                payload = client.get_task(task_id)
            except Exception:
                payload = summary
            current_file = payload.get("current_file")
            if snapshot is None:
                snapshot = DownloaderTaskSnapshot(node_key=node_key, remote_task_id=task_id)
                db.add(snapshot)
            previous_status = snapshot.status
            structured = _task_structured_fields(payload)
            snapshot.source = payload.get("source")
            snapshot.task_type = payload.get("task_type")
            snapshot.title = payload.get("title")
            snapshot.status = str(payload.get("status") or "unknown")
            snapshot.total_count = _int(payload.get("total_count"))
            snapshot.success_count = _int(payload.get("success_count"))
            snapshot.failed_count = _int(payload.get("failed_count"))
            snapshot.remote_created_at = structured["remote_created_at"]
            snapshot.remote_updated_at = structured["remote_updated_at"]
            snapshot.total_bytes = structured["total_bytes"]
            snapshot.downloaded_bytes = structured["downloaded_bytes"]
            snapshot.current_file_json = json.dumps(current_file, ensure_ascii=False) if current_file is not None else None
            snapshot.raw_payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            snapshot.observed_at = datetime.now(UTC)
            if snapshot.status in _TERMINAL_STATUSES:
                if previous_status not in _TERMINAL_STATUSES:
                    snapshot.finished_at = structured["finished_at"]
            else:
                snapshot.finished_at = None
            _record_task_history(db, payload, node_key=node_key, task_id=task_id)
            updated += 1
            submissions = list(db.scalars(select(DownloaderSubmission).where(DownloaderSubmission.remote_task_id == task_id)).all())
            package_channel = next(
                (
                    submission.package.channel_title
                    for submission in submissions
                    if submission.package is not None and submission.package.channel_title
                ),
                None,
            )
            snapshot.channel_title = (
                package_channel
                or structured["channel_title"]
                or channel_titles.get(_int(payload.get("chat_id"), 0))
            )
            for submission in submissions:
                status = snapshot.status
                if status in {"completed", "completed_with_errors"}:
                    submission.status = status
                elif status in {"failed", "cancelled"}:
                    submission.status = status
                candidate = db.get(DownloaderPackageCandidate, submission.candidate_id) if submission.candidate_id else None
                if candidate is not None and candidate.status != "no_new_items" and submission.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                    candidate.status = submission.status
        db.commit()
        return TaskSyncSummary(len(tasks), updated)

    @staticmethod
    def list_task_history(
        db: Session,
        task_id: str,
        *,
        node_key: str = "rn",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = list(
            db.scalars(
                select(DownloaderTaskHistory)
                .where(
                    DownloaderTaskHistory.node_key == node_key,
                    DownloaderTaskHistory.remote_task_id == str(task_id),
                )
                .options(selectinload(DownloaderTaskHistory.files))
                .order_by(DownloaderTaskHistory.observed_at.desc(), DownloaderTaskHistory.id.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
        )
        result = []
        for row in rows:
            result.append(
                {
                    "id": row.id,
                    "remote_task_id": row.remote_task_id,
                    "status": row.status,
                    "total_count": row.total_count,
                    "success_count": row.success_count,
                    "failed_count": row.failed_count,
                    "current_file": json.loads(row.current_file_json) if row.current_file_json else None,
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "files": [json.loads(file.raw_payload_json) for file in row.files],
                }
            )
        return result
    @staticmethod
    def list_tasks(db: Session, *, node_key: str = "rn", limit: int = 100) -> tuple[list[dict[str, Any]], int]:
        rows = list(
            db.scalars(
                select(DownloaderTaskSnapshot)
                .where(DownloaderTaskSnapshot.node_key == node_key)
                .order_by(DownloaderTaskSnapshot.observed_at.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
        )
        result = []
        for row in rows:
            current_file = None
            if row.current_file_json:
                try:
                    current_file = json.loads(row.current_file_json)
                except json.JSONDecodeError:
                    current_file = None
            result.append({
                "id": row.id,
                "remote_task_id": row.remote_task_id,
                "source": row.source,
                "task_type": row.task_type,
                "title": row.title,
                "status": row.status,
                "total_count": row.total_count,
                "success_count": row.success_count,
                "failed_count": row.failed_count,
                "current_file": current_file,
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            })
        total = db.scalar(select(func.count()).select_from(DownloaderTaskSnapshot).where(DownloaderTaskSnapshot.node_key == node_key)) or 0
        return result, int(total)
