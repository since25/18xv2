"""白名单批处理路由：扫描 / 提交 / 候选列表 / 丢弃 / 恢复 + SSE 进度。

复用 §async-import 的异步模式：asyncio.Lock + asyncio.to_thread + SSE。

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from pydantic import BaseModel

from app.api.deps import get_db
from app.services.background_job_service import BackgroundJobService
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

# 并发保护：scan 和 submit 各一把锁，互不阻塞但同类型同时只跑一个。
# 注意：locked() 检查 + create_task 之间不是真正原子的，单用户场景下可接受
# （事件循环单线程使并发 POST 极少），与 imports.py 同样取舍。
_scan_lock = asyncio.Lock()
_submit_lock = asyncio.Lock()
# job_id 用 uuid4 字符串，避免重启后 id 复用导致陈旧前端订阅冲突
_JOB_RETENTION_SECONDS = 600  # done 后 10 分钟内仍可被 SSE/active 查到
# 仅作为旧测试/旧进程兼容 fallback；正式状态以 background_jobs 表为准。
_jobs: dict[str, dict] = {}


def _new_job(job_type: str, db: Session) -> str:
    job_id = str(uuid.uuid4())
    state = BackgroundJobService.create(db, job_id, f"whitelist:{job_type}")
    _jobs[job_id] = state
    return job_id


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


# ── Scan job ────────────────────────────────────────────────────────────
@router.post("/scan-jobs")
async def start_scan_job(
    payload: ScanJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="已有扫描任务在运行，请等待完成")
    job_id = _new_job("scan", db)
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_scan_job(job_id: str, payload: ScanJobRequest) -> None:
    async with _scan_lock:
        await asyncio.to_thread(_blocking_scan, job_id, payload)


def _run_blocking_job(
    job_id: str,
    work: Callable[..., "BaseModel"],
) -> None:
    """通用 blocking job runner：管理 SessionLocal 生命周期 + progress cb + done/error 双路径。

    `work(session, cb) -> Pydantic Summary` 是真正干活的回调，由 scan/submit 各自传入。
    """
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        def cb(stage: str, current: int, total: int) -> None:
            BackgroundJobService.update(session, job_id, stage=stage, current=current, total=total)
            if job_id in _jobs:
                _jobs[job_id].update(stage=stage, current=current, total=total)

        summary = work(session, cb)
        BackgroundJobService.update(
            session, job_id, stage="完成", summary=summary.model_dump(), done=True,
            finished_at=datetime.now(UTC),
        )
        if job_id in _jobs:
            _jobs[job_id].update(stage="完成", summary=summary.model_dump(), done=True, finished_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        logger.exception("job %s 失败", job_id)
        BackgroundJobService.update(
            session, job_id, stage="失败", error=str(exc), done=True,
            finished_at=datetime.now(UTC),
        )
        if job_id in _jobs:
            _jobs[job_id].update(stage="失败", error=str(exc), done=True, finished_at=datetime.now(UTC).isoformat())
    finally:
        session.close()


def _make_magnet_svc(session: Session):
    """构造一个面向当前 session 的 MagnetDownloadService。"""
    from app.services.client_115.client import Real115Client
    from app.services.magnet_download_service import MagnetDownloadService
    from app.services.source_article_db import SourceArticleDatabaseService

    return MagnetDownloadService(
        session,
        article_db=SourceArticleDatabaseService(),
        client_115=Real115Client(),
    )


def _blocking_scan(job_id: str, payload: ScanJobRequest) -> None:
    def work(session, cb):
        svc = WhitelistCandidateService(session, magnet_svc=_make_magnet_svc(session))
        return svc.scan(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            progress_cb=cb,
        )
    _run_blocking_job(job_id, work)


# ── Submit job ──────────────────────────────────────────────────────────
@router.post("/submit-jobs")
async def start_submit_job(
    payload: SubmitJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _submit_lock.locked():
        raise HTTPException(status_code=409, detail="已有提交任务在运行，请等待完成")
    job_id = _new_job("submit", db)
    asyncio.create_task(_run_submit_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_submit_job(job_id: str, payload: SubmitJobRequest) -> None:
    async with _submit_lock:
        await asyncio.to_thread(_blocking_submit, job_id, payload)


def _blocking_submit(job_id: str, payload: SubmitJobRequest) -> None:
    def work(session, cb):
        svc = WhitelistCandidateService(session, magnet_svc=_make_magnet_svc(session))
        return svc.submit_selected(
            candidate_ids=payload.candidate_ids,
            force_submit=payload.force_submit,
            progress_cb=cb,
        )
    _run_blocking_job(job_id, work)


# ── SSE 进度 + active jobs ──────────────────────────────────────────────
@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    """SSE 推送：每秒一帧；done 后再推一帧后断开。

    不需要独立 keepalive — 每秒必发 data 已经穿透 nginx 等代理的 idle timeout。
    不在此处 pop _jobs[job_id]，避免多 tab 订阅时第一个 tab pop 导致第二个 tab 见 not found；
    清理由 _sweep_jobs 后台任务在 _JOB_RETENTION_SECONDS 后完成。
    """
    async def event_stream():
        """每秒 yield 一帧 data；done 后再推一帧后断开。

        不需要独立 keepalive — 每秒必发 data 已经穿透 nginx 等代理的 idle timeout。
        不在此处 pop _jobs[job_id]，避免多 tab 订阅时第一个 tab pop 导致第二个 tab 见 not found；
        清理由 _sweep_jobs 后台任务在 _JOB_RETENTION_SECONDS 后完成。
        """
        sent_done_once = False
        while True:
            from app.db.session import SessionLocal
            with SessionLocal() as state_session:
                state = BackgroundJobService.get(state_session, job_id)
            if state is None:
                state = _jobs.get(job_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(_public_state(state), ensure_ascii=False)}\n\n"
            if state["done"]:
                if sent_done_once:
                    break
                sent_done_once = True
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/jobs/active", response_model=ActiveJobsResponse)
async def active_jobs() -> ActiveJobsResponse:
    from app.db.session import SessionLocal
    with SessionLocal() as session:
        scan = next(
            (j for j in BackgroundJobService.list_active(session) if _job_type_matches(j, "scan")),
            None,
        )
        submit = next(
            (j for j in BackgroundJobService.list_active(session) if _job_type_matches(j, "submit")),
            None,
        )
    if scan is None:
        scan = next((j for j in _jobs.values() if _job_type_matches(j, "scan") and not j.get("done")), None)
    if submit is None:
        submit = next((j for j in _jobs.values() if _job_type_matches(j, "submit") and not j.get("done")), None)
    return ActiveJobsResponse(
        scan=JobFrame.model_validate(_public_state(scan)) if scan else None,
        submit=JobFrame.model_validate(_public_state(submit)) if submit else None,
    )


# ── Sweeper：后台清理已完成超过保留期的 job ─────────────────────────────
_SWEEP_INTERVAL_SECONDS = 60


async def _sweep_jobs() -> None:
    """每 _SWEEP_INTERVAL_SECONDS 扫描一次，回收已完成且超过 _JOB_RETENTION_SECONDS 的 job。"""
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            now = datetime.now(UTC)
            from app.db.session import SessionLocal
            with SessionLocal() as session:
                removed = BackgroundJobService.purge_expired(session, _JOB_RETENTION_SECONDS)
            if removed:
                logger.info("sweep: 回收 %d 条已完成 job", removed)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sweep cycle 失败")


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
