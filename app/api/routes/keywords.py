from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.keywords import KeywordEntry, KeywordLibraryEntry
from app.schemas.keywords import (
    KeywordAliasAddRequest,
    KeywordDuplicateScanRequest,
    KeywordDuplicateScanResponse,
    KeywordDuplicatePairResponse,
    KeywordEntryBatchImportRequest,
    KeywordEntryBatchImportResponse,
    KeywordEntryCreateRequest,
    KeywordEntryListResponse,
    KeywordEntryMergeRequest,
    KeywordEntryResponse,
    KeywordEntryUpdateRequest,
    KeywordHitResponse,
    KeywordHitRebuildRequest,
    KeywordHitRebuildResponse,
    KeywordLibraryBatchCreateRequest,
    KeywordLibraryBatchCreateResponse,
    KeywordLibraryEntryResponse,
    KeywordOperationLogResponse,
    KeywordTreeHitSummaryListResponse,
    KeywordTreeHitSummaryResponse,
    SimilarKeywordPreviewRequest,
    SimilarKeywordPreviewResponse,
    SimilarKeywordSuggestionResponse,
)
from app.services.keywords.hit_rebuild_service import KeywordHitRebuildService
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

router = APIRouter(tags=["keywords"])


def _to_entry_response(entry: KeywordEntry) -> KeywordEntryResponse:
    return KeywordEntryResponse.model_validate(entry)


