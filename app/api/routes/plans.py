from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_115_client, get_db
from app.models.organization import BatchPlanOperationLog, ExecutionJob, OrganizationPlan
from app.schemas.plans import (
    BatchDeletePlanRequest,
    BatchExecutePlanRequest,
    BatchPlanOperationLogResponse,
    BatchPlanOperationResponse,
    ExecutePlanRequest,
    JobResponse,
    KeywordMovePlanGenerateRequest,
    OrganizeTaskPlanGenerateRequest,
    PlanBatchResponse,
    PlanResponse,
    PlanGenerateRequest,
    PlanSummaryPageResponse,
    PlanSummaryResponse,
)
from app.services.client_115.client import Real115Client
from app.services.executor.executor import PlanExecutor
from app.services.planner.plan_service import PlanService
from app.services.strategy_rule_service import StrategyRuleService

router = APIRouter(prefix="/plans", tags=["plans"])


def _dump_json_list(values: list[int] | list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _load_json_int_list(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[int] = []
    for item in parsed:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _load_json_str_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _to_batch_log_response(log: BatchPlanOperationLog) -> BatchPlanOperationLogResponse:
    return BatchPlanOperationLogResponse(
        id=log.id,
        action=log.action,
        requested_count=log.requested_count,
        processed_count=log.processed_count,
        requested_plan_ids=_load_json_int_list(log.requested_plan_ids),
        processed_plan_ids=_load_json_int_list(log.processed_plan_ids),
        skipped_plan_ids=_load_json_int_list(log.skipped_plan_ids),
        errors=_load_json_str_list(log.error_details),
        requested_by=log.requested_by,
        operator_note=log.operator_note,
        created_at=log.created_at,
    )


def _list_plan_summaries(
    db: Session,
    *,
    min_item_count: int | None = None,
    max_item_count: int | None = None,
    latest_job_status: str | None = None,
    include_completed: bool = True,
) -> list[PlanSummaryResponse]:
    plans = list(
        db.scalars(
            select(OrganizationPlan)
            .order_by(OrganizationPlan.id.desc())
            .options(selectinload(OrganizationPlan.items), selectinload(OrganizationPlan.jobs))
        ).all()
    )
    summaries: list[PlanSummaryResponse] = []
    for plan in plans:
        latest_job = max(plan.jobs, key=lambda item: item.id) if plan.jobs else None
        summaries.append(
            PlanSummaryResponse(
                id=plan.id,
                strategy_version=plan.strategy_version,
                scope_desc=plan.scope_desc,
                status=plan.status,
                dry_run=plan.dry_run,
                created_at=plan.created_at,
                item_count=len(plan.items),
                latest_job_id=latest_job.id if latest_job else None,
                latest_job_status=latest_job.status if latest_job else None,
                latest_job_dry_run=latest_job.dry_run if latest_job else None,
            )
        )
    filtered: list[PlanSummaryResponse] = []
    for summary in summaries:
        if min_item_count is not None and summary.item_count < min_item_count:
            continue
        if max_item_count is not None and summary.item_count > max_item_count:
            continue
        if latest_job_status:
            normalized_filter = latest_job_status.strip().lower()
            normalized_actual = (summary.latest_job_status or "none").strip().lower()
            if normalized_filter != normalized_actual:
                continue
        elif not include_completed and (summary.latest_job_status or "").strip().lower() == "completed":
            continue
        filtered.append(summary)
    return filtered


@router.get("/data", response_model=PlanSummaryPageResponse)
def list_plans(
    min_item_count: int | None = None,
    max_item_count: int | None = None,
    latest_job_status: str | None = None,
    include_completed: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> PlanSummaryPageResponse:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    # 无筛选时直接在 SQL 层分页，避免计划数量增长后把所有 items/jobs
    # 一次性加载到内存。带统计筛选的旧逻辑仍保留，确保筛选语义不变。
    if (
        min_item_count is None
        and max_item_count is None
        and latest_job_status is None
        and include_completed
    ):
        total = db.scalar(select(func.count()).select_from(OrganizationPlan)) or 0
        plans = list(
            db.scalars(
                select(OrganizationPlan)
                .order_by(OrganizationPlan.id.desc())
                .offset(safe_offset)
                .limit(safe_limit)
                .options(selectinload(OrganizationPlan.items), selectinload(OrganizationPlan.jobs))
            ).all()
        )
        items: list[PlanSummaryResponse] = []
        for plan in plans:
            latest_job = max(plan.jobs, key=lambda item: item.id) if plan.jobs else None
            items.append(
                PlanSummaryResponse(
                    id=plan.id,
                    strategy_version=plan.strategy_version,
                    scope_desc=plan.scope_desc,
                    status=plan.status,
                    dry_run=plan.dry_run,
                    created_at=plan.created_at,
                    item_count=len(plan.items),
                    latest_job_id=latest_job.id if latest_job else None,
                    latest_job_status=latest_job.status if latest_job else None,
                    latest_job_dry_run=latest_job.dry_run if latest_job else None,
                )
            )
        return PlanSummaryPageResponse(total=int(total), items=items)

    summaries = _list_plan_summaries(
        db,
        min_item_count=min_item_count,
        max_item_count=max_item_count,
        latest_job_status=latest_job_status,
        include_completed=include_completed,
    )
    return PlanSummaryPageResponse(total=len(summaries), items=summaries[safe_offset : safe_offset + safe_limit])


@router.post("/batch-execute", response_model=BatchPlanOperationResponse)
def batch_execute_plans(
    payload: BatchExecutePlanRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
) -> BatchPlanOperationResponse:
    executor = PlanExecutor(db, client=client_115)
    jobs: list[JobResponse] = []
    errors: list[str] = []
    processed_count = 0
    processed_plan_ids: list[int] = []
    seen_plan_ids: list[int] = []
    for plan_id in payload.plan_ids:
        if plan_id in seen_plan_ids:
            continue
        seen_plan_ids.append(plan_id)
        try:
            job = executor.execute_plan(
                plan_id=plan_id,
                dry_run=payload.dry_run,
                confirm_real_run=payload.confirm_real_run,
                requested_by=payload.requested_by,
                operator_note=payload.operator_note,
            )
            hydrated = db.scalar(
                select(ExecutionJob)
                .where(ExecutionJob.id == job.id)
                .options(selectinload(ExecutionJob.logs), selectinload(ExecutionJob.rollback_records))
            )
            if hydrated is not None:
                jobs.append(JobResponse.model_validate(hydrated))
            processed_count += 1
            processed_plan_ids.append(plan_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"plan_id={plan_id}: {exc}")
    db.add(
        BatchPlanOperationLog(
            action="batch_execute",
            requested_count=len(payload.plan_ids),
            processed_count=processed_count,
            requested_plan_ids=_dump_json_list(payload.plan_ids),
            processed_plan_ids=_dump_json_list(processed_plan_ids),
            skipped_plan_ids=_dump_json_list([]),
            error_details=_dump_json_list(errors),
            requested_by=payload.requested_by,
            operator_note=payload.operator_note,
        )
    )
    db.commit()
    return BatchPlanOperationResponse(
        requested_count=len(payload.plan_ids),
        processed_count=processed_count,
        jobs=jobs,
        errors=errors,
    )


@router.post("/batch-delete", response_model=BatchPlanOperationResponse)
def batch_delete_plans(payload: BatchDeletePlanRequest, db: Session = Depends(get_db)) -> BatchPlanOperationResponse:
    deleted_plan_ids: list[int] = []
    skipped_plan_ids: list[int] = []
    for plan_id in payload.plan_ids:
        plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan_id))
        if plan is None:
            skipped_plan_ids.append(plan_id)
            continue
        db.delete(plan)
        deleted_plan_ids.append(plan_id)
    db.add(
        BatchPlanOperationLog(
            action="batch_delete",
            requested_count=len(payload.plan_ids),
            processed_count=len(deleted_plan_ids),
            requested_plan_ids=_dump_json_list(payload.plan_ids),
            processed_plan_ids=_dump_json_list(deleted_plan_ids),
            skipped_plan_ids=_dump_json_list(skipped_plan_ids),
            error_details=_dump_json_list([]),
        )
    )
    db.commit()
    return BatchPlanOperationResponse(
        requested_count=len(payload.plan_ids),
        processed_count=len(deleted_plan_ids),
        deleted_plan_ids=deleted_plan_ids,
        skipped_plan_ids=skipped_plan_ids,
    )


@router.get("/batch-logs", response_model=list[BatchPlanOperationLogResponse])
def list_batch_operation_logs(limit: int = 10, db: Session = Depends(get_db)) -> list[BatchPlanOperationLogResponse]:
    safe_limit = max(1, min(limit, 50))
    logs = list(
        db.scalars(select(BatchPlanOperationLog).order_by(BatchPlanOperationLog.id.desc()).limit(safe_limit)).all()
    )
    return [_to_batch_log_response(log) for log in logs]


@router.post("/generate", response_model=PlanResponse)
def generate_plan(payload: PlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plan = service.generate_plan(
            import_id=payload.import_id,
            strategy_version=payload.strategy_version,
            dry_run=payload.dry_run,
            node_ids=payload.node_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
    return PlanResponse.model_validate(plan)


@router.post("/keyword-generate", response_model=PlanResponse)
def generate_keyword_move_plan(payload: KeywordMovePlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plan = service.generate_keyword_move_plan(
            import_id=payload.import_id,
            keyword=payload.keyword,
            target_path=payload.target_path,
            dry_run=payload.dry_run,
            keyword_entry_id=payload.keyword_entry_id,
            case_sensitive=payload.case_sensitive,
            node_ids=payload.node_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
    return PlanResponse.model_validate(plan)


@router.post("/generate-from-tasks", response_model=PlanBatchResponse)
def generate_plan_from_organize_tasks(payload: OrganizeTaskPlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plans = service.generate_plan_from_tasks(
            import_id=payload.import_id,
            dry_run=payload.dry_run,
            keyword_entry_id=payload.keyword_entry_id,
            task_ids=payload.task_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hydrated_plans = [
        db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
        for plan in plans
    ]
    return PlanBatchResponse(total=len(hydrated_plans), plans=[PlanResponse.model_validate(plan) for plan in hydrated_plans if plan is not None])


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: int, db: Session = Depends(get_db)) -> PlanResponse:
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan_id).options(selectinload(OrganizationPlan.items)))
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse.model_validate(plan)


@router.post("/{plan_id}/execute", response_model=JobResponse)
def execute_plan(
    plan_id: int,
    payload: ExecutePlanRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
) -> JobResponse:
    executor = PlanExecutor(db, client=client_115)
    try:
        job = executor.execute_plan(
            plan_id=plan_id,
            dry_run=payload.dry_run,
            confirm_real_run=payload.confirm_real_run,
            requested_by=payload.requested_by,
            operator_note=payload.operator_note,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    job = db.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.id == job.id)
        .options(selectinload(ExecutionJob.logs), selectinload(ExecutionJob.rollback_records))
    )
    return JobResponse.model_validate(job)
