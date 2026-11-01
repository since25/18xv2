from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.downloader import (
    DownloaderPackage,
    DownloaderPackageCandidate,
    DownloaderSubmission,
    DownloaderTaskSnapshot,
)
from app.models.keywords import KeywordEntry
from app.services.downloader.sync_service import DownloaderSyncService, _load_terms, _match_package


_ACTIVE_STATUSES = {"pending", "queued", "running", "downloading", "paused"}
_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}
_FAILED_FILE_STATUSES = {"failed", "download_failed", "upload_failed"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_object(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _byte_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _file_row(file_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(file_payload.get("message_id") or file_payload.get("id") or ""),
        "filename": file_payload.get("filename") or file_payload.get("file_name"),
        "status": file_payload.get("status"),
        "total_size": _byte_value(file_payload.get("total_size_bytes", file_payload.get("total_size"))),
        "downloaded_size": _byte_value(
            file_payload.get("downloaded_size_bytes", file_payload.get("downloaded_size"))
        ),
        "error": file_payload.get("error"),
    }


class DownloaderQueryService:
    """下载器收件箱、任务看板和统计信息的查询服务。"""

    @staticmethod
    def _filter_candidates(
        package: DownloaderPackage,
        candidates: list[DownloaderPackageCandidate],
        *,
        current_only: bool,
        statuses: set[str] | None = None,
    ) -> list[DownloaderPackageCandidate]:
        if current_only:
            revision = package.index_revision or 0
            candidates = [candidate for candidate in candidates if candidate.package_revision == revision]
        if statuses is not None:
            candidates = [candidate for candidate in candidates if candidate.status in statuses]
        return candidates

    @staticmethod
    def _keyword_names(db: Session, candidates: list[DownloaderPackageCandidate]) -> dict[int, KeywordEntry]:
        ids = {candidate.keyword_entry_id for candidate in candidates}
        if not ids:
            return {}
        return {
            entry.id: entry
            for entry in db.scalars(select(KeywordEntry).where(KeywordEntry.id.in_(ids))).all()
        }

    @staticmethod
    def _inbox_matches(
        package: DownloaderPackage,
        candidates: list[DownloaderPackageCandidate],
        *,
        view: Literal["candidates", "ignored", "unmatched"],
        download_status: str | None,
        keyword_entry_id: int | None,
        search: str | None,
        channel_title: str | None = None,
    ) -> bool:
        if view == "candidates":
            if package.ignored_at is not None or not candidates:
                return False
        elif view == "unmatched":
            # 未命中：没被忽略，且当前版本没有任何未作废的白名单候选
            if package.ignored_at is not None or candidates:
                return False
        elif package.ignored_at is None:
            return False
        if download_status == "failed":
            if package.current_download_status not in {"failed", "cancelled"}:
                return False
        elif download_status and package.current_download_status != download_status:
            return False
        if keyword_entry_id is not None and not any(
            candidate.keyword_entry_id == keyword_entry_id for candidate in candidates
        ):
            return False
        if search and search.casefold() not in (package.title or "").casefold():
            return False
        if channel_title and package.channel_title != channel_title:
            return False
        return True

    @staticmethod
    def _inbox_item(
        db: Session,
        package: DownloaderPackage,
        candidates: list[DownloaderPackageCandidate],
    ) -> dict[str, Any]:
        keywords = DownloaderQueryService._keyword_names(db, candidates)
        raw = _json_object(package.raw_payload_json) or {}
        completed_media_count = package.completed_media_count
        new_media_count = None
        if (
            package.current_download_status == "outdated"
            and package.media_count is not None
            and completed_media_count is not None
            and package.media_count - completed_media_count > 0
        ):
            new_media_count = package.media_count - completed_media_count
        return {
            "package_id": package.id,
            "remote_package_id": package.remote_package_id,
            "title": package.title,
            "channel_title": package.channel_title,
            "published_at": package.published_at,
            "media_count": package.media_count,
            "known_total_size": package.known_total_size,
            "current_download_status": package.current_download_status,
            "boundary_status": package.boundary_status,
            "index_revision": package.index_revision,
            "completed_revision": package.completed_revision,
            "new_media_count": new_media_count,
            "candidate_ids": [candidate.id for candidate in candidates],
            "keywords": [
                {
                    "keyword_entry_id": candidate.keyword_entry_id,
                    "keyword": keywords[candidate.keyword_entry_id].canonical_name
                    if candidate.keyword_entry_id in keywords
                    else "",
                    "matched_term": candidate.matched_term,
                }
                for candidate in candidates
            ],
            "ignored_at": _iso(_aware(package.ignored_at)),
            "ignored_reason": package.ignored_reason,
            # RN 提供的失败原因码：本包最近一次下载失败原因、频道级错误（如频道不可访问）
            "last_download_error": raw.get("last_download_error"),
            "channel_error": raw.get("channel_last_error"),
        }

    @staticmethod
    def list_inbox(
        db: Session,
        *,
        view: Literal["candidates", "ignored", "unmatched"],
        download_status: str | None = None,
        keyword_entry_id: int | None = None,
        search: str | None = None,
        channel_title: str | None = None,
        sort: Literal["published_at", "size", "media_count"] = "published_at",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        packages = list(db.scalars(select(DownloaderPackage).order_by(DownloaderPackage.id)).all())
        # 一次取出全部候选再按资源包分组，避免逐包查询（资源包数万时会慢到数十秒）
        all_candidates_by_package: dict[int, list[DownloaderPackageCandidate]] = {}
        for candidate in db.scalars(
            select(DownloaderPackageCandidate).order_by(DownloaderPackageCandidate.id)
        ).all():
            all_candidates_by_package.setdefault(candidate.package_id, []).append(candidate)
        # 各视图用到的候选口径：待确认看 pending/selected，已忽略和未命中先取全部
        view_statuses: dict[str, set[str] | None] = {
            "candidates": {"pending", "selected"},
            "ignored": None,
            "unmatched": None,
        }
        filters = {
            "download_status": download_status,
            "keyword_entry_id": keyword_entry_id,
            "search": search,
            "channel_title": channel_title,
        }
        matching: list[tuple[DownloaderPackage, list[DownloaderPackageCandidate]]] = []
        counts = {name: 0 for name in view_statuses}
        for package in packages:
            package_candidates = all_candidates_by_package.get(package.id, [])
            for name, statuses in view_statuses.items():
                candidates = DownloaderQueryService._filter_candidates(
                    package, package_candidates, current_only=True, statuses=statuses
                )
                if name == "unmatched":
                    # 已作废的候选不算命中（如黑名单排除），提交后状态各异，所以按排除法判断
                    candidates = [candidate for candidate in candidates if candidate.status != "dismissed"]
                if not DownloaderQueryService._inbox_matches(package, candidates, view=name, **filters):
                    continue
                counts[name] += 1
                if name == view:
                    matching.append((package, candidates))

        def sort_key(item: tuple[DownloaderPackage, list[DownloaderPackageCandidate]]):
            package = item[0]
            if sort == "size":
                return package.known_total_size or 0
            if sort == "media_count":
                return package.media_count or 0
            return package.published_at or ""

        matching.sort(key=sort_key, reverse=True)
        safe_page = max(page, 1)
        safe_size = min(max(page_size, 1), 200)
        start = (safe_page - 1) * safe_size
        items = [DownloaderQueryService._inbox_item(db, package, candidates) for package, candidates in matching[start : start + safe_size]]
        return items, len(matching), counts

    @staticmethod
    def ignore_packages(
        db: Session,
        *,
        candidate_ids: list[int] | None = None,
        package_ids: list[int] | None = None,
        reason: str | None = None,
    ) -> int:
        ids = {int(package_id) for package_id in package_ids or []}
        if candidate_ids:
            ids.update(
                db.scalars(
                    select(DownloaderPackageCandidate.package_id).where(
                        DownloaderPackageCandidate.id.in_(candidate_ids)
                    )
                ).all()
            )
        if not ids:
            return 0
        packages = list(db.scalars(select(DownloaderPackage).where(DownloaderPackage.id.in_(ids))).all())
        now = datetime.now(UTC)
        ignored = 0
        for package in packages:
            if package.ignored_at is not None:
                continue
            package.ignored_at = now
            package.ignored_reason = reason
            ignored += 1
            for candidate in db.scalars(
                select(DownloaderPackageCandidate).where(
                    DownloaderPackageCandidate.package_id == package.id,
                    DownloaderPackageCandidate.status.in_(["pending", "selected"]),
                )
            ).all():
                candidate.status = "dismissed"
                candidate.dismissed_reason = "ignored"
        db.commit()
        return ignored

    @staticmethod
    def ignore_channel(db: Session, channel_title: str, *, reason: str | None = None) -> list[int]:
        """忽略某频道当前在收件箱里的全部资源包，返回被忽略的资源包 id 以便撤销。"""
        package_ids = list(
            db.scalars(
                select(DownloaderPackage.id)
                .join(DownloaderPackageCandidate, DownloaderPackageCandidate.package_id == DownloaderPackage.id)
                .where(
                    DownloaderPackage.channel_title == channel_title,
                    DownloaderPackage.ignored_at.is_(None),
                    DownloaderPackageCandidate.status.in_(["pending", "selected"]),
                    DownloaderPackageCandidate.package_revision == func.coalesce(DownloaderPackage.index_revision, 0),
                )
                .distinct()
                .order_by(DownloaderPackage.id)
            ).all()
        )
        if package_ids:
            DownloaderQueryService.ignore_packages(db, package_ids=package_ids, reason=reason)
        return package_ids

    @staticmethod
    def unignore_packages(db: Session, package_ids: list[int]) -> int:
        if not package_ids:
            return 0
        packages = list(
            db.scalars(
                select(DownloaderPackage).where(
                    DownloaderPackage.id.in_(package_ids), DownloaderPackage.ignored_at.is_not(None)
                )
            ).all()
        )
        if not packages:
            return 0
        whitelist_terms, blacklist_terms = _load_terms(db)
        restored = 0
        for package in packages:
            package.ignored_at = None
            package.ignored_reason = None
            _match_package(db, package, whitelist_terms, blacklist_terms)
            restored += 1
        db.commit()
        return restored

    @staticmethod
    def _task_packages(db: Session, task_ids: set[str]) -> dict[str, list[tuple[DownloaderPackage, int | None]]]:
        if not task_ids:
            return {}
        rows = db.execute(
            select(DownloaderSubmission, DownloaderPackage)
            .join(DownloaderPackage, DownloaderPackage.id == DownloaderSubmission.package_id)
            .where(DownloaderSubmission.remote_task_id.in_(task_ids))
        ).all()
        result: dict[str, list[tuple[DownloaderPackage, int | None]]] = {}
        for submission, package in rows:
            if submission.remote_task_id:
                result.setdefault(submission.remote_task_id, []).append((package, submission.candidate_id))
        return result

    @staticmethod
    def _task_row(
        snapshot: DownloaderTaskSnapshot,
        packages: list[tuple[DownloaderPackage, int | None]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_file = _json_object(snapshot.current_file_json)
        package = packages[0][0] if packages else None
        started_at = _aware(snapshot.remote_created_at)
        finished_at = _aware(snapshot.finished_at)
        now_value = _aware(now) or datetime.now(UTC)
        duration_seconds = None
        if started_at:
            duration_seconds = max(int(((finished_at or now_value) - started_at).total_seconds()), 0)
        return {
            "id": snapshot.id,
            "remote_task_id": snapshot.remote_task_id,
            "source": snapshot.source,
            "task_type": snapshot.task_type,
            "title": snapshot.title,
            "status": snapshot.status,
            "total_count": snapshot.total_count,
            "success_count": snapshot.success_count,
            "failed_count": snapshot.failed_count,
            "current_file": current_file,
            "observed_at": _iso(_aware(snapshot.observed_at)),
            "remote_created_at": _iso(started_at),
            "remote_updated_at": _iso(_aware(snapshot.remote_updated_at)),
            "finished_at": _iso(finished_at),
            "total_bytes": snapshot.total_bytes,
            "downloaded_bytes": snapshot.downloaded_bytes,
            "channel_title": snapshot.channel_title or (package.channel_title if package else None),
            "duration_seconds": duration_seconds,
            "download_speed_bytes": _byte_value(current_file.get("download_speed_bytes")) if current_file else 0,
            "package_id": package.id if package else None,
            "package_title": package.title if package else None,
        }

    @staticmethod
    def list_tasks(
        db: Session,
        *,
        node_key: str,
        status: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        channel: str | None = None,
        keyword_entry_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        snapshots = list(
            db.scalars(select(DownloaderTaskSnapshot).where(DownloaderTaskSnapshot.node_key == node_key)).all()
        )
        package_map = DownloaderQueryService._task_packages(db, {snapshot.remote_task_id for snapshot in snapshots})
        wanted_statuses: set[str] | None = None
        if status:
            wanted_statuses = set()
            for value in status:
                wanted_statuses.update(_ACTIVE_STATUSES if value == "active" else {value})
        since_value = _aware(since)
        until_value = _aware(until)
        filtered: list[tuple[DownloaderTaskSnapshot, list[tuple[DownloaderPackage, int | None]]]] = []
        for snapshot in snapshots:
            created = _aware(snapshot.remote_created_at)
            if wanted_statuses is not None and snapshot.status not in wanted_statuses:
                continue
            if since_value is not None or until_value is not None:
                if created is None:
                    continue
                if since_value is not None and created < since_value:
                    continue
                if until_value is not None and created > until_value:
                    continue
            packages = package_map.get(snapshot.remote_task_id, [])
            if channel and (snapshot.channel_title or (packages[0][0].channel_title if packages else None)) != channel:
                continue
            if keyword_entry_id is not None:
                if not any(
                    candidate_id is not None
                    and db.scalar(select(DownloaderPackageCandidate.keyword_entry_id).where(DownloaderPackageCandidate.id == candidate_id))
                    == keyword_entry_id
                    for _, candidate_id in packages
                ):
                    continue
            if search:
                search_value = search.casefold()
                if search_value not in (snapshot.title or "").casefold() and not any(
                    search_value in (package.title or "").casefold() for package, _ in packages
                ):
                    continue
            filtered.append((snapshot, packages))

        filtered.sort(
            key=lambda item: (
                _aware(item[0].remote_created_at) is not None,
                _aware(item[0].remote_created_at) or datetime.min.replace(tzinfo=UTC),
                item[0].id,
            ),
            reverse=True,
        )
        safe_page = max(page, 1)
        safe_size = min(max(page_size, 1), 200)
        start = (safe_page - 1) * safe_size
        return [DownloaderQueryService._task_row(snapshot, packages) for snapshot, packages in filtered[start : start + safe_size]], len(filtered)

    @staticmethod
    def task_detail(db: Session, task_id: str, *, node_key: str) -> dict[str, Any] | None:
        snapshot = db.scalar(
            select(DownloaderTaskSnapshot).where(
                DownloaderTaskSnapshot.node_key == node_key,
                DownloaderTaskSnapshot.remote_task_id == str(task_id),
            )
        )
        if snapshot is None:
            return None
        packages = DownloaderQueryService._task_packages(db, {snapshot.remote_task_id}).get(snapshot.remote_task_id, [])
        history = DownloaderSyncService.list_task_history(db, str(task_id), node_key=node_key, limit=50)
        raw_files = history[0].get("files", []) if history else []
        files = [_file_row(file_payload) for file_payload in raw_files if isinstance(file_payload, dict)]
        failed_files = [file_payload for file_payload in files if file_payload.get("status") in _FAILED_FILE_STATUSES]
        return {
            "task": DownloaderQueryService._task_row(snapshot, packages),
            "files": files,
            "failed_files": failed_files,
            "history": history,
        }

    @staticmethod
    def summary(db: Session, *, node_key: str, now: datetime) -> dict[str, int]:
        now_value = _aware(now) or datetime.now(UTC)
        local_now = now_value.astimezone(_SHANGHAI)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = local_start.astimezone(UTC)
        week_start = now_value - timedelta(days=7)
        snapshots = list(db.scalars(select(DownloaderTaskSnapshot).where(DownloaderTaskSnapshot.node_key == node_key)).all())
        today_count = today_bytes = week_count = week_bytes = week_failed_files = active_count = 0
        for snapshot in snapshots:
            if snapshot.status in _ACTIVE_STATUSES:
                active_count += 1
            if snapshot.status not in {"completed", "completed_with_errors"}:
                continue
            finished = _aware(snapshot.finished_at)
            if finished is None:
                continue
            if finished >= today_start:
                today_count += 1
                today_bytes += snapshot.downloaded_bytes or 0
            if finished >= week_start:
                week_count += 1
                week_bytes += snapshot.downloaded_bytes or 0
                week_failed_files += snapshot.failed_count or 0
        return {
            "today_count": today_count,
            "today_bytes": today_bytes,
            "week_count": week_count,
            "week_bytes": week_bytes,
            "active_count": active_count,
            "week_failed_files": week_failed_files,
        }

    @staticmethod
    def list_channels(db: Session) -> list[str]:
        values = set(
            value
            for value in db.scalars(select(DownloaderPackage.channel_title)).all()
            if value
        )
        values.update(value for value in db.scalars(select(DownloaderTaskSnapshot.channel_title)).all() if value)
        return sorted(values)
