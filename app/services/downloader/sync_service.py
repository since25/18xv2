from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.downloader import (
    DownloaderPackage,
    DownloaderPackageCandidate,
    DownloaderSubmission,
    DownloaderSyncRun,
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


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


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
        "index_revision": _int(payload.get("index_revision"), 0) or None,
        "raw_payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "last_seen_at": now,
        "updated_at": now,
    }


class DownloaderSyncService:
    """在 18x 数据库中同步资源包、候选和下载任务。"""

    @staticmethod
    def sync_packages(db: Session, client: Any, *, node_key: str = "rn") -> SyncSummary:
        run = DownloaderSyncRun(kind="packages", status="running")
        db.add(run)
        db.flush()
        now = datetime.now(UTC)
        whitelist = list(
            db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "whitelist", KeywordEntry.status == "active")
                .options(selectinload(KeywordEntry.aliases))
            ).all()
        )
        blacklist = list(
            db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "blacklist", KeywordEntry.status == "active")
                .options(selectinload(KeywordEntry.aliases))
            ).all()
        )
        whitelist_terms = [(entry, _terms(entry)) for entry in whitelist]
        blacklist_terms = [term for entry in blacklist for term in _terms(entry)]
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
                    normalized_title = normalize_keyword_text(package.title).casefold()
                    blocked = any(term in normalized_title for _, term in blacklist_terms)
                    matched_entries: list[tuple[KeywordEntry, str]] = []
                    if package.boundary_status == "stable" and not package.has_successful_attempt and not blocked:
                        for entry, terms in whitelist_terms:
                            for display, term in terms:
                                if term in normalized_title:
                                    matched_entries.append((entry, display))
                                    break
                    existing_candidates = list(
                        db.scalars(
                            select(DownloaderPackageCandidate).where(
                                DownloaderPackageCandidate.package_id == package.id
                            )
                        ).all()
                    )
                    matched_ids = {entry.id for entry, _ in matched_entries}
                    for candidate in existing_candidates:
                        if candidate.keyword_entry_id not in matched_ids and candidate.status in {"pending", "selected"}:
                            candidate.status = "dismissed"
                            candidate.dismissed_reason = "资源包状态或黑名单规则已排除"
                            dismissed += 1
                    for entry, display in matched_entries:
                        existing = next((item for item in existing_candidates if item.keyword_entry_id == entry.id), None)
                        if existing is None:
                            db.add(
                                DownloaderPackageCandidate(
                                    package_id=package.id,
                                    keyword_entry_id=entry.id,
                                    matched_term=display,
                                    match_reason=f"标题命中白名单：{display}",
                                )
                            )
                            created += 1
                        elif existing.status == "dismissed" and existing.dismissed_reason == "资源包状态或黑名单规则已排除":
                            existing.status = "pending"
                            existing.dismissed_reason = None
                            existing.matched_term = display
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
            if candidate.status not in {"selected", "submitted"}:
                raise ValueError(f"candidate {candidate_id} 不是已选择状态")
            package = db.get(DownloaderPackage, candidate.package_id)
            if package is None or package.boundary_status != "stable":
                raise ValueError(f"candidate {candidate_id} 对应资源包已不可下载")
            revision = package.index_revision or 0
            key = f"18x:{node_key}:package:{package.remote_package_id}:r{revision}"
            existing = db.scalar(select(DownloaderSubmission).where(DownloaderSubmission.idempotency_key == key))
            if existing is not None and existing.status == "submitted":
                candidate.status = "submitted"
                skipped += 1
                items.append({"candidate_id": candidate.id, "submission_id": existing.id, "remote_task_id": existing.remote_task_id, "status": existing.status})
                continue
            try:
                payload = client.submit_package(package.remote_package_id, key)
                batch = payload.get("batch") if isinstance(payload, dict) else {}
                batch = batch if isinstance(batch, dict) else {}
                if existing is None:
                    existing = DownloaderSubmission(package_id=package.id, candidate_id=candidate.id, idempotency_key=key)
                    db.add(existing)
                existing.remote_batch_id = _int(batch.get("id"), 0) or None
                existing.remote_task_id = str(batch.get("task_id")) if batch.get("task_id") else None
                existing.status = "submitted"
                existing.error_message = None
                candidate.status = "submitted"
                submitted += 1
                items.append({"candidate_id": candidate.id, "submission_id": existing.id, "remote_task_id": existing.remote_task_id, "status": existing.status})
            except DownloaderRemoteError as exc:
                if existing is None:
                    existing = DownloaderSubmission(package_id=package.id, candidate_id=candidate.id, idempotency_key=key)
                    db.add(existing)
                existing.status = "failed"
                existing.error_message = str(exc)
                db.commit()
                raise
            except Exception as exc:
                if existing is None:
                    existing = DownloaderSubmission(package_id=package.id, candidate_id=candidate.id, idempotency_key=key)
                    db.add(existing)
                existing.status = "failed"
                existing.error_message = str(exc)
                failed += 1
                items.append({"candidate_id": candidate.id, "submission_id": existing.id, "status": "failed", "error": "remote submission failed"})
        db.commit()
        return SubmissionSummary(submitted, skipped, failed, items)

    @staticmethod
    def sync_tasks(db: Session, client: Any, *, node_key: str = "rn") -> TaskSyncSummary:
        tasks = client.list_tasks()
        updated = 0
        for summary in tasks:
            task_id = str(summary.get("task_id") or summary.get("id") or "")
            if not task_id:
                continue
            try:
                payload = client.get_task(task_id)
            except Exception:
                payload = summary
            current_file = payload.get("current_file")
            snapshot = db.scalar(
                select(DownloaderTaskSnapshot).where(
                    DownloaderTaskSnapshot.node_key == node_key,
                    DownloaderTaskSnapshot.remote_task_id == task_id,
                )
            )
            if snapshot is None:
                snapshot = DownloaderTaskSnapshot(node_key=node_key, remote_task_id=task_id)
                db.add(snapshot)
            snapshot.source = payload.get("source")
            snapshot.task_type = payload.get("task_type")
            snapshot.title = payload.get("title")
            snapshot.status = str(payload.get("status") or "unknown")
            snapshot.total_count = _int(payload.get("total_count"))
            snapshot.success_count = _int(payload.get("success_count"))
            snapshot.failed_count = _int(payload.get("failed_count"))
            snapshot.current_file_json = json.dumps(current_file, ensure_ascii=False) if current_file is not None else None
            snapshot.raw_payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            snapshot.observed_at = datetime.now(UTC)
            updated += 1
            submissions = list(db.scalars(select(DownloaderSubmission).where(DownloaderSubmission.remote_task_id == task_id)).all())
            for submission in submissions:
                status = snapshot.status
                if status in {"completed", "completed_with_errors"}:
                    submission.status = "completed" if status == "completed" else "failed"
                elif status in {"failed", "cancelled"}:
                    submission.status = status
                candidate = db.get(DownloaderPackageCandidate, submission.candidate_id) if submission.candidate_id else None
                if candidate is not None and candidate.status == "submitted" and submission.status in {"completed", "failed", "cancelled"}:
                    candidate.status = "completed" if submission.status == "completed" else "failed"
        db.commit()
        return TaskSyncSummary(len(tasks), updated)

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
