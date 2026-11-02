from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.background_jobs import BackgroundJob
from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem
from app.schemas.jellyfin import (
    JellyfinConflictResponse,
    JellyfinJobResponse,
    JellyfinStatusResponse,
    JellyfinUnmatchedResponse,
)
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin.job_runner import (
    JOB_SCAN,
    JOB_SYNC,
    JobAlreadyRunning,
    jellyfin_scan_enabled,
    jellyfin_sync_enabled,
    run_scan_job,
    run_sync_job,
    start_job,
)


router = APIRouter(prefix="/jellyfin", tags=["jellyfin"])


def _latest_job(db: Session, job_type: str) -> dict | None:
    row = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.job_type == job_type)
        .order_by(BackgroundJob.started_at.desc())
        .limit(1)
    )
    return BackgroundJobService.to_dict(row) if row is not None else None


@router.get("/status", response_model=JellyfinStatusResponse)
def jellyfin_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    active_items = JellyfinMediaItem.active.is_(True)
    counts = {
        "active_items": int(db.scalar(select(func.count()).select_from(JellyfinMediaItem).where(active_items)) or 0),
        "matched": int(
            db.scalar(
                select(func.count())
                .select_from(JellyfinMediaItem)
                .where(active_items, JellyfinMediaItem.match_state == "matched")
            )
            or 0
        ),
        "unmatched": int(
            db.scalar(
                select(func.count())
                .select_from(JellyfinMediaItem)
                .where(active_items, JellyfinMediaItem.match_state == "unmatched")
            )
            or 0
        ),
        "nfo_error": int(
            db.scalar(
                select(func.count())
                .select_from(JellyfinMediaItem)
                .where(active_items, JellyfinMediaItem.match_state == "nfo_error")
            )
            or 0
        ),
        "pending_resolve": int(
            db.scalar(
                select(func.count())
                .select_from(JellyfinMediaItem)
                .where(active_items, JellyfinMediaItem.resolve_state == "pending")
            )
            or 0
        ),
    }
    collections = {
        value: int(
            db.scalar(
                select(func.count())
                .select_from(JellyfinKeywordCollection)
                .where(JellyfinKeywordCollection.status == value)
            )
            or 0
        )
        for value in ("active", "conflict", "retired")
    }
    return {
        "scan_enabled": jellyfin_scan_enabled(settings),
        "sync_enabled": jellyfin_sync_enabled(settings),
        "local_roots": list(getattr(settings, "media_library_local_roots", []) or []),
        "strm_roots": list(getattr(settings, "media_library_strm_roots", []) or []),
        "latest_scan": _latest_job(db, JOB_SCAN),
        "latest_sync": _latest_job(db, JOB_SYNC),
        "counts": counts,
        "collections": collections,
    }


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def trigger_scan(background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    if not jellyfin_scan_enabled(settings):
        raise HTTPException(status_code=409, detail="Jellyfin 扫描未启用")
    try:
        job_id = start_job(db, JOB_SCAN)
    except JobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail="Jellyfin 扫描任务正在运行") from exc
    background_tasks.add_task(run_scan_job, job_id)
    return {"job_id": job_id}


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    if not jellyfin_sync_enabled(settings):
        raise HTTPException(status_code=409, detail="Jellyfin 同步未启用或缺少地址/API Key")
    try:
        job_id = start_job(db, JOB_SYNC)
    except JobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail="Jellyfin 同步任务正在运行") from exc
    background_tasks.add_task(run_sync_job, job_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JellyfinJobResponse)
def get_jellyfin_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    result = BackgroundJobService.get(db, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Jellyfin 任务不存在")
    return result


@router.get("/unmatched", response_model=JellyfinUnmatchedResponse)
def list_unmatched(
    source: Literal["local", "strm_115"] | None = Query(default=None),
    state: Literal["unmatched", "nfo_error"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    conditions = [
        JellyfinMediaItem.active.is_(True),
        JellyfinMediaItem.match_state.in_(["unmatched", "nfo_error"]),
    ]
    if source is not None:
        conditions.append(JellyfinMediaItem.source == source)
    if state is not None:
        conditions.append(JellyfinMediaItem.match_state == state)
    total = int(db.scalar(select(func.count()).select_from(JellyfinMediaItem).where(*conditions)) or 0)
    rows = db.scalars(
        select(JellyfinMediaItem)
        .where(*conditions)
        .order_by(JellyfinMediaItem.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "source": row.source,
                "path": row.path,
                "match_state": row.match_state,
                "match_note": row.match_note,
            }
            for row in rows
        ],
    }


@router.get("/conflicts", response_model=JellyfinConflictResponse)
def list_conflicts(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(JellyfinKeywordCollection)
        .where(
            or_(
                JellyfinKeywordCollection.status == "conflict",
                (
                    JellyfinKeywordCollection.last_error.is_not(None)
                    & (JellyfinKeywordCollection.last_error != "")
                ),
            )
        )
        .order_by(JellyfinKeywordCollection.id.asc())
    ).all()
    return {
        "items": [
            {
                "keyword_entry_id": row.keyword_entry_id,
                "canonical_name_snapshot": row.canonical_name_snapshot,
                "status": row.status,
                "last_error": row.last_error,
            }
            for row in rows
        ]
    }
