from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db
from app.models.dedupe import DedupeCandidate, DedupeDeletePlan, DedupeDeletePlanItem, DedupeGroup
from app.schemas.dedupe import (
    DedupeActiveJobsResponse,
    DedupeCandidateResponse,
    DedupeConfirmJobRequest,
    DedupeDeletePlanCreateRequest,
    DedupeDeletePlanDetailResponse,
    DedupeDeletePlanExecuteRequest,
    DedupeDeletePlanItemResponse,
    DedupeDeletePlanListResponse,
    DedupeDeletePlanResponse,
    DedupeGroupDetailResponse,
    DedupeGroupListResponse,
    DedupeGroupResponse,
    DedupeJobFrame,
    DedupeReviewRequest,
    DedupeScanJobRequest,
)
from app.services.background_job_service import BackgroundJobService
from app.services.client_115.client import Real115Client
from app.services.dedupe.normalization import DedupeRuleSet
from app.services.dedupe.confirmation_service import DedupeConfirmationService
from app.services.dedupe.delete_plan_service import DedupeDeletePlanService
from app.services.dedupe.scan_service import DedupeScanOptions, DedupeScanService
from app.services.job_runner import JobAlreadyRunning, create_job, job_event_stream, submit_job

router = APIRouter(prefix="/dedupe", tags=["dedupe"])
logger = logging.getLogger(__name__)

# 任务状态只认 background_jobs 表；库里任务类型带 dedupe: 前缀，对外展示时去掉。


def _public_state(state: dict | None) -> dict | None:
    if state is None:
        return None
    result = dict(state)
    if result["job_type"] in {"scan", "confirm", "delete"}:
        return result
    if result["job_type"].startswith("dedupe:"):
        result["job_type"] = result["job_type"].split(":", 1)[1]
    return result


@router.post("/scan-jobs")
async def start_scan_job(payload: DedupeScanJobRequest, db: Session = Depends(get_db)) -> dict:
    try:
        job_id = create_job(db, "dedupe:scan")
    except JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="已有去重扫描任务在运行")

    def work(session, cb):
        cb("本地文件名扫描", 0, 0)
        summary = DedupeScanService(session).scan(
            DedupeScanOptions(
                tree_import_id=payload.tree_import_id,
                scope_path_prefix=payload.scope_path_prefix,
                included_extensions=payload.included_extensions,
                candidate_threshold=payload.candidate_threshold,
                high_confidence_threshold=payload.high_confidence_threshold,
                rules=DedupeRuleSet(
                    noise_words=payload.noise_words,
                    regex_patterns=payload.regex_patterns,
                ),
            )
        )
        cb("完成", summary.total_files, summary.total_files)
        return summary

    submit_job(job_id, work)
    return {"job_id": job_id, "status": "pending"}


@router.post("/confirm-jobs")
async def start_confirm_job(
    payload: DedupeConfirmJobRequest,
    db: Session = Depends(get_db),
    client: Real115Client = Depends(get_115_client),
) -> dict:
    try:
        job_id = create_job(db, "dedupe:confirm")
    except JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="已有去重确认任务在运行")

    def work(session, cb):
        cb("远端确认", 0, len(payload.candidate_ids))
        summary = DedupeConfirmationService(session, client).confirm_candidates(payload.candidate_ids)
        cb("完成", summary.requested, summary.requested)
        return summary

    submit_job(job_id, work)
    return {"job_id": job_id, "status": "pending"}


