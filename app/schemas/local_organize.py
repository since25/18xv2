from __future__ import annotations

from pydantic import BaseModel, Field


class LocalOrganizeScanRequest(BaseModel):
    root_path: str
    target_root: str
    whitelist_keywords: list[str] = Field(default_factory=list, max_length=500)
    fuzzy_match: bool = True
    max_results: int = Field(default=500, ge=1, le=5000)


class LocalOrganizeCandidateResponse(BaseModel):
    source_path: str
    source_name: str
    matched_keyword: str
    target_path: str
    status: str
    reasons: list[str]


class LocalOrganizeScanResponse(BaseModel):
    root_path: str
    target_root: str
    total_candidates: int
    total_move_candidates: int
    total_ambiguous: int
    skipped_count: int
    truncated_count: int
    items: list[LocalOrganizeCandidateResponse]


class LocalOrganizeExecuteRequest(BaseModel):
    root_path: str
    target_root: str
    items: list[LocalOrganizeCandidateResponse] = Field(min_length=1, max_length=2000)
    dry_run: bool = True
    confirm_execute: bool = False


class LocalOrganizeExecuteItemResponse(BaseModel):
    source_path: str
    target_path: str
    success: bool
    status: str
    error_message: str | None = None


class LocalOrganizeExecuteResponse(BaseModel):
    root_path: str
    target_root: str
    dry_run: bool
    total_requested: int
    total_processed: int
    items: list[LocalOrganizeExecuteItemResponse]


class LocalOrganizeDebugRequest(BaseModel):
    folder_name: str = Field(min_length=1)
    whitelist_keywords: list[str] = Field(default_factory=list, max_length=500)
    fuzzy_match: bool = True


class LocalOrganizeDebugRuleMatchResponse(BaseModel):
    keyword_entry_id: int | None = None
    canonical_name: str
    matched_terms: list[str]
    all_terms: list[str]


class LocalOrganizeDebugResponse(BaseModel):
    folder_name: str
    normalized_folder_name: str
    status: str
    matched_rule_count: int
    matched_rules: list[LocalOrganizeDebugRuleMatchResponse]
