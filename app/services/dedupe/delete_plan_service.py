from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dedupe import (
    DedupeCandidate,
    DedupeDeletePlan,
    DedupeDeletePlanItem,
    DedupeRemoteConfirmation,
)


@dataclass(slots=True)
class DedupeDeletePlanSummary:
    plan_id: int
    total: int
    deleted: int
    failed: int
    skipped: int


class DedupeDeletePlanService:
    def __init__(self, db: Session, client):
        self.db = db
        self.client = client

    def create_plan(
        self,
        *,
        name: str,
        candidate_ids: list[int],
        rate_limit_seconds: float = 2.0,
    ) -> DedupeDeletePlan:
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            raise ValueError("No candidates selected")

        candidates = list(
            self.db.scalars(
                select(DedupeCandidate)
                .where(DedupeCandidate.id.in_(unique_ids))
                .order_by(DedupeCandidate.id.asc())
            ).all()
        )
        missing_ids = set(unique_ids) - {candidate.id for candidate in candidates}
        if missing_ids:
            raise ValueError(f"Candidates not found: {sorted(missing_ids)}")

        plan_items = [self._prepare_plan_item(candidate) for candidate in candidates]
        tree_import_ids = {candidate.group.tree_import_id for candidate, _confirmation in plan_items}
        if len(tree_import_ids) != 1:
            raise ValueError("All candidates in a delete plan must belong to the same tree import")

        first_candidate = plan_items[0][0]
        plan = DedupeDeletePlan(
            name=name,
            tree_import_id=first_candidate.group.tree_import_id,
            source_scan_run_id=first_candidate.group.scan_run_id,
            rate_limit_seconds=rate_limit_seconds,
            status="draft",
        )
        self.db.add(plan)
        self.db.flush()

        for candidate, confirmation in plan_items:
            self.db.add(
                DedupeDeletePlanItem(
                    plan_id=plan.id,
                    candidate_id=candidate.id,
                    node_file_id=candidate.node_file_id,
                    remote_file_id=str(confirmation.remote_file_id),
                    raw_path=candidate.raw_path,
                    remote_path=confirmation.remote_path,
                    confirmation_level=candidate.group.confidence_level,
                    delete_reason=candidate.user_reason or candidate.suggested_reason or "人工确认删除",
                    status="pending",
                )
            )

        plan.total_items = len(plan_items)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def execute_plan(
        self,
        plan_id: int,
        *,
        confirm: bool,
        sleep_seconds: float | None = None,
    ) -> DedupeDeletePlanSummary:
        if not confirm:
            raise ValueError("confirm must be true")
        if self.client is None:
            raise ValueError("client is required to execute a delete plan")

        plan = self.db.get(DedupeDeletePlan, plan_id)
        if plan is None:
            raise ValueError(f"Delete plan {plan_id} not found")

        plan.status = "running"
        plan.confirmed_at = plan.confirmed_at or datetime.now(UTC)
        plan.started_at = datetime.now(UTC)
        self.db.commit()

        deleted = 0
        failed = 0
        skipped = 0
        delay = plan.rate_limit_seconds if sleep_seconds is None else sleep_seconds
        items = sorted(plan.items, key=lambda item: item.id)
        for item in items:
            if item.status != "pending":
                skipped += 1
                continue
            try:
                item.status = "deleting"
                self.db.commit()
                self.client.delete_node(item.remote_file_id, dry_run=False)
                item.status = "deleted"
                item.deleted_at = datetime.now(UTC)
                deleted += 1
            except Exception as exc:  # noqa: BLE001 - per-item audit should capture client errors
                item.status = "failed"
                item.error_message = str(exc)
                failed += 1
            self.db.commit()
            if delay > 0:
                time.sleep(delay)

        plan.deleted_count = deleted
        plan.failed_count = failed
        plan.skipped_count = skipped
        plan.total_items = len(items)
        plan.status = "completed_with_errors" if failed else "completed"
        plan.finished_at = datetime.now(UTC)
        self.db.commit()
        return DedupeDeletePlanSummary(plan.id, len(items), deleted, failed, skipped)

    def _prepare_plan_item(self, candidate: DedupeCandidate) -> tuple[DedupeCandidate, DedupeRemoteConfirmation]:
        if candidate.user_action != "delete":
            raise ValueError(f"Candidate {candidate.id} is not marked for delete")
        if candidate.group.confidence_level == "filename_suspected":
            raise ValueError(f"Candidate {candidate.id} is filename_suspected and cannot enter a delete plan")

        confirmation = self._latest_resolved_confirmation(candidate.id)
        if confirmation is None or not confirmation.remote_file_id:
            raise ValueError(f"Candidate {candidate.id} has no resolved remote confirmation")
        return candidate, confirmation

    def _latest_resolved_confirmation(self, candidate_id: int) -> DedupeRemoteConfirmation | None:
        return self.db.scalar(
            select(DedupeRemoteConfirmation)
            .where(DedupeRemoteConfirmation.candidate_id == candidate_id)
            .where(DedupeRemoteConfirmation.status == "resolved")
            .order_by(DedupeRemoteConfirmation.id.desc())
        )
