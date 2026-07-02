from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReviewBucket = Literal["whitelist", "blacklist"]


class ReviewKeywordCandidate(BaseModel):
    keyword: str
    count: int = 1
    source: str = "manual_path_regex"
    examples: list[str] = Field(default_factory=list)
    match_status: str = "new"
    matched_entry_id: int | None = None
    matched_canonical_name: str | None = None
    matched_keyword_type: str | None = None
    similar_score: float | None = None


class ReviewIntakeCreateRequest(BaseModel):
    bucket: ReviewBucket
    raw_path: str = Field(min_length=1, max_length=20000)
    source: str = Field(default="shortcut", max_length=64)
    note: str | None = None
    pattern: str = Field(default=r"[【「『［\[]([^】」』］\]]+)[】」』］\]]", min_length=1, max_length=500)
    flags: str = Field(default="", max_length=20)
    group_index: int = Field(default=1, ge=0, le=20)
    limit: int = Field(default=20, ge=1, le=200)


class ReviewIntakePathRequest(BaseModel):
    raw_path: str = Field(min_length=1, max_length=20000)
    source: str = Field(default="shortcut", max_length=64)
    note: str | None = None
    pattern: str = Field(default=r"[【「『［\[]([^】」』］\]]+)[】」』］\]]", min_length=1, max_length=500)
    flags: str = Field(default="", max_length=20)
    group_index: int = Field(default=1, ge=0, le=20)
    limit: int = Field(default=20, ge=1, le=200)


class ReviewIntakeApproveRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    note: str | None = None


class ReviewIntakeDismissRequest(BaseModel):
    note: str | None = None


class ReviewIntakeItemResponse(BaseModel):
    id: int
    bucket: ReviewBucket
    raw_path: str
    normalized_path: str
    path_hash: str
    source: str
    note: str | None
    keyword_candidates: list[ReviewKeywordCandidate]
    status: str
    approved_keyword_entry_id: int | None
    approved_keyword: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewIntakeListResponse(BaseModel):
    items: list[ReviewIntakeItemResponse]
    total: int
    page: int
    page_size: int


class ReviewIntakeSummaryResponse(BaseModel):
    whitelist_pending: int = 0
    blacklist_pending: int = 0
    whitelist_approved: int = 0
    blacklist_approved: int = 0
    whitelist_dismissed: int = 0
    blacklist_dismissed: int = 0
