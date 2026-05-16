from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.services.client_115.schemas import NodePayload


class ArticleSearchRequest(BaseModel):
    keyword_entry_id: int | None = None
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class ArticleCandidateResponse(BaseModel):
    source_tid: int
    source_title: str
    source_magnet: str
    source_detail_url: str | None = None
    source_section: str | None = None
    source_category: str | None = None
    source_sub_type: str | None = None
    source_size: int | None = None
    matched_keyword: str | None = None
    matched_alias: str | None = None
    match_score: float = 0.0


class ArticleSearchResponse(BaseModel):
    query: str
    keyword_entry_id: int | None = None
    total_candidates: int
    candidates: list[ArticleCandidateResponse]


class DuplicateCheckItemRequest(BaseModel):
    source_tid: int
    source_title: str = Field(min_length=1)
    source_magnet: str = Field(min_length=1)
    matched_keyword: str | None = None
    matched_alias: str | None = None


class DuplicateCheckRequest(BaseModel):
    items: list[DuplicateCheckItemRequest] = Field(min_length=1, max_length=100)
    # 指定则用本地目录树匹配，不指定则走 115 搜索接口
    tree_import_id: int | None = None


class DuplicateCheckItemResponse(BaseModel):
    source_tid: int
    duplicate_status: str
    duplicate_reason: str | None = None
    search_terms: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    matched_import_id: int | None = None
    matched_import_label: str | None = None
    matched_nodes: list[NodePayload] = Field(default_factory=list)


class DuplicateCheckResponse(BaseModel):
    items: list[DuplicateCheckItemResponse]


class MagnetTaskCreateItem(BaseModel):
    source_tid: int
    source_title: str = Field(min_length=1)
    source_magnet: str = Field(min_length=1)
    source_detail_url: str | None = None
    source_section: str | None = None
    matched_keyword: str | None = None
    matched_alias: str | None = None
    match_score: float = 0.0
    keyword_entry_id: int | None = None
    target_path: str | None = None
    target_cid: str | None = None


class MagnetTaskCreateRequest(BaseModel):
    items: list[MagnetTaskCreateItem] = Field(min_length=1, max_length=100)
    target_cid: str | None = None
    force_submit: bool = False
    tree_import_id: int | None = None


class MagnetTaskResponse(ORMModel):
    id: int
    batch_id: str | None = None
    keyword_entry_id: int | None = None
    source_tid: int
    source_title: str
    source_magnet: str
    source_detail_url: str | None = None
    source_section: str | None = None
    matched_keyword: str | None = None
    matched_alias: str | None = None
    match_score: str | None = None
    duplicate_status: str
    duplicate_detail: str | None = None
    status: str
    target_cid: str | None = None
    task_id_115: str | None = None
    submitted_to_115_at: datetime | None = None
    failure_reason: str | None = None
    operation_log: str | None = None
    created_at: datetime
    updated_at: datetime


class MagnetTaskBatchResponse(BaseModel):
    created_count: int
    submitted_count: int
    duplicate_skipped_count: int
    tasks: list[MagnetTaskResponse]


class MagnetTaskBatchSummaryResponse(BaseModel):
    batch_id: str
    created_at: datetime
    total_count: int
    submitted_count: int
    duplicate_skipped_count: int
    failed_count: int
    pending_count: int
    items: list[MagnetTaskResponse]


class MagnetTaskBatchSummaryListResponse(BaseModel):
    total: int
    batches: list[MagnetTaskBatchSummaryResponse]


class WhitelistBatchRequest(BaseModel):
    tree_import_id: int
    keyword_entry_ids: list[int] = Field(default_factory=list, max_length=500)
    per_keyword_limit: int = Field(default=10, ge=1, le=100)
    total_limit: int = Field(default=100, ge=1, le=500)
    force_submit: bool = False
    submit_limit: int = Field(default=20, ge=1, le=100)


class WhitelistBatchCandidateResponse(BaseModel):
    source_tid: int
    source_title: str
    source_magnet: str
    source_detail_url: str | None = None
    source_section: str | None = None
    matched_keyword: str | None = None
    matched_alias: str | None = None
    match_score: float = 0.0
    keyword_entry_id: int | None = None
    duplicate_status: str
    duplicate_reason: str | None = None
    matched_import_id: int | None = None
    matched_import_label: str | None = None
    target_path: str


class WhitelistBatchPreviewResponse(BaseModel):
    scanned_keyword_count: int
    total_candidates: int
    selected_candidates: int
    candidates: list[WhitelistBatchCandidateResponse]


class WhitelistBatchSubmitResponse(BaseModel):
    scanned_keyword_count: int
    total_candidates: int
    selected_candidates: int
    created_count: int
    submitted_count: int
    duplicate_skipped_count: int
    failed_count: int
    tasks: list[MagnetTaskResponse]
