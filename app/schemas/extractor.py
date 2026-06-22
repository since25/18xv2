from __future__ import annotations

from pydantic import BaseModel, Field


class ManualKeywordExtractRequest(BaseModel):
    import_id: int
    keywords: list[str] = Field(min_length=1, max_length=500)
    node_ids: list[int] | None = None
    case_sensitive: bool = False
    limit: int = Field(default=100, ge=1, le=5000)


class RegexKeywordExtractRequest(BaseModel):
    import_id: int
    pattern: str = Field(min_length=1, max_length=500)
    node_ids: list[int] | None = None
    flags: str = Field(default="", max_length=20)
    group_index: int = Field(default=1, ge=0, le=20)
    min_count: int = Field(default=1, ge=1, le=500)
    limit: int = Field(default=100, ge=1, le=5000)


class ManualPathRegexExtractRequest(BaseModel):
    import_id: int | None = None
    raw_path: str = Field(min_length=1, max_length=20000)
    pattern: str = Field(min_length=1, max_length=500)
    flags: str = Field(default="", max_length=20)
    group_index: int = Field(default=1, ge=0, le=20)
    limit: int = Field(default=100, ge=1, le=5000)


class ExtractedKeywordResponse(BaseModel):
    keyword: str
    count: int
    source: str
    examples: list[str]
    match_status: str = "new"
    matched_entry_id: int | None = None
    matched_canonical_name: str | None = None
    similar_score: float | None = None


class ExtractedKeywordListResponse(BaseModel):
    import_id: int | None
    total_nodes: int
    total_keywords: int
    total_actionable_keywords: int = 0
    total_existing_keywords: int = 0
    total_ignored_keywords: int = 0
    total_blacklisted_keywords: int = 0
    total_similar_keywords: int = 0
    keywords: list[ExtractedKeywordResponse]


class RegexMatchPreviewResponse(BaseModel):
    node_id: int
    folder_name: str
    raw_path: str
    extracted_keyword: str
    match_status: str = "new"
    matched_entry_id: int | None = None
    matched_canonical_name: str | None = None
    similar_score: float | None = None


class RegexExtractPreviewResponse(BaseModel):
    import_id: int | None
    pattern: str
    flags: str
    total_nodes: int
    total_matches: int
    total_actionable_matches: int = 0
    preview: list[RegexMatchPreviewResponse]
