from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedResponse


KeywordType = Literal["whitelist", "blacklist", "ignore", "tag"]


class KeywordAliasResponse(TimestampedResponse):
    id: int
    alias: str
    alias_normalized: str
    source: str
    note: str | None = None


class KeywordEntryCreateRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    keyword_type: KeywordType
    aliases: list[str] = Field(default_factory=list, max_length=200)
    note: str | None = None


class KeywordEntryUpdateRequest(BaseModel):
    canonical_name: str | None = Field(default=None, min_length=1, max_length=255)
    keyword_type: KeywordType | None = None
    status: str | None = Field(default=None, max_length=32)
    note: str | None = None


class KeywordEntryBatchImportRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=500)
    keyword_type: KeywordType
    import_id: int | None = None
    pattern: str | None = Field(default=None, max_length=500)
    flags: str | None = Field(default=None, max_length=20)
    source: str = Field(default="manual", max_length=32)
    note: str | None = None
    examples_by_keyword: dict[str, list[str]] = Field(default_factory=dict)
    source_folder_name_by_keyword: dict[str, str] = Field(default_factory=dict)


class KeywordEntryMergeRequest(BaseModel):
    canonical_entry_id: int
    merge_entry_ids: list[int] = Field(min_length=1, max_length=100)
    note: str | None = None


class KeywordAliasAddRequest(BaseModel):
    aliases: list[str] = Field(min_length=1, max_length=200)
    source: str = Field(default="manual", max_length=32)


class SimilarKeywordPreviewRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=500)
    threshold: float = Field(default=0.75, ge=0.1, le=1.0)
    limit: int = Field(default=20, ge=1, le=200)


class KeywordHitResponse(TimestampedResponse):
    id: int
    raw_keyword: str
    normalized_keyword: str
    keyword_entry_id: int | None = None
    canonical_name_snapshot: str | None = None
    source_path: str
    source_folder_name: str
    import_id: int | None = None
    match_rule: str | None = None
    match_source: str


class KeywordHitRebuildRequest(BaseModel):
    import_id: int
    include_files: bool = True
    include_folders: bool = True
    replace_existing: bool = True


class KeywordHitRebuildResponse(BaseModel):
    import_id: int
    deleted_count: int
    created_count: int
    scanned_folder_count: int
    scanned_file_count: int
    matched_keyword_count: int


class KeywordTreeHitSummaryResponse(ORMModel):
    keyword_entry_id: int
    canonical_name: str
    keyword_type: KeywordType
    status: str
    hit_count: int
    sample_paths: list[str] = Field(default_factory=list)


class KeywordTreeHitSummaryListResponse(BaseModel):
    total: int
    items: list[KeywordTreeHitSummaryResponse]


class KeywordEntryResponse(TimestampedResponse):
    id: int
    canonical_name: str
    canonical_name_normalized: str
    keyword_type: KeywordType
    status: str
    note: str | None = None
    updated_at: datetime | None = None
    aliases: list[KeywordAliasResponse] = []


class KeywordEntryListResponse(BaseModel):
    total: int
    entries: list[KeywordEntryResponse]


class KeywordEntryBatchImportResponse(BaseModel):
    created_count: int
    existing_count: int
    entries: list[KeywordEntryResponse]


class SimilarKeywordSuggestionResponse(ORMModel):
    keyword: str
    matched_entry_id: int
    matched_canonical_name: str
    score: float


class SimilarKeywordPreviewResponse(BaseModel):
    total: int
    suggestions: list[SimilarKeywordSuggestionResponse]


class KeywordLibraryEntryResponse(TimestampedResponse):
    id: int
    keyword: str
    keyword_normalized: str
    list_type: str
    source: str
    import_id: int | None = None
    pattern: str | None = None
    flags: str | None = None
    note: str | None = None


class KeywordLibraryBatchCreateRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=500)
    list_type: Literal["whitelist", "blacklist", "ignore", "tag"]
    source: str = Field(default="manual", max_length=32)
    import_id: int | None = None
    pattern: str | None = Field(default=None, max_length=500)
    flags: str | None = Field(default=None, max_length=20)
    note: str | None = None


class KeywordLibraryBatchCreateResponse(BaseModel):
    created_count: int
    skipped_count: int
    entries: list[KeywordLibraryEntryResponse]


class KeywordOperationLogResponse(TimestampedResponse):
    id: int
    action: str
    keyword_entry_id: int | None = None
    related_keyword_entry_id: int | None = None
    detail: str | None = None


class KeywordDuplicateScanRequest(BaseModel):
    keyword_type: KeywordType | None = None
    status: str | None = Field(default="active", max_length=32)
    threshold: float = Field(default=0.85, ge=0.1, le=1.0)


class KeywordDuplicatePairResponse(BaseModel):
    keyword_1: KeywordEntryResponse
    keyword_2: KeywordEntryResponse
    score: float


class KeywordDuplicateScanResponse(BaseModel):
    pairs: list[KeywordDuplicatePairResponse]
