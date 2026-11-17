from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db, get_source_article_db
from app.models.tasks import MagnetDownloadTask
from app.schemas.magnet_tasks import (
    ArticleSearchRequest,
    ArticleSearchResponse,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    MagnetTaskBatchResponse,
    MagnetTaskBatchSummaryListResponse,
    MagnetTaskBatchSummaryResponse,
    MagnetTaskCreateRequest,
    MagnetTaskResponse,
)
from app.services.client_115.client import Real115Client
from app.services.magnet_download_service import MagnetDownloadService
from app.services.source_article_db import SourceArticleDatabaseService

router = APIRouter(prefix="/magnet-tasks", tags=["magnet-tasks"])


def _build_batch_summaries(rows: list[MagnetDownloadTask]) -> list[MagnetTaskBatchSummaryResponse]:
    grouped: OrderedDict[str, list[MagnetDownloadTask]] = OrderedDict()
    for row in rows:
        batch_key = row.batch_id or f"legacy-{row.id}"
        grouped.setdefault(batch_key, []).append(row)

    summaries: list[MagnetTaskBatchSummaryResponse] = []
    for batch_id, items in grouped.items():
        ordered_items = sorted(items, key=lambda item: item.id)
        created_times = [item.created_at for item in ordered_items if item.created_at is not None]
        summaries.append(
            MagnetTaskBatchSummaryResponse(
                batch_id=batch_id,
                created_at=min(created_times) if created_times else datetime.now(UTC),
                total_count=len(ordered_items),
                submitted_count=sum(1 for item in ordered_items if item.status == "submitted"),
                duplicate_skipped_count=sum(1 for item in ordered_items if item.status == "duplicate_skipped"),
                failed_count=sum(1 for item in ordered_items if item.status == "failed"),
                pending_count=sum(1 for item in ordered_items if item.status == "pending"),
                items=[MagnetTaskResponse.model_validate(item) for item in ordered_items],
            )
        )
    return summaries


@router.get("", response_model=list[MagnetTaskResponse])
def list_magnet_tasks(
    status: str | None = None,
    keyword_entry_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[MagnetTaskResponse]:
    stmt = select(MagnetDownloadTask).order_by(MagnetDownloadTask.id.desc())
    if status:
        stmt = stmt.where(MagnetDownloadTask.status == status)
    if keyword_entry_id is not None:
        stmt = stmt.where(MagnetDownloadTask.keyword_entry_id == keyword_entry_id)
    return [MagnetTaskResponse.model_validate(row) for row in db.scalars(stmt).all()]


@router.get("/batches", response_model=MagnetTaskBatchSummaryListResponse)
def list_magnet_task_batches(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> MagnetTaskBatchSummaryListResponse:
    rows = db.scalars(select(MagnetDownloadTask).order_by(MagnetDownloadTask.id.desc())).all()
    summaries = _build_batch_summaries(list(rows))
    limited = summaries[: max(1, min(limit, 100))]
    return MagnetTaskBatchSummaryListResponse(total=len(summaries), batches=limited)


@router.delete("/history")
def clear_magnet_task_history(db: Session = Depends(get_db)) -> dict[str, int]:
    rows = db.scalars(select(MagnetDownloadTask)).all()
    deleted_count = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return {"deleted_count": deleted_count}


@router.post("/search", response_model=ArticleSearchResponse)
def search_article_candidates(
    payload: ArticleSearchRequest,
    db: Session = Depends(get_db),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> ArticleSearchResponse:
    try:
        candidates = MagnetDownloadService(db, article_db=article_db).build_candidates(
            query=payload.query,
            keyword_entry_id=payload.keyword_entry_id,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ArticleSearchResponse(
        query=payload.query,
        keyword_entry_id=payload.keyword_entry_id,
        total_candidates=len(candidates),
        candidates=candidates,
    )


@router.post("/duplicate-check", response_model=DuplicateCheckResponse)
def duplicate_check(
    payload: DuplicateCheckRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> DuplicateCheckResponse:
    if payload.tree_import_id is None:
        raise HTTPException(status_code=400, detail="请先选择目录树批次后再执行重复检查。当前仅支持本地目录树匹配。")
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    return DuplicateCheckResponse(items=service.check_duplicates(payload.items, tree_import_id=payload.tree_import_id))


@router.post("/submit", response_model=MagnetTaskBatchResponse)
def submit_magnet_tasks(
    payload: MagnetTaskCreateRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> MagnetTaskBatchResponse:
    if payload.tree_import_id is None:
        raise HTTPException(status_code=400, detail="请先选择目录树批次后再提交磁力任务。当前仅允许基于本地目录树完成重复检查。")
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    tasks = service.create_and_submit_tasks(
        items=payload.items,
        target_cid=payload.target_cid,
        force_submit=payload.force_submit,
        tree_import_id=payload.tree_import_id,
    )
    return MagnetTaskBatchResponse(
        created_count=len(tasks),
        submitted_count=sum(1 for task in tasks if task.status == "submitted"),
        duplicate_skipped_count=sum(1 for task in tasks if task.status == "duplicate_skipped"),
        tasks=[MagnetTaskResponse.model_validate(task) for task in tasks],
    )
