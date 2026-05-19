"""白名单批处理路由：扫描 / 提交 / 候选列表 / 丢弃 / 恢复 + SSE 进度。

复用 §async-import 的异步模式：asyncio.Lock + asyncio.to_thread + SSE。

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.whitelist import (
    ActiveJobsResponse,
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

# 并发保护：scan 和 submit 各一把锁，互不阻塞但同类型同时只跑一个
_scan_lock = asyncio.Lock()
_submit_lock = asyncio.Lock()
# job_id 用 uuid4 字符串，避免重启后 id 复用导致陈旧前端订阅冲突
_jobs: dict[str, dict] = {}
_JOB_RETENTION_SECONDS = 600  # done 后 10 分钟内仍可被 SSE/active 查到


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


# ── Scan job ────────────────────────────────────────────────────────────
@router.post("/scan-jobs")
async def start_scan_job(
    payload: ScanJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="已有扫描任务在运行，请等待完成")
    job_id = _new_job("scan")
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_scan_job(job_id: str, payload: ScanJobRequest) -> None:
    async with _scan_lock:
        await asyncio.to_thread(_blocking_scan, job_id, payload)


def _blocking_scan(job_id: str, payload: ScanJobRequest) -> None:
    from app.db.session import SessionLocal
    from app.services.client_115.client import Real115Client
    from app.services.magnet_download_service import MagnetDownloadService
    from app.services.source_article_db import SourceArticleDatabaseService

    session = SessionLocal()
    try:
        def cb(stage: str, current: int, total: int) -> None:
            _jobs[job_id].update(stage=stage, current=current, total=total)

        magnet_svc = MagnetDownloadService(
            session,
            article_db=SourceArticleDatabaseService(),
            client_115=Real115Client(),
        )
        svc = WhitelistCandidateService(session, magnet_svc=magnet_svc)
        summary = svc.scan(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            progress_cb=cb,
        )
        _jobs[job_id].update(stage="完成", summary=summary.model_dump(), done=True)
    except Exception as exc:
        logger.exception("scan job %s 失败", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()


# ── Submit job ──────────────────────────────────────────────────────────
@router.post("/submit-jobs")
async def start_submit_job(
    payload: SubmitJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _submit_lock.locked():
        raise HTTPException(status_code=409, detail="已有提交任务在运行，请等待完成")
    job_id = _new_job("submit")
    asyncio.create_task(_run_submit_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_submit_job(job_id: str, payload: SubmitJobRequest) -> None:
    async with _submit_lock:
        await asyncio.to_thread(_blocking_submit, job_id, payload)


def _blocking_submit(job_id: str, payload: SubmitJobRequest) -> None:
    from app.db.session import SessionLocal
    from app.services.client_115.client import Real115Client
    from app.services.magnet_download_service import MagnetDownloadService
    from app.services.source_article_db import SourceArticleDatabaseService

    session = SessionLocal()
    try:
        def cb(stage: str, current: int, total: int) -> None:
            _jobs[job_id].update(stage=stage, current=current, total=total)

        magnet_svc = MagnetDownloadService(
            session,
            article_db=SourceArticleDatabaseService(),
            client_115=Real115Client(),
        )
        svc = WhitelistCandidateService(session, magnet_svc=magnet_svc)
        summary = svc.submit_selected(
            candidate_ids=payload.candidate_ids,
            force_submit=payload.force_submit,
            progress_cb=cb,
        )
        _jobs[job_id].update(stage="完成", summary=summary.model_dump(), done=True)
    except Exception as exc:
        logger.exception("submit job %s 失败", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()


# ── SSE 进度 + active jobs ──────────────────────────────────────────────
@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    """SSE 推送：每秒一帧；空闲 20s 输出 keepalive；done 后再推一帧后断开。

    不在此处 pop job，避免多 tab 订阅同一 job 时 tab A 已 pop 导致 tab B 看到 not found。
    清理由 _sweep_jobs 后台任务在 _JOB_RETENTION_SECONDS 后完成。
    """
    async def event_stream():
        last_emit = asyncio.get_event_loop().time()
        sent_done_once = False
        while True:
            state = _jobs.get(job_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            last_emit = asyncio.get_event_loop().time()
            if state["done"]:
                if sent_done_once:
                    break
                sent_done_once = True
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(1)
            if asyncio.get_event_loop().time() - last_emit >= 20:
                yield ": keepalive\n\n"
                last_emit = asyncio.get_event_loop().time()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/jobs/active", response_model=ActiveJobsResponse)
async def active_jobs() -> ActiveJobsResponse:
    scan = next(
        (j for j in _jobs.values() if j["job_type"] == "scan" and not j["done"]),
        None,
    )
    submit = next(
        (j for j in _jobs.values() if j["job_type"] == "submit" and not j["done"]),
        None,
    )
    return ActiveJobsResponse(
        scan=JobFrame(**scan) if scan else None,
        submit=JobFrame(**submit) if submit else None,
    )


# ── Sweeper：后台清理已完成超过保留期的 job ─────────────────────────────
async def _sweep_jobs() -> None:
    """每 60s 扫描一次，回收已完成且超过 _JOB_RETENTION_SECONDS 的 job。"""
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(UTC)
            expired = []
            for jid, j in list(_jobs.items()):
                if j["done"] and j["finished_at"]:
                    finished = datetime.fromisoformat(j["finished_at"])
                    if (now - finished).total_seconds() > _JOB_RETENTION_SECONDS:
                        expired.append(jid)
            for jid in expired:
                _jobs.pop(jid, None)
                logger.info("sweep: 回收 job %s", jid)
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


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models.whitelist import WhitelistCandidate
    cand = db.get(WhitelistCandidate, candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.delete(cand)
    db.commit()
    return {"ok": True}
