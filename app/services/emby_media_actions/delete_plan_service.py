from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyDeletePlan, EmbyDeletePlanItem, EmbyMediaMapping, EmbyMediaMappingPath
from app.services.emby_media_actions.path_guard import PathGuard


@dataclass(frozen=True, slots=True)
class EmbyDeleteSummary:
    plan_id: int
    total: int
    deleted: int
    failed: int
    blocked: int


class EmbyDeletePlanService:
    def __init__(self, db: Session, client_115, allowed_roots: list[str]) -> None:
        self.db = db
        self.client_115 = client_115
        self.path_guard = PathGuard(allowed_roots)

    def create_mapping_from_matches(
        self,
        *,
        emby_item_id: str,
        emby_item_type: str,
        emby_title: str,
        alist_url: str,
        mount_name: str,
        remote_path: str,
        remote_file_id: str | None,
        matches,
        emby_series_id: str | None = None,
        emby_season_id: str | None = None,
        emby_episode_id: str | None = None,
    ) -> EmbyMediaMapping:
        mapping = self.db.scalar(
            select(EmbyMediaMapping).where(
                EmbyMediaMapping.emby_item_id == emby_item_id,
                EmbyMediaMapping.alist_url == alist_url,
            )
        )
        is_new_mapping = mapping is None
        if mapping is None:
            mapping = EmbyMediaMapping(emby_item_id=emby_item_id, alist_url=alist_url)
            self.db.add(mapping)
        else:
            mapping.paths.clear()
            self.db.flush()
        mapping.emby_item_type = emby_item_type
        mapping.emby_title = emby_title
        mapping.emby_series_id = emby_series_id
        mapping.emby_season_id = emby_season_id
        mapping.emby_episode_id = emby_episode_id
        mapping.alist_mount_name = mount_name
        mapping.remote_provider = "115"
        mapping.remote_path = remote_path
        if is_new_mapping or remote_file_id:
            mapping.remote_file_id = remote_file_id
        self.db.flush()
        for match in self._unique_matches_by_resolved_path(matches):
            mapping.paths.append(
                EmbyMediaMappingPath(
                    path_role=match.path_role,
                    path=match.path,
                    root_name=match.root_name,
                    root_path=match.root_path,
                    file_size=match.file_size,
                    inode=match.inode,
                    link_count=match.link_count,
                )
            )
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    @staticmethod
    def _unique_matches_by_resolved_path(matches) -> list:
        unique_matches = []
        seen_paths: set[str] = set()
        for match in matches:
            resolved_path = str(Path(match.path).expanduser().resolve())
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            unique_matches.append(match)
        return unique_matches

    def create_plan_from_mapping(self, *, mapping_id: int, scope: str, source: str) -> EmbyDeletePlan:
        mapping = self.db.get(EmbyMediaMapping, mapping_id)
        if mapping is None:
            raise LookupError("mapping not found")
        target_mappings = self._target_mappings(mapping, scope)
        plan = EmbyDeletePlan(
            source=source,
            emby_item_id=mapping.emby_item_id,
            scope=scope,
            status="draft",
            summary=mapping.emby_title,
        )
        self.db.add(plan)
        self.db.flush()
        seen_local_paths: set[str] = set()
        seen_remote_file_ids: set[str] = set()
        for target_mapping in target_mappings:
            self._add_mapping_paths(plan.id, target_mapping, seen_local_paths)
            self._add_remote_file(plan.id, target_mapping, seen_remote_file_ids)
        self.db.flush()
        plan.total_items = len(plan.items)
        plan.blocked_count = sum(1 for item in plan.items if item.status == "blocked")
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _target_mappings(self, mapping: EmbyMediaMapping, scope: str) -> list[EmbyMediaMapping]:
        if scope in {"movie", "episode"}:
            return [mapping]
        if scope == "season":
            if not mapping.emby_season_id:
                raise ValueError("season scope requires emby_season_id")
            return list(
                self.db.scalars(
                    select(EmbyMediaMapping)
                    .where(EmbyMediaMapping.emby_season_id == mapping.emby_season_id)
                    .order_by(EmbyMediaMapping.id)
                )
            )
        if scope == "series":
            if not mapping.emby_series_id:
                raise ValueError("series scope requires emby_series_id")
            return list(
                self.db.scalars(
                    select(EmbyMediaMapping)
                    .where(EmbyMediaMapping.emby_series_id == mapping.emby_series_id)
                    .order_by(EmbyMediaMapping.id)
                )
            )
        return [mapping]

    def _add_mapping_paths(self, plan_id: int, mapping: EmbyMediaMapping, seen_local_paths: set[str]) -> None:
        for path in mapping.paths:
            if path.path_role == "source_strm":
                group = "source_strm"
            elif path.path_role == "organized_strm":
                group = "emby_library"
            else:
                continue
            if path.path in seen_local_paths:
                continue
            seen_local_paths.add(path.path)
            dry_run = self.path_guard.delete_path(path.path, dry_run=True)
            blocked_reason = dry_run.error_message if dry_run.status != "dry_run" else None
            self.db.add(
                EmbyDeletePlanItem(
                    plan_id=plan_id,
                    group=group,
                    target_type="file",
                    target_path=path.path,
                    display_name=path.path.rsplit("/", 1)[-1],
                    status="pending" if dry_run.status == "dry_run" else "blocked",
                    blocked_reason=blocked_reason,
                    dry_run_result=dry_run.status,
                )
            )

    def _add_remote_file(self, plan_id: int, mapping: EmbyMediaMapping, seen_remote_file_ids: set[str]) -> None:
        if not mapping.remote_file_id or mapping.remote_file_id in seen_remote_file_ids:
            return
        seen_remote_file_ids.add(mapping.remote_file_id)
        status = "pending"
        blocked_reason = None
        error_message = None
        dry_run_result = "dry_run"
        if mapping.remote_provider != "115":
            status = "blocked"
            blocked_reason = "unsupported_remote_provider"
            dry_run_result = "blocked"
        elif self.client_115 is None:
            status = "blocked"
            blocked_reason = "client_115_required"
            dry_run_result = "blocked"
        else:
            try:
                dry_run = self.client_115.delete_node(mapping.remote_file_id, dry_run=True)
                dry_run_result = self._remote_dry_run_result(dry_run)
            except Exception as exc:  # noqa: BLE001
                status = "blocked"
                blocked_reason = "remote_dry_run_failed"
                error_message = str(exc)
                dry_run_result = "blocked"
        self.db.add(
            EmbyDeletePlanItem(
                plan_id=plan_id,
                group="remote_115",
                target_type="remote_file",
                remote_file_id=mapping.remote_file_id,
                target_path=mapping.remote_path,
                display_name=mapping.remote_path.rsplit("/", 1)[-1] if mapping.remote_path else mapping.remote_file_id,
                status=status,
                blocked_reason=blocked_reason,
                error_message=error_message,
                dry_run_result=dry_run_result,
            )
        )

    @staticmethod
    def _remote_dry_run_result(result) -> str:
        for field in ("message", "action", "payload"):
            value = getattr(result, field, None)
            if value:
                return str(value)
        return str(result)

    def execute_plan(self, plan_id: int, *, confirm: bool) -> EmbyDeleteSummary:
        if not confirm:
            raise ValueError("confirm must be true")
        plan = self.db.get(EmbyDeletePlan, plan_id)
        if plan is None:
            raise LookupError("delete plan not found")
        if plan.status not in {"draft", "confirmed"}:
            raise ValueError("delete plan is not executable")
        plan.status = "running"
        plan.confirmed_at = plan.confirmed_at or datetime.now(UTC)
        plan.started_at = datetime.now(UTC)
        self.db.commit()
        deleted = failed = blocked = 0
        for item in sorted(plan.items, key=lambda row: row.id):
            if item.status != "pending":
                if item.status == "blocked":
                    blocked += 1
                continue
            try:
                if item.group == "remote_115":
                    if not self.client_115:
                        raise ValueError("115 client is required")
                    if not item.remote_file_id:
                        raise ValueError("remote_file_id is required")
                    self.client_115.delete_node(item.remote_file_id, dry_run=False)
                else:
                    if not item.target_path:
                        raise ValueError("target_path is required")
                    result = self.path_guard.delete_path(item.target_path, dry_run=False)
                    if result.status != "deleted":
                        raise ValueError(result.error_message or result.status)
                item.status = "deleted"
                item.executed_at = datetime.now(UTC)
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                item.status = "failed"
                item.error_message = str(exc)
                failed += 1
            self.db.commit()
        plan.deleted_count = deleted
        plan.failed_count = failed
        plan.blocked_count = blocked
        plan.status = "completed" if failed == 0 else "failed"
        plan.finished_at = datetime.now(UTC)
        self.db.commit()
        return EmbyDeleteSummary(plan.id, len(plan.items), deleted, failed, blocked)
