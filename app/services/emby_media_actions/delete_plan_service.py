from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyDeletePlan, EmbyDeletePlanItem, EmbyMediaMapping
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

    def create_plan_from_mapping(self, *, mapping_id: int, scope: str, source: str) -> EmbyDeletePlan:
        mapping = self.db.get(EmbyMediaMapping, mapping_id)
        if mapping is None:
            raise LookupError("mapping not found")
        plan = EmbyDeletePlan(
            source=source,
            emby_item_id=mapping.emby_item_id,
            scope=scope,
            status="draft",
            summary=mapping.emby_title,
        )
        self.db.add(plan)
        self.db.flush()
        for path in mapping.paths:
            if path.path_role == "source_strm":
                group = "source_strm"
            elif path.path_role == "organized_strm":
                group = "emby_library"
            else:
                continue
            decision = self.path_guard.classify(path.path)
            self.db.add(
                EmbyDeletePlanItem(
                    plan_id=plan.id,
                    group=group,
                    target_type="file",
                    target_path=path.path,
                    display_name=path.path.rsplit("/", 1)[-1],
                    status="blocked" if not decision.allowed else "pending",
                    blocked_reason=decision.reason,
                    dry_run_result="blocked" if not decision.allowed else "dry_run",
                )
            )
        if mapping.remote_file_id:
            self.db.add(
                EmbyDeletePlanItem(
                    plan_id=plan.id,
                    group="remote_115",
                    target_type="remote_file",
                    remote_file_id=mapping.remote_file_id,
                    target_path=mapping.remote_path,
                    display_name=mapping.remote_path.rsplit("/", 1)[-1] if mapping.remote_path else mapping.remote_file_id,
                    status="pending",
                    dry_run_result="dry_run",
                )
            )
        self.db.flush()
        plan.total_items = len(plan.items)
        plan.blocked_count = sum(1 for item in plan.items if item.status == "blocked")
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def execute_plan(self, plan_id: int, *, confirm: bool) -> EmbyDeleteSummary:
        if not confirm:
            raise ValueError("confirm must be true")
        plan = self.db.get(EmbyDeletePlan, plan_id)
        if plan is None:
            raise LookupError("delete plan not found")
        if plan.status not in {"draft", "confirmed", "failed"}:
            raise ValueError("delete plan is not executable")
        plan.status = "running"
        plan.confirmed_at = plan.confirmed_at or datetime.now(UTC)
        plan.started_at = datetime.now(UTC)
        self.db.commit()
        deleted = failed = blocked = 0
        for item in sorted(plan.items, key=lambda row: row.id):
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
