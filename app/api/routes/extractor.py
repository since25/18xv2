from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.extractor import (
    ExtractedKeywordListResponse,
    ExtractedKeywordResponse,
    ManualPathRegexExtractRequest,
    ManualKeywordExtractRequest,
    RegexExtractPreviewResponse,
    RegexKeywordExtractRequest,
    RegexMatchPreviewResponse,
)
from app.services.classifier.keyword_extractor_service import KeywordExtractorService
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

router = APIRouter(prefix="/extractor", tags=["extractor"])


def _resolve_keyword_candidates(
    db: Session,
    items: list[tuple[str, int, str, list[str]]],
) -> tuple[list[dict], dict[str, dict]]:
    registry = KeywordRegistryService(db)
    ignore_entries, _ = registry.list_entries(keyword_type="ignore", status="active", limit=5000)
    ignore_tokens = {
        alias.alias_normalized
        for entry in ignore_entries
        for alias in entry.aliases
    } | {entry.canonical_name_normalized for entry in ignore_entries}

    resolved_items: list[dict] = []
    resolution_by_keyword: dict[str, dict] = {}

    for keyword, count, source, examples in items:
        normalized = normalize_keyword_text(keyword)
        if normalized in ignore_tokens:
            resolution = {
                "keyword": keyword,
                "count": count,
                "source": source,
                "examples": examples,
                "match_status": "ignored",
                "matched_entry_id": None,
                "matched_canonical_name": None,
                "similar_score": None,
            }
        else:
            matched_entry = registry.find_entry_by_keyword(normalized)
            if matched_entry is not None:
                resolution = {
                    "keyword": keyword,
                    "count": count,
                    "source": source,
                    "examples": examples,
                    "match_status": "existing",
                    "matched_entry_id": matched_entry.id,
                    "matched_canonical_name": matched_entry.canonical_name,
                    "similar_score": None,
                }
            else:
                similar_items = registry.suggest_similar(
                    [keyword],
                    threshold=0.75,
                    limit=1,
                    keyword_types=["whitelist", "tag"],
                )
                similar = similar_items[0] if similar_items else None
                resolution = {
                    "keyword": keyword,
                    "count": count,
                    "source": source,
                    "examples": examples,
                    "match_status": "similar" if similar else "new",
                    "matched_entry_id": similar.matched_entry_id if similar else None,
                    "matched_canonical_name": similar.matched_canonical_name if similar else None,
                    "similar_score": similar.score if similar else None,
                }

        resolved_items.append(resolution)
        resolution_by_keyword[keyword] = resolution

    return resolved_items, resolution_by_keyword


def _build_extracted_response(
    payload: ManualKeywordExtractRequest | RegexKeywordExtractRequest | ManualPathRegexExtractRequest,
    total_nodes: int,
    raw_items: list[tuple[str, int, str, list[str]]],
    db: Session,
) -> ExtractedKeywordListResponse:
    resolved_items, _ = _resolve_keyword_candidates(db, raw_items)
    actionable_items = [item for item in resolved_items if item["match_status"] in {"new", "similar"}]
    return ExtractedKeywordListResponse(
        import_id=payload.import_id,
        total_nodes=total_nodes,
        total_keywords=len(actionable_items),
        total_actionable_keywords=len(actionable_items),
        total_existing_keywords=sum(1 for item in resolved_items if item["match_status"] == "existing"),
        total_ignored_keywords=sum(1 for item in resolved_items if item["match_status"] == "ignored"),
        total_blacklisted_keywords=0,
        total_similar_keywords=sum(1 for item in resolved_items if item["match_status"] == "similar"),
        keywords=[ExtractedKeywordResponse(**item) for item in actionable_items[: payload.limit]],
    )


@router.post("/keywords/manual", response_model=ExtractedKeywordListResponse)
def extract_manual_keywords(
    payload: ManualKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    keywords, total_nodes = service.extract_manual_keywords(
        import_id=payload.import_id,
        keywords=payload.keywords,
        node_ids=payload.node_ids,
        case_sensitive=payload.case_sensitive,
        limit=payload.limit,
    )
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )


