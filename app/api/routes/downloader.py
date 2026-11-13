from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.downloader import DownloaderSyncRun
from app.schemas.downloader import (
    DownloaderCandidateListResponse,
    DownloaderControlRequest,
    DownloaderIgnoreRequest,
    DownloaderInboxResponse,
    DownloaderKeywordQuickAddRequest,
    DownloaderRetryRequest,
    DownloaderSelectRequest,
    DownloaderPackageSubmitRequest,
    DownloaderSubmitRequest,
    DownloaderTaskListResponse,
    DownloaderUnignoreRequest,
)
from app.services.downloader.client import DownloaderClient, DownloaderRemoteError
from app.services.downloader.keyword_quick_add import KeywordQuickAddError, quick_add_keyword
from app.services.downloader.query_service import DownloaderQueryService
from app.services.downloader.sync_service import DownloaderSyncService

router = APIRouter(prefix="/downloader", tags=["downloader"])


def _client() -> DownloaderClient:
    settings = get_settings()
    if not settings.downloader_enabled or not settings.downloader_base_url:
        raise HTTPException(status_code=503, detail="RN 下载器集成未启用或地址未配置")
    return DownloaderClient(settings)


def _remote_error(error: DownloaderRemoteError) -> HTTPException:
    return HTTPException(status_code=502, detail={"error_code": error.code, "message": str(error)})


@router.get("/status")
def downloader_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    latest = db.scalar(select(DownloaderSyncRun).order_by(DownloaderSyncRun.id.desc()))
    payload = {
        "enabled": bool(settings.downloader_enabled and settings.downloader_base_url),
        "node_key": settings.downloader_node_key,
        "base_url_configured": bool(settings.downloader_base_url),
        "latest_sync": {
            "kind": latest.kind,
            "status": latest.status,
            "packages_seen": latest.packages_seen,
            "candidates_created": latest.candidates_created,
            "tasks_seen": latest.tasks_seen,
            "error_message": latest.error_message,
            "started_at": latest.started_at.isoformat() if latest.started_at else None,
            "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
        }
        if latest
        else None,
    }
    if not payload["enabled"]:
        payload.update({"remote_ready": False, "remote": None})
        return payload
    try:
        payload.update({"remote_ready": True, "remote": _client().health()})
    except DownloaderRemoteError as error:
        payload.update({"remote_ready": False, "remote": {"error_code": error.code, "message": str(error)}})
    return payload


@router.post("/sync")
def sync_downloader(db: Session = Depends(get_db)) -> dict:
    try:
        with _client() as client:
            packages = DownloaderSyncService.sync_packages(db, client, node_key=get_settings().downloader_node_key)
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error
    return {
        "packages_seen": packages.packages_seen,
        "packages_updated": packages.packages_updated,
        "candidates_created": packages.candidates_created,
        "candidates_dismissed": packages.candidates_dismissed,
    }


