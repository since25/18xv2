from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import PurePosixPath
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.organization import ExecutionJob, ExecutionLog, ExecutionRollbackRecord, OrganizationPlan
from app.models.tasks import OrganizeTask
from app.services.client_115.client import Client115Error


class PlanExecutor:
    def __init__(self, db: Session, client=None):
        self.db = db
        self.client = client
        self.settings = get_settings()

    @staticmethod
    def _normalize_for_prefix_check(path: str) -> str:
        cleaned = path.strip().strip("/")
        if not cleaned:
            return ""
        return "/".join(part for part in cleaned.split("/") if part)

    def _ensure_allowed(self, source_path: str, dry_run: bool) -> None:
        if dry_run:
            return
        normalized_source = self._normalize_for_prefix_check(source_path)
        normalized_prefixes = [self._normalize_for_prefix_check(prefix) for prefix in self.settings.test_allowed_path_prefixes]
        if "" in normalized_prefixes:
            return
        if not any(
            normalized_source == prefix or normalized_source.startswith(f"{prefix}/")
            for prefix in normalized_prefixes
        ):
            raise PermissionError(f"Real execution is not allowed for path: {source_path}")

    def _validate_real_run_confirmation(self, confirm_real_run: bool, dry_run: bool) -> None:
        if dry_run:
            return
        if not confirm_real_run:
            raise ValueError("confirm_real_run must be true for real execution")

    @staticmethod
    def _path_parts(path: str) -> list[str]:
        cleaned = path.strip().strip("/")
        if not cleaned:
            return []
        return [part for part in cleaned.split("/") if part]

    def _client_path_parts(self, path: str) -> list[str]:
        if hasattr(self.client, "path_parts_for_display_path"):
            return self.client.path_parts_for_display_path(path)
        return self._path_parts(path)

    @staticmethod
    def _norm_name(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    def _find_child(self, parent_id: str, name: str, *, directories_only: bool = False) -> str | None:
        norm_name = self._norm_name(name)
        offset = 0
        limit = 500
        while True:
            listing = self.client.list_files(cid=parent_id, limit=limit, offset=offset, show_dir=1)
            data = listing.get("data", [])
            for item in data:
                if self._norm_name(item.get("fn", "")) != norm_name:
                    continue
                if directories_only and item.get("fc") != "0":
                    continue
                return str(item.get("fid"))
            count = int(listing.get("count") or len(data) or 0)
            offset += len(data)
            if not data or offset >= count:
                break
        return None

    def _resolve_path_to_id(self, path: str) -> str:
        parts = self._client_path_parts(path)
        if not parts:
            return "0"
        current_id = "0"
        for part in parts:
            matched_id = self._find_child(current_id, part)
            if matched_id is None:
                raise Client115Error(f"Path not found: {path}")
            current_id = matched_id
        return current_id

    def _ensure_directory(self, path: str, dry_run: bool) -> tuple[str, list[str]]:
        parts = self._client_path_parts(path)
        current_id = "0"
        created: list[str] = []
        for part in parts:
            matched_id = self._find_child(current_id, part, directories_only=True)
            if matched_id is not None:
                current_id = matched_id
                continue
            if dry_run:
                created.append(part)
                current_id = f"dry-run:{part}"
                continue
            created_result = self.client.create_folder(current_id, part)
            current_id = str(created_result.payload["file_id"])
            created.append(part)
        return current_id, created

    def _target_parent_and_name(self, target_path: str) -> tuple[str, str]:
        normalized = PurePosixPath(target_path.strip())
        target_name = normalized.name
        if not target_name:
            raise Client115Error("Target path is invalid")
        parent_path = str(normalized.parent)
        return parent_path, target_name

    @staticmethod
    def _encode_payload(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _extract_organize_task_id(reason: str | None) -> int | None:
        if not reason:
            return None
        matched = re.search(r"organize_task_id=(\d+)", reason)
        if not matched:
            return None
        return int(matched.group(1))

    @staticmethod
    def _paths_to_parent_path(paths: list[dict]) -> str:
        return "/".join(str(item.get("file_name")) for item in paths if item.get("file_name"))

    def _build_rollback_payload(
        self,
        *,
        source_id: str,
        source_name: str,
        source_info: dict,
        target_parent_id: str,
        target_parent_path: str,
        target_name: str,
    ) -> tuple[str, str] | None:
        original_parent_id = str(source_info.get("parent_id")) if source_info.get("parent_id") is not None else "0"
        original_parent_path = self._paths_to_parent_path(source_info.get("paths", []))
        rename_required = source_name != target_name
        move_required = original_parent_id != target_parent_id
        if not rename_required and not move_required:
            return None
        undo_action = "rename_and_move" if rename_required and move_required else "rename" if rename_required else "move"
        payload = {
            "file_id": source_id,
            "original_name": source_name,
            "original_parent_id": original_parent_id,
            "original_parent_path": original_parent_path,
            "applied_target_parent_id": target_parent_id,
            "applied_target_parent_path": target_parent_path,
            "applied_target_name": target_name,
        }
        return undo_action, self._encode_payload(payload)

    def _execute_item(self, item, dry_run: bool) -> tuple[bool, str, str | None, str | None, tuple[str, str] | None]:
        self._ensure_allowed(item.source_path, dry_run=dry_run)

        source_id = self._resolve_path_to_id(item.source_path)
        source_info = self.client.get_file(file_id=source_id).get("data", {})
        source_name = source_info.get("file_name") or PurePosixPath(item.source_path).name

        if item.action_type == "noop":
            return True, "noop", None, None, None

        target_parent_path, target_name = self._target_parent_and_name(item.suggested_target_path)
        target_parent_id, created_segments = self._ensure_directory(target_parent_path, dry_run=dry_run)
        raw_response = {"source_id": source_id, "target_parent_path": target_parent_path, "created_segments": created_segments}
        rollback_spec = None if dry_run else self._build_rollback_payload(
            source_id=source_id,
            source_name=source_name,
            source_info=source_info,
            target_parent_id=target_parent_id,
            target_parent_path=target_parent_path,
            target_name=target_name,
        )

        if not dry_run:
            conflict_id = self._find_child(target_parent_id, target_name)
            if conflict_id is not None and conflict_id != source_id:
                return False, "conflict", f"Target already contains: {target_name}", self._encode_payload(raw_response), None

        if dry_run:
            return True, "dry_run", None, self._encode_payload(raw_response), None

        if source_name != target_name:
            rename_result = self.client.rename_node(source_id, target_name, dry_run=False)
            raw_response["rename"] = rename_result.payload

        move_result = self.client.move_node(source_id, target_parent_id, dry_run=False)
        raw_response["move"] = move_result.payload
        return True, "success", None, self._encode_payload(raw_response), rollback_spec

    def execute_plan(
        self,
        plan_id: int,
        dry_run: bool = True,
        *,
        confirm_real_run: bool = False,
        requested_by: str | None = None,
        operator_note: str | None = None,
    ) -> ExecutionJob:
        plan = self.db.scalar(
            select(OrganizationPlan).where(OrganizationPlan.id == plan_id).options(selectinload(OrganizationPlan.items))
        )
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")
        if len(plan.items) > self.settings.executor_max_items_per_run:
            raise ValueError(
                f"Plan has {len(plan.items)} items, exceeding EXECUTOR_MAX_ITEMS_PER_RUN={self.settings.executor_max_items_per_run}"
            )
        self._validate_real_run_confirmation(confirm_real_run=confirm_real_run, dry_run=dry_run)

        job = ExecutionJob(
            plan_id=plan.id,
            dry_run=dry_run,
            status="running",
            requested_by=(requested_by or "").strip() or None,
            operator_note=(operator_note or "").strip() or None,
            confirmation_validated=dry_run or confirm_real_run,
            rollback_status="recording" if not dry_run else "not_required",
        )
        self.db.add(job)
        self.db.flush()

        rollback_count = 0
        has_blocked = False
        has_failed = False
        has_completed_action = False
        for item in plan.items:
            success = item.conflict_status in {"none", "noop"}
            api_status = "skipped"
            error_message = None
            raw_response = None
            rollback_spec = None

            try:
                if success:
                    success, api_status, error_message, raw_response, rollback_spec = self._execute_item(item, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                success = False
                api_status = "blocked"
                error_message = str(exc)

            log = ExecutionLog(
                job_id=job.id,
                node_id=item.node_id,
                action_type=item.action_type,
                before_path=item.source_path,
                after_path=item.suggested_target_path,
                api_status=api_status,
                success=success,
                error_message=error_message,
                raw_response=raw_response,
            )
            self.db.add(log)
            self.db.flush()

            if success and api_status in {"success", "dry_run", "noop"}:
                has_completed_action = True
            elif api_status == "blocked":
                has_blocked = True
            elif not success:
                has_failed = True

            organize_task_id = self._extract_organize_task_id(item.reason)
            if organize_task_id is not None and not dry_run:
                organize_task = self.db.get(OrganizeTask, organize_task_id)
                if organize_task is not None:
                    organize_task.executed_at = datetime.now(timezone.utc)
                    if success:
                        organize_task.status = "completed"
                        organize_task.failure_reason = None
                    else:
                        organize_task.status = "failed"
                        organize_task.failure_reason = error_message or api_status
                    note = f"job#{job.id}:{api_status}"
                    if organize_task.operation_log:
                        organize_task.operation_log = f"{organize_task.operation_log}\n{note}"
                    else:
                        organize_task.operation_log = note

            if not dry_run and success and rollback_spec is not None:
                undo_action, undo_payload = rollback_spec
                self.db.add(
                    ExecutionRollbackRecord(
                        job_id=job.id,
                        node_id=item.node_id,
                        log_id=log.id,
                        undo_action=undo_action,
                        undo_payload=undo_payload,
                        status="recorded",
                        note="Recorded before irreversible execution for later rollback tooling.",
                    )
                )
                rollback_count += 1

        if has_blocked:
            job.status = "blocked"
        elif has_failed:
            job.status = "failed"
        elif has_completed_action or not plan.items:
            job.status = "completed"
        else:
            job.status = "completed"
        job.rollback_status = "recorded" if rollback_count else "not_required"
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(job)
        return job
