"""白名单批处理路由：扫描 / 提交 / 候选列表 / 丢弃 / 恢复 + SSE 进度。

扫描和提交走统一后台任务启动器 app/services/job_runner.py：
库里同类型未完成任务判重 + 后台线程执行 + background_jobs 表记录进度 + SSE 推送。

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db
from app.services.background_job_service import BackgroundJobService
from app.services.client_115.client import Real115Client
from app.services.job_runner import JobAlreadyRunning, create_job, job_event_stream, submit_job
from app.schemas.whitelist import (
    ActiveJobsResponse,
    BulkDismissRequest,
    CandidateListResponse,
    CandidateResponse,
    DismissRequest,
    JobFrame,
    ScanJobRequest,
    SubmitJobRequest,
)
from app.services.whitelist.candidate_service import WhitelistCandidateService

router = APIRouter(prefix="/whitelist-batch", tags=["whitelist-batch"])
logger = logging.getLogger(__name__)

# job_id 用 uuid4 字符串（由启动器生成），避免重启后 id 复用导致陈旧前端订阅冲突。
# 任务状态只认 background_jobs 表；库里任务类型带 whitelist: 前缀，对外展示时去掉。


def _public_state(state: dict | None) -> dict | None:
    if state is None:
        return None
    result = dict(state)
    # 兼容旧测试/旧内存快照，它们使用未加命名空间的 job_type。
    if result["job_type"] in {"scan", "submit"}:
        return result
    if result["job_type"].startswith("whitelist:"):
        result["job_type"] = result["job_type"].split(":", 1)[1]
    return result


def _job_type_matches(state: dict, job_type: str) -> bool:
    return state["job_type"] in {job_type, f"whitelist:{job_type}"}


def _make_magnet_svc(session: Session, client: Real115Client):
    """构造一个面向当前 session 的 MagnetDownloadService，使用传入的全局 115 客户端。"""
    from app.services.magnet_download_service import MagnetDownloadService
    from app.services.source_article_db import SourceArticleDatabaseService

    return MagnetDownloadService(
        session,
        article_db=SourceArticleDatabaseService(),
        client_115=client,
    )


# ── Scan job ────────────────────────────────────────────────────────────
@router.post("/scan-jobs")
async def start_scan_job(
    payload: ScanJobRequest,
    db: Session = Depends(get_db),
    client: Real115Client = Depends(get_115_client),
) -> dict:
    try:
        job_id = create_job(db, "whitelist:scan")
    except JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="已有扫描任务在运行，请等待完成")

    def work(session, cb):
        svc = WhitelistCandidateService(session, magnet_svc=_make_magnet_svc(session, client))
        return svc.scan(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            progress_cb=cb,
        )

    submit_job(job_id, work)
    return {"job_id": job_id, "status": "pending"}


# ── Submit job ──────────────────────────────────────────────────────────
@router.post("/submit-jobs")
async def start_submit_job(
    payload: SubmitJobRequest,
    db: Session = Depends(get_db),
    client: Real115Client = Depends(get_115_client),
) -> dict:
    try:
        job_id = create_job(db, "whitelist:submit")
    except JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="已有提交任务在运行，请等待完成")

    def work(session, cb):
        svc = WhitelistCandidateService(session, magnet_svc=_make_magnet_svc(session, client))
        return svc.submit_selected(
            candidate_ids=payload.candidate_ids,
            force_submit=payload.force_submit,
            progress_cb=cb,
        )

    submit_job(job_id, work)
    return {"job_id": job_id, "status": "pending"}


# ── SSE 进度 + active jobs ──────────────────────────────────────────────
@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    """SSE 推送：每秒一帧；done 后再推一帧后断开。

    多 tab 订阅互不影响；记录由统一清理循环在保留期后删除。
    """
    return StreamingResponse(
        job_event_stream(job_id, transform=_public_state),
        media_type="text/event-stream",
    )


@router.get("/jobs/active", response_model=ActiveJobsResponse)
async def active_jobs() -> ActiveJobsResponse:
    from app.db.session import SessionLocal
    with SessionLocal() as session:
        active = BackgroundJobService.list_active(session)
    scan = next((j for j in active if _job_type_matches(j, "scan")), None)
    submit = next((j for j in active if _job_type_matches(j, "submit")), None)
    return ActiveJobsResponse(
        scan=JobFrame.model_validate(_public_state(scan)) if scan else None,
        submit=JobFrame.model_validate(_public_state(submit)) if submit else None,
    )


# ── Candidates CRUD ─────────────────────────────────────────────────────
@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates(
    lifecycle_status: str | None = Query(default=None),
    matched_keyword_entry_id: int | None = Query(default=None),
    duplicate_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CandidateListResponse:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    items, total = svc.list_candidates(
        lifecycle_status=lifecycle_status,
        matched_keyword_entry_id=matched_keyword_entry_id,
        duplicate_status=duplicate_status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return CandidateListResponse(
        items=[CandidateResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(
    candidate_id: int,
    payload: DismissRequest,
    db: Session = Depends(get_db),
) -> dict:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    try:
        cand = svc.dismiss(candidate_id=candidate_id, reason=payload.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Candidate not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"candidate_id": cand.id, "lifecycle_status": cand.lifecycle_status}


@router.post("/candidates/{candidate_id}/restore")
def restore_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
) -> dict:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    try:
        cand = svc.restore(candidate_id=candidate_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Candidate not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"candidate_id": cand.id, "lifecycle_status": cand.lifecycle_status}


@router.post("/candidates/bulk-dismiss")
def bulk_dismiss_candidates(
    payload: BulkDismissRequest,
    db: Session = Depends(get_db),
) -> dict:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    try:
        result = svc.bulk_dismiss(candidate_ids=payload.candidate_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models.whitelist import WhitelistCandidate
    cand = db.get(WhitelistCandidate, candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.delete(cand)
    db.commit()
    return {"ok": True}