@router.get("/packages", response_model=None)
def list_downloader_candidates(
    view: Literal["candidates", "ignored", "unmatched"] | None = Query(default=None),
    download_status: str | None = Query(default=None),
    candidate_status: str | None = Query(default="pending"),
    keyword_entry_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    channel_title: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> DownloaderCandidateListResponse:
    if view is not None:
        items, total, counts = DownloaderQueryService.list_inbox(
            db,
            view=view,
            download_status=download_status,
            keyword_entry_id=keyword_entry_id,
            search=search,
            channel_title=channel_title,
            page=page,
            page_size=page_size,
        )
        return DownloaderInboxResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            counts=counts,
        )
    items, total = DownloaderSyncService.list_candidates(
        db,
        candidate_status=candidate_status,
        keyword_entry_id=keyword_entry_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return DownloaderCandidateListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/packages/ignore")
def ignore_downloader_packages(payload: DownloaderIgnoreRequest, db: Session = Depends(get_db)) -> dict:
    if payload.channel_title:
        package_ids = DownloaderQueryService.ignore_channel(db, payload.channel_title, reason=payload.reason)
        return {"ignored": len(package_ids), "package_ids": package_ids}
    if not payload.candidate_ids and not payload.package_ids:
        raise HTTPException(status_code=422, detail="candidate_ids、package_ids 或 channel_title 至少提供一个")
    return {
        "ignored": DownloaderQueryService.ignore_packages(
            db,
            candidate_ids=payload.candidate_ids,
            package_ids=payload.package_ids,
            reason=payload.reason,
        )
    }


@router.post("/packages/unignore")
def unignore_downloader_packages(
    payload: DownloaderUnignoreRequest,
    db: Session = Depends(get_db),
) -> dict:
    return {"restored": DownloaderQueryService.unignore_packages(db, payload.package_ids)}


@router.post("/keyword-quick-add")
def keyword_quick_add(payload: DownloaderKeywordQuickAddRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return quick_add_keyword(
            db, keyword=payload.keyword, list_type=payload.list_type, dry_run=payload.dry_run
        )
    except KeywordQuickAddError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.post("/packages/{candidate_id}/select")
def select_downloader_candidate(
    candidate_id: int,
    payload: DownloaderSelectRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        candidate = DownloaderSyncService.select_candidate(db, candidate_id, payload.selected)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"candidate_id": candidate.id, "status": candidate.status}


@router.post("/download-batches")
def submit_downloader_batches(
    payload: DownloaderSubmitRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = DownloaderSyncService.submit_selected(
            db,
            _client(),
            payload.candidate_ids,
            node_key=get_settings().downloader_node_key,
        )
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"submitted": result.submitted, "skipped": result.skipped, "failed": result.failed, "items": result.items}


@router.post("/packages/download")
def submit_downloader_packages(
    payload: DownloaderPackageSubmitRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = DownloaderSyncService.submit_packages(
            db,
            _client(),
            payload.package_ids,
            node_key=get_settings().downloader_node_key,
        )
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"submitted": result.submitted, "skipped": result.skipped, "failed": result.failed, "items": result.items}


@router.get("/tasks", response_model=DownloaderTaskListResponse)
def list_downloader_tasks(
    limit: int | None = Query(default=None, ge=1, le=500),
    status: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    channel: str | None = Query(default=None),
    keyword_entry_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    db: Session = Depends(get_db),
) -> DownloaderTaskListResponse:
    if (
        not any(value is not None for value in (status, since, until, channel, keyword_entry_id, search))
        and page is None
        and page_size is None
        and limit is not None
    ):
        items, total = DownloaderSyncService.list_tasks(db, node_key=get_settings().downloader_node_key, limit=limit)
        return DownloaderTaskListResponse(items=items, total=total)
    items, total = DownloaderQueryService.list_tasks(
        db,
        node_key=get_settings().downloader_node_key,
        status=[value for value in (status or "").split(",") if value],
        since=since,
        until=until,
        channel=channel,
        keyword_entry_id=keyword_entry_id,
        search=search,
        page=page or 1,
        page_size=page_size or 20,
    )
    return DownloaderTaskListResponse(items=items, total=total)


@router.get("/tasks/{task_id}/detail")
def downloader_task_detail(task_id: str, db: Session = Depends(get_db)) -> dict:
    detail = DownloaderQueryService.task_detail(db, task_id, node_key=get_settings().downloader_node_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return detail


@router.get("/tasks/{task_id}/history")
def list_downloader_task_history(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "task_id": task_id,
        "items": DownloaderSyncService.list_task_history(
            db,
            task_id,
            node_key=get_settings().downloader_node_key,
            limit=limit,
        ),
    }


@router.post("/tasks/sync")
def sync_downloader_tasks(db: Session = Depends(get_db)) -> dict:
    try:
        with _client() as client:
            result = DownloaderSyncService.sync_tasks(db, client, node_key=get_settings().downloader_node_key)
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error
    return {"tasks_seen": result.tasks_seen, "tasks_updated": result.tasks_updated}


@router.post("/control")
def control_downloader(payload: DownloaderControlRequest) -> dict:
    try:
        return _client().set_download_state(payload.state)
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error


@router.post("/tasks/{task_id}/cancel")
def cancel_downloader_task(task_id: str) -> dict:
    try:
        return _client().cancel_task(task_id)
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error


@router.post("/tasks/{task_id}/retry")
def retry_downloader_task(task_id: str, payload: DownloaderRetryRequest | None = None) -> dict:
    try:
        return _client().retry_task(task_id)
    except DownloaderRemoteError as error:
        raise _remote_error(error) from error


@router.get("/summary")
def downloader_summary(db: Session = Depends(get_db)) -> dict:
    return DownloaderQueryService.summary(
        db,
        node_key=get_settings().downloader_node_key,
        now=datetime.now(UTC),
    )


@router.get("/channels")
def downloader_channels(db: Session = Depends(get_db)) -> dict:
    return {"items": DownloaderQueryService.list_channels(db)}
