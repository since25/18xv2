from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.review_intake import ReviewIntakeItem
from app.schemas.review_intake import (
    ReviewIntakeApproveRequest,
    ReviewIntakeCreateRequest,
    ReviewIntakeDismissRequest,
    ReviewIntakeItemResponse,
    ReviewIntakeListResponse,
    ReviewIntakePathRequest,
    ReviewIntakeSummaryResponse,
)
from app.services.review_intake_service import ReviewIntakeService, parse_keyword_candidates

router = APIRouter(prefix="/review-intake", tags=["review-intake"])


def _to_response(item: ReviewIntakeItem) -> ReviewIntakeItemResponse:
    return ReviewIntakeItemResponse(
        id=item.id,
        bucket=item.bucket,  # type: ignore[arg-type]
        raw_path=item.raw_path,
        normalized_path=item.normalized_path,
        path_hash=item.path_hash,
        source=item.source,
        note=item.note,
        keyword_candidates=parse_keyword_candidates(item.extracted_keywords_json),
        status=item.status,
        approved_keyword_entry_id=item.approved_keyword_entry_id,
        approved_keyword=item.approved_keyword,
        reviewed_at=item.reviewed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _submit_with_bucket(
    *,
    bucket: str,
    payload: ReviewIntakePathRequest,
    db: Session,
) -> ReviewIntakeItemResponse:
    svc = ReviewIntakeService(db)
    try:
        item = svc.create_or_update(
            bucket=bucket,
            raw_path=payload.raw_path,
            source=payload.source,
            note=payload.note,
            pattern=payload.pattern,
            flags=payload.flags,
            group_index=payload.group_index,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(item)


@router.post("/items", response_model=ReviewIntakeItemResponse)
def create_item(
    payload: ReviewIntakeCreateRequest,
    db: Session = Depends(get_db),
) -> ReviewIntakeItemResponse:
    path_payload = ReviewIntakePathRequest(
        raw_path=payload.raw_path,
        source=payload.source,
        note=payload.note,
        pattern=payload.pattern,
        flags=payload.flags,
        group_index=payload.group_index,
        limit=payload.limit,
    )
    return _submit_with_bucket(bucket=payload.bucket, payload=path_payload, db=db)


@router.post("/whitelist", response_model=ReviewIntakeItemResponse)
def create_whitelist_item(
    payload: ReviewIntakePathRequest,
    db: Session = Depends(get_db),
) -> ReviewIntakeItemResponse:
    return _submit_with_bucket(bucket="whitelist", payload=payload, db=db)


@router.post("/blacklist", response_model=ReviewIntakeItemResponse)
def create_blacklist_item(
    payload: ReviewIntakePathRequest,
    db: Session = Depends(get_db),
) -> ReviewIntakeItemResponse:
    return _submit_with_bucket(bucket="blacklist", payload=payload, db=db)


@router.get("/items", response_model=ReviewIntakeListResponse)
def list_items(
    bucket: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ReviewIntakeListResponse:
    try:
        items, total = ReviewIntakeService(db).list_items(
            bucket=bucket,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReviewIntakeListResponse(
        items=[_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=ReviewIntakeSummaryResponse)
def get_summary(db: Session = Depends(get_db)) -> ReviewIntakeSummaryResponse:
    return ReviewIntakeSummaryResponse(**ReviewIntakeService(db).summary())


@router.post("/items/{item_id}/approve", response_model=ReviewIntakeItemResponse)
def approve_item(
    item_id: int,
    payload: ReviewIntakeApproveRequest,
    db: Session = Depends(get_db),
) -> ReviewIntakeItemResponse:
    try:
        item = ReviewIntakeService(db).approve(
            item_id=item_id,
            keyword=payload.keyword,
            note=payload.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(item)


@router.post("/items/{item_id}/dismiss", response_model=ReviewIntakeItemResponse)
def dismiss_item(
    item_id: int,
    payload: ReviewIntakeDismissRequest,
    db: Session = Depends(get_db),
) -> ReviewIntakeItemResponse:
    try:
        item = ReviewIntakeService(db).dismiss(item_id=item_id, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(item)


@router.post("/items/{item_id}/restore", response_model=ReviewIntakeItemResponse)
def restore_item(item_id: int, db: Session = Depends(get_db)) -> ReviewIntakeItemResponse:
    try:
        item = ReviewIntakeService(db).restore(item_id=item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(item)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    if not ReviewIntakeService(db).delete(item_id=item_id):
        raise HTTPException(status_code=404, detail="待审核项不存在")
    return {"ok": True}