@router.post("/delete-plans")
def create_delete_plan(
    payload: DedupeDeletePlanCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        plan = DedupeDeletePlanService(db, client=None).create_plan(
            name=payload.name,
            candidate_ids=payload.candidate_ids,
            rate_limit_seconds=payload.rate_limit_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"plan_id": plan.id, "status": plan.status, "total_items": plan.total_items}


@router.get("/delete-plans", response_model=DedupeDeletePlanListResponse)
def list_delete_plans(db: Session = Depends(get_db)) -> DedupeDeletePlanListResponse:
    plans = list(db.scalars(select(DedupeDeletePlan).order_by(DedupeDeletePlan.id.desc())).all())
    return DedupeDeletePlanListResponse(
        items=[DedupeDeletePlanResponse.model_validate(plan) for plan in plans],
        total=len(plans),
    )


@router.get("/delete-plans/{plan_id}", response_model=DedupeDeletePlanDetailResponse)
def get_delete_plan(plan_id: int, db: Session = Depends(get_db)) -> DedupeDeletePlanDetailResponse:
    plan = db.get(DedupeDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Delete plan not found")
    items = list(
        db.scalars(
            select(DedupeDeletePlanItem)
            .where(DedupeDeletePlanItem.plan_id == plan_id)
            .order_by(DedupeDeletePlanItem.id.asc())
        ).all()
    )
    return DedupeDeletePlanDetailResponse(
        plan=DedupeDeletePlanResponse.model_validate(plan),
        items=[DedupeDeletePlanItemResponse.model_validate(item) for item in items],
    )


@router.post("/delete-plans/{plan_id}/execute-jobs")
async def start_delete_job(
    plan_id: int,
    payload: DedupeDeletePlanExecuteRequest,
    db: Session = Depends(get_db),
    client: Real115Client = Depends(get_115_client),
) -> dict:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    try:
        job_id = create_job(db, "dedupe:delete")
    except JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="已有去重删除任务在运行")

    def work(session, cb):
        cb("限流删除", 0, 0)
        summary = DedupeDeletePlanService(session, client).execute_plan(plan_id, confirm=True)
        cb("完成", summary.total, summary.total)
        return summary

    submit_job(job_id, work)
    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    return StreamingResponse(
        job_event_stream(job_id, transform=_public_state),
        media_type="text/event-stream",
    )


@router.get("/jobs/active", response_model=DedupeActiveJobsResponse)
async def active_jobs() -> DedupeActiveJobsResponse:
    return DedupeActiveJobsResponse(
        scan=_active_job("scan"),
        confirm=_active_job("confirm"),
        delete=_active_job("delete"),
    )


def _active_job(job_type: str) -> DedupeJobFrame | None:
    from app.db.session import SessionLocal
    with SessionLocal() as session:
        job = next(
            (item for item in BackgroundJobService.list_active(session)
             if item["job_type"] == f"dedupe:{job_type}"),
            None,
        )
    public = _public_state(job)
    return DedupeJobFrame.model_validate(public) if public else None


@router.get("/groups", response_model=DedupeGroupListResponse)
def list_groups(
    status: str | None = None,
    confidence_level: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> DedupeGroupListResponse:
    stmt = select(DedupeGroup)
    if status:
        stmt = stmt.where(DedupeGroup.status == status)
    if confidence_level:
        stmt = stmt.where(DedupeGroup.confidence_level == confidence_level)
    rows = list(db.scalars(stmt.order_by(DedupeGroup.id.desc())).all())
    offset = (page - 1) * page_size
    items = rows[offset : offset + page_size]
    return DedupeGroupListResponse(
        items=[DedupeGroupResponse.model_validate(row) for row in items],
        total=len(rows),
        page=page,
        page_size=page_size,
    )


@router.get("/groups/{group_id}", response_model=DedupeGroupDetailResponse)
def get_group(group_id: int, db: Session = Depends(get_db)) -> DedupeGroupDetailResponse:
    group = db.get(DedupeGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Dedupe group not found")
    candidates = list(
        db.scalars(
            select(DedupeCandidate)
            .where(DedupeCandidate.group_id == group_id)
            .order_by(DedupeCandidate.id.asc())
        ).all()
    )
    return DedupeGroupDetailResponse(
        group=DedupeGroupResponse.model_validate(group),
        candidates=[DedupeCandidateResponse.model_validate(row) for row in candidates],
    )


@router.post("/groups/{group_id}/review")
def review_group(group_id: int, payload: DedupeReviewRequest, db: Session = Depends(get_db)) -> dict:
    group = db.get(DedupeGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Dedupe group not found")

    keep_ids = set(payload.keep_candidate_ids)
    delete_ids = set(payload.delete_candidate_ids)
    if keep_ids & delete_ids:
        raise HTTPException(status_code=400, detail="候选项不能同时标记为保留和删除")

    candidates = list(db.scalars(select(DedupeCandidate).where(DedupeCandidate.group_id == group_id)).all())
    candidate_ids = {candidate.id for candidate in candidates}
    unknown_ids = (keep_ids | delete_ids) - candidate_ids
    if unknown_ids:
        raise HTTPException(status_code=400, detail="候选项不属于当前重复组")

    for candidate in candidates:
        if candidate.id in keep_ids:
            candidate.user_action = "keep"
        elif candidate.id in delete_ids:
            candidate.user_action = "delete"
        else:
            candidate.user_action = "undecided"

    group.status = "confirmed"
    group.review_note = payload.note
    db.commit()
    return {"group_id": group.id, "status": group.status}
