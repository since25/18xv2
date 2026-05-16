from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class PlanGenerateRequest(BaseModel):
    import_id: int
    node_ids: list[int] | None = None
    strategy_version: str = "rules-v1"
    dry_run: bool = True


class KeywordMovePlanGenerateRequest(BaseModel):
    import_id: int
    keyword: str | None = None
    keyword_entry_id: int | None = None
    target_path: str
    dry_run: bool = True
    case_sensitive: bool = False
    node_ids: list[int] | None = None


class OrganizeTaskPlanGenerateRequest(BaseModel):
    import_id: int
    keyword_entry_id: int | None = None
    task_ids: list[int] | None = None
    dry_run: bool = True


class ExecutePlanRequest(BaseModel):
    dry_run: bool = True
    confirm_real_run: bool = False
    requested_by: str | None = None
    operator_note: str | None = None


class BatchExecutePlanRequest(BaseModel):
    plan_ids: list[int]
    dry_run: bool = True
    confirm_real_run: bool = False
    requested_by: str | None = None
    operator_note: str | None = None


class BatchDeletePlanRequest(BaseModel):
    plan_ids: list[int]


class PlanItemResponse(ORMModel):
    id: int
    node_id: int
    source_path: str
    suggested_target_path: str
    action_type: str
    confidence: float
    conflict_status: str
    reason: str | None


class PlanResponse(ORMModel):
    id: int
    strategy_version: str
    scope_desc: str
    status: str
    dry_run: bool
    created_at: datetime
    items: list[PlanItemResponse] = []


class PlanBatchResponse(BaseModel):
    total: int
    plans: list["PlanResponse"]


class PlanSummaryResponse(ORMModel):
    id: int
    strategy_version: str
    scope_desc: str
    status: str
    dry_run: bool
    created_at: datetime
    item_count: int
    latest_job_id: int | None = None
    latest_job_status: str | None = None
    latest_job_dry_run: bool | None = None


class PlanSummaryPageResponse(BaseModel):
    total: int
    items: list[PlanSummaryResponse]


class ExecutionLogResponse(ORMModel):
    id: int
    node_id: int
    action_type: str
    before_path: str
    after_path: str
    api_status: str
    success: bool
    error_message: str | None
    raw_response: str | None
    created_at: datetime


class RollbackRecordResponse(ORMModel):
    id: int
    node_id: int
    log_id: int | None
    undo_action: str
    undo_payload: str | None
    status: str
    note: str | None
    created_at: datetime


class JobResponse(ORMModel):
    id: int
    plan_id: int
    dry_run: bool
    status: str
    requested_by: str | None
    operator_note: str | None
    confirmation_validated: bool
    rollback_status: str
    started_at: datetime
    finished_at: datetime | None
    logs: list[ExecutionLogResponse] = []
    rollback_records: list[RollbackRecordResponse] = []


class BatchPlanOperationResponse(BaseModel):
    requested_count: int
    processed_count: int
    jobs: list[JobResponse] = []
    deleted_plan_ids: list[int] = []
    skipped_plan_ids: list[int] = []
    errors: list[str] = []


class BatchPlanOperationLogResponse(BaseModel):
    id: int
    action: str
    requested_count: int
    processed_count: int
    requested_plan_ids: list[int] = []
    processed_plan_ids: list[int] = []
    skipped_plan_ids: list[int] = []
    errors: list[str] = []
    requested_by: str | None = None
    operator_note: str | None = None
    created_at: datetime


PlanBatchResponse.model_rebuild()