@router.get("/keywords", response_model=KeywordEntryListResponse)
def list_keywords(
    keyword_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> KeywordEntryListResponse:
    service = KeywordRegistryService(db)
    entries, total_count = service.list_entries(keyword_type=keyword_type, status=status, query=query, skip=skip, limit=limit)
    return KeywordEntryListResponse(total=total_count, entries=[_to_entry_response(item) for item in entries])


@router.post("/keywords", response_model=KeywordEntryResponse)
def create_keyword(payload: KeywordEntryCreateRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    entry = service.create_entry(
        canonical_name=payload.canonical_name,
        keyword_type=payload.keyword_type,
        merge_policy=payload.merge_policy,
        note=payload.note,
        aliases=payload.aliases,
        source="manual",
    )
    service.sync_legacy_library()
    return _to_entry_response(entry)


@router.patch("/keywords/{entry_id}", response_model=KeywordEntryResponse)
def update_keyword(entry_id: int, payload: KeywordEntryUpdateRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    try:
        entry = service.update_entry(
            entry_id,
            canonical_name=payload.canonical_name,
            keyword_type=payload.keyword_type,
            merge_policy=payload.merge_policy,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service.sync_legacy_library()
    return _to_entry_response(entry)


@router.post("/keywords/import", response_model=KeywordEntryBatchImportResponse)
def batch_import_keywords(payload: KeywordEntryBatchImportRequest, db: Session = Depends(get_db)) -> KeywordEntryBatchImportResponse:
    service = KeywordRegistryService(db)
    existing_before = {normalize_keyword_text(item): service.find_entry_by_keyword(item) for item in payload.keywords}
    entries = service.record_hits(
        keywords=payload.keywords,
        import_id=payload.import_id,
        examples_by_keyword=payload.examples_by_keyword,
        source_folder_name_by_keyword=payload.source_folder_name_by_keyword,
        match_rule=payload.pattern,
        match_source=payload.source,
        keyword_type=payload.keyword_type,
        merge_policy=payload.merge_policy,
    )
    service.sync_legacy_library()
    existing_count = sum(1 for item in existing_before.values() if item is not None)
    unique_entries: dict[int, KeywordEntry] = {entry.id: entry for entry in entries}
    return KeywordEntryBatchImportResponse(
        created_count=max(0, len(unique_entries) - existing_count),
        existing_count=existing_count,
        entries=[_to_entry_response(item) for item in unique_entries.values()],
    )


@router.post("/keywords/{entry_id}/aliases", response_model=KeywordEntryResponse)
def add_keyword_aliases(entry_id: int, payload: KeywordAliasAddRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    try:
        service.add_aliases(entry_id, payload.aliases, source=payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service.sync_legacy_library()
    entry = db.scalar(select(KeywordEntry).where(KeywordEntry.id == entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Keyword entry not found")
    return _to_entry_response(entry)


@router.post("/keywords/merge", response_model=KeywordEntryResponse)
def merge_keywords(payload: KeywordEntryMergeRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    try:
        entry = KeywordRegistryService(db).merge_entries(
            canonical_entry_id=payload.canonical_entry_id,
            merge_entry_ids=payload.merge_entry_ids,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    KeywordRegistryService(db).sync_legacy_library()
    return _to_entry_response(entry)


@router.get("/keywords/hits", response_model=list[KeywordHitResponse])
def list_keyword_hits(
    import_id: int | None = None,
    keyword_entry_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[KeywordHitResponse]:
    hits = KeywordRegistryService(db).list_hits(import_id=import_id, keyword_entry_id=keyword_entry_id, limit=limit)
    return [KeywordHitResponse.model_validate(item) for item in hits]


@router.post("/keywords/hits/rebuild", response_model=KeywordHitRebuildResponse)
def rebuild_keyword_hits(payload: KeywordHitRebuildRequest, db: Session = Depends(get_db)) -> KeywordHitRebuildResponse:
    try:
        result = KeywordHitRebuildService(db).rebuild_import_hits(
            import_id=payload.import_id,
            include_files=payload.include_files,
            include_folders=payload.include_folders,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KeywordHitRebuildResponse(
        import_id=result.import_id,
        deleted_count=result.deleted_count,
        created_count=result.created_count,
        scanned_folder_count=result.scanned_folder_count,
        scanned_file_count=result.scanned_file_count,
        matched_keyword_count=result.matched_keyword_count,
    )


@router.get("/keywords/tree-hit-summary", response_model=KeywordTreeHitSummaryListResponse)
def list_keyword_tree_hit_summary(
    import_id: int | None = None,
    tree_path: str | None = None,
    keyword_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> KeywordTreeHitSummaryListResponse:
    items = KeywordRegistryService(db).summarize_tree_hits(
        import_id=import_id,
        tree_path=tree_path,
        keyword_type=keyword_type,
        status=status,
        query=query,
        limit=limit,
    )
    return KeywordTreeHitSummaryListResponse(
        total=len(items),
        items=[KeywordTreeHitSummaryResponse.model_validate(item) for item in items],
    )


@router.get("/keywords/operation-logs", response_model=list[KeywordOperationLogResponse])
def list_keyword_operation_logs(
    keyword_entry_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[KeywordOperationLogResponse]:
    logs = KeywordRegistryService(db).list_operation_logs(keyword_entry_id=keyword_entry_id, limit=limit)
    return [KeywordOperationLogResponse.model_validate(item) for item in logs]


@router.post("/keywords/similar-preview", response_model=SimilarKeywordPreviewResponse)
def preview_similar_keywords(payload: SimilarKeywordPreviewRequest, db: Session = Depends(get_db)) -> SimilarKeywordPreviewResponse:
    suggestions = KeywordRegistryService(db).suggest_similar(payload.keywords, threshold=payload.threshold, limit=payload.limit)
    return SimilarKeywordPreviewResponse(
        total=len(suggestions),
        suggestions=[SimilarKeywordSuggestionResponse.model_validate(item) for item in suggestions],
    )


@router.delete("/keywords/{entry_id}")
def delete_keyword(entry_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    service = KeywordRegistryService(db)
    deleted = service.delete_entry(entry_id)
    service.sync_legacy_library()
    return {"deleted": deleted}


legacy_router = APIRouter(prefix="/keyword-library", tags=["keyword-library"])


@legacy_router.get("", response_model=list[KeywordLibraryEntryResponse])
def list_keyword_library(
    list_type: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> list[KeywordLibraryEntryResponse]:
    query_stmt = select(KeywordLibraryEntry).order_by(KeywordLibraryEntry.id.desc())
    if list_type:
        query_stmt = query_stmt.where(KeywordLibraryEntry.list_type == list_type)
    if keyword:
        normalized = normalize_keyword_text(keyword)
        query_stmt = query_stmt.where(KeywordLibraryEntry.keyword_normalized.contains(normalized))
    rows = list(db.scalars(query_stmt).all())
    return [KeywordLibraryEntryResponse.model_validate(row) for row in rows]


@legacy_router.post("", response_model=KeywordLibraryBatchCreateResponse)
def create_keyword_library_entries(
    payload: KeywordLibraryBatchCreateRequest,
    db: Session = Depends(get_db),
) -> KeywordLibraryBatchCreateResponse:
    service = KeywordRegistryService(db)
    created = []
    seen: set[str] = set()
    skipped_count = 0
    for keyword in payload.keywords:
        normalized = normalize_keyword_text(keyword)
        if len(normalized) < 2:
            skipped_count += 1
            continue
        if normalized in seen:
            skipped_count += 1
            continue
        seen.add(normalized)
        existed_before = service.find_entry_by_keyword(normalized) is not None
        entry = service.create_entry(
            canonical_name=keyword,
            keyword_type=payload.list_type,
            merge_policy="normal",
            note=payload.note,
            aliases=[],
            source=payload.source,
        )
        created.append(entry)
        if existed_before:
            skipped_count += 1
    service.sync_legacy_library()
    rows = list(
        db.scalars(
            select(KeywordLibraryEntry)
            .where(KeywordLibraryEntry.list_type == payload.list_type)
            .where(KeywordLibraryEntry.keyword_normalized.in_(list(seen)))
        ).all()
    )
    return KeywordLibraryBatchCreateResponse(
        created_count=len(rows),
        skipped_count=skipped_count,
        entries=[KeywordLibraryEntryResponse.model_validate(item) for item in rows],
    )


@legacy_router.delete("/{entry_id}")
def delete_keyword_library_entry(entry_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    entry = db.get(KeywordLibraryEntry, entry_id)
    if entry is None:
        return {"deleted": False}
    keyword_entry = KeywordRegistryService(db).find_entry_by_keyword(entry.keyword_normalized)
    db.delete(entry)
    if keyword_entry is not None:
        db.delete(keyword_entry)
    db.commit()
    return {"deleted": True}


@router.post("/keywords/duplicates/scan", response_model=KeywordDuplicateScanResponse)
def scan_duplicate_keywords(payload: KeywordDuplicateScanRequest, db: Session = Depends(get_db)) -> KeywordDuplicateScanResponse:
    service = KeywordRegistryService(db)
    pairs = service.scan_duplicate_keywords(
        keyword_type=payload.keyword_type,
        status=payload.status,
        threshold=payload.threshold,
    )
    reference_counts = service.count_whitelist_candidate_references(
        [entry.id for pair in pairs for entry in pair[:2]]
    )
    return KeywordDuplicateScanResponse(
        pairs=[
            KeywordDuplicatePairResponse(
                keyword_1=_to_entry_response(a),
                keyword_2=_to_entry_response(b),
                score=score,
                keyword_1_reference_count=reference_counts.get(a.id, 0),
                keyword_2_reference_count=reference_counts.get(b.id, 0),
            )
            for a, b, score in pairs
        ]
    )
