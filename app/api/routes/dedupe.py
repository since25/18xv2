from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.dedupe import DedupeCandidate, DedupeGroup
from app.schemas.dedupe import (
    DedupeActiveJobsResponse,
    DedupeCandidateResponse,
    DedupeGroupDetailResponse,
    DedupeGroupListResponse,
    DedupeGroupResponse,
    DedupeJobFrame,
    DedupeReviewRequest,
    DedupeScanJobRequest,
)
from app.services.dedupe.normalization import DedupeRuleSet
from app.services.dedupe.scan_service import DedupeScanOptions, DedupeScanService

router = APIRouter(prefix="/dedupe", tags=["dedupe"])
logger = logging.getLogger(__name__)

_scan_lock = asyncio.Lock()
_jobs: dict[str, dict] = {}
_JOB_RETENTION_SECONDS = 600
_SWEEP_INTERVAL_SECONDS = 60


def _new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "job_type": job_type,
        "stage": "等待开始",
        "current": 0,
        "total": 0,
        "done": False,
        "error": None,
        "summary": None,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
    }
    return job_id


@router.post("/scan-jobs")
async def start_scan_job(payload: DedupeScanJobRequest) -> dict:
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="已有去重扫描任务在运行")
    job_id = _new_job("scan")
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_scan_job(job_id: str, payload: DedupeScanJobRequest) -> None:
    async with _scan_lock:
        await asyncio.to_thread(_blocking_scan, job_id, payload)


def _blocking_scan(job_id: str, payload: DedupeScanJobRequest) -> None:
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        _jobs[job_id].update(stage="本地文件名扫描", current=0, total=0)
        service = DedupeScanService(session)
        summary = service.scan(
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
        _jobs[job_id].update(
            stage="完成",
            current=summary.total_files,
            total=summary.total_files,
            done=True,
            summary=asdict(summary),
        )
    except Exception as exc:
        logger.exception("dedupe scan job %s failed", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()


@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    async def event_stream():
        sent_done_once = False
        while True:
            state = _jobs.get(job_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
            if state["done"]:
                if sent_done_once:
                    break
                sent_done_once = True
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/jobs/active", response_model=DedupeActiveJobsResponse)
async def active_jobs() -> DedupeActiveJobsResponse:
    return DedupeActiveJobsResponse(
        scan=_active_job("scan"),
        confirm=_active_job("confirm"),
        delete=_active_job("delete"),
    )


def _active_job(job_type: str) -> DedupeJobFrame | None:
    job = next((item for item in _jobs.values() if item["job_type"] == job_type and not item["done"]), None)
    return DedupeJobFrame.model_validate(job) if job else None


async def _sweep_jobs() -> None:
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            now = datetime.now(UTC)
            expired: list[str] = []
            for job_id, job in list(_jobs.items()):
                if job["done"] and job["finished_at"]:
                    finished = datetime.fromisoformat(job["finished_at"])
                    if (now - finished).total_seconds() > _JOB_RETENTION_SECONDS:
                        expired.append(job_id)
            for job_id in expired:
                _jobs.pop(job_id, None)
                logger.info("dedupe sweep: removed job %s", job_id)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("dedupe sweep cycle failed")


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