@router.post("/keywords/regex", response_model=ExtractedKeywordListResponse)
def extract_regex_keywords(
    payload: RegexKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    try:
        keywords, _, total_nodes = service.extract_regex_keywords(
            import_id=payload.import_id,
            pattern=payload.pattern,
            node_ids=payload.node_ids,
            flags=payload.flags,
            group_index=payload.group_index,
            min_count=payload.min_count,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )


@router.post("/keywords/regex-preview", response_model=RegexExtractPreviewResponse)
def preview_regex_keywords(
    payload: RegexKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> RegexExtractPreviewResponse:
    service = KeywordExtractorService(db)
    try:
        _, preview, total_nodes = service.extract_regex_keywords(
            import_id=payload.import_id,
            pattern=payload.pattern,
            node_ids=payload.node_ids,
            flags=payload.flags,
            group_index=payload.group_index,
            min_count=payload.min_count,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, resolution_by_keyword = _resolve_keyword_candidates(
        db,
        [
            (
                item.extracted_keyword,
                1,
                "regex",
                [item.raw_path],
            )
            for item in preview
        ],
    )
    actionable_preview = [item for item in preview if resolution_by_keyword[item.extracted_keyword]["match_status"] in {"new", "similar"}]
    return RegexExtractPreviewResponse(
        import_id=payload.import_id,
        pattern=payload.pattern,
        flags=payload.flags,
        total_nodes=total_nodes,
        total_matches=len(preview),
        total_actionable_matches=len(actionable_preview),
        preview=[
            RegexMatchPreviewResponse(
                node_id=item.node_id,
                folder_name=item.folder_name,
                raw_path=item.raw_path,
                extracted_keyword=item.extracted_keyword,
                match_status=resolution_by_keyword[item.extracted_keyword]["match_status"],
                matched_entry_id=resolution_by_keyword[item.extracted_keyword]["matched_entry_id"],
                matched_canonical_name=resolution_by_keyword[item.extracted_keyword]["matched_canonical_name"],
                similar_score=resolution_by_keyword[item.extracted_keyword]["similar_score"],
            )
            for item in actionable_preview[: payload.limit]
        ],
    )


@router.post("/keywords/manual-path-regex", response_model=RegexExtractPreviewResponse)
def preview_manual_path_regex_keywords(
    payload: ManualPathRegexExtractRequest,
    db: Session = Depends(get_db),
) -> RegexExtractPreviewResponse:
    service = KeywordExtractorService(db)
    try:
        _, preview, total_nodes = service.extract_regex_keywords_from_path(
            raw_path=payload.raw_path,
            pattern=payload.pattern,
            flags=payload.flags,
            group_index=payload.group_index,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, resolution_by_keyword = _resolve_keyword_candidates(
        db,
        [
            (
                item.extracted_keyword,
                1,
                "manual_path_regex",
                [item.raw_path],
            )
            for item in preview
        ],
    )
    actionable_preview = [item for item in preview if resolution_by_keyword[item.extracted_keyword]["match_status"] in {"new", "similar"}]
    return RegexExtractPreviewResponse(
        import_id=payload.import_id,
        pattern=payload.pattern,
        flags=payload.flags,
        total_nodes=total_nodes,
        total_matches=len(preview),
        total_actionable_matches=len(actionable_preview),
        preview=[
            RegexMatchPreviewResponse(
                node_id=item.node_id,
                folder_name=item.folder_name,
                raw_path=item.raw_path,
                extracted_keyword=item.extracted_keyword,
                match_status=resolution_by_keyword[item.extracted_keyword]["match_status"],
                matched_entry_id=resolution_by_keyword[item.extracted_keyword]["matched_entry_id"],
                matched_canonical_name=resolution_by_keyword[item.extracted_keyword]["matched_canonical_name"],
                similar_score=resolution_by_keyword[item.extracted_keyword]["similar_score"],
            )
            for item in actionable_preview[: payload.limit]
        ],
    )


@router.post("/keywords/manual-path-regex/summary", response_model=ExtractedKeywordListResponse)
def extract_manual_path_regex_keywords(
    payload: ManualPathRegexExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    try:
        keywords, _, total_nodes = service.extract_regex_keywords_from_path(
            raw_path=payload.raw_path,
            pattern=payload.pattern,
            flags=payload.flags,
            group_index=payload.group_index,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )
