from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DedupeScanJobRequest(BaseModel):
    tree_import_id: int
    scope_path_prefix: str | None = None
    included_extensions: list[str] = Field(default_factory=lambda: [".mp4", ".mkv", ".avi", ".mov"])
    candidate_threshold: float = Field(default=0.82, ge=0.1, le=1.0)
    high_confidence_threshold: float = Field(default=0.92, ge=0.1, le=1.0)
    noise_words: list[str] = Field(default_factory=list)
    regex_patterns: list[str] = Field(default_factory=list)


class DedupeReviewRequest(BaseModel):
    keep_candidate_ids: list[int] = Field(default_factory=list)
    delete_candidate_ids: list[int] = Field(default_factory=list)
    note: str | None = None


class DedupeConfirmJobRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)


class DedupeGroupResponse(ORMModel):
    id: int
    scan_run_id: int
    tree_import_id: int
    representative_name: str
    normalized_name: str
    score_max: float
    confidence_level: str
    status: str
    review_note: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DedupeCandidateResponse(ORMModel):
    id: int
    group_id: int
    node_file_id: int
    raw_name: str
    raw_path: str
    file_ext: str | None
    normalized_name: str
    similarity_score: float
    suggested_action: str
    suggested_reason: str | None
    user_action: str
    user_reason: str | None


class DedupeGroupDetailResponse(BaseModel):
    group: DedupeGroupResponse
    candidates: list[DedupeCandidateResponse]


class DedupeGroupListResponse(BaseModel):
    items: list[DedupeGroupResponse]
    total: int
    page: int
    page_size: int


class DedupeScanSummary(BaseModel):
    scan_run_id: int
    total_files: int
    total_groups: int
    total_candidates: int


class DedupeJobFrame(BaseModel):
    job_id: str
    job_type: Literal["scan", "confirm", "delete"]
    stage: str
    current: int
    total: int
    done: bool
    error: str | None = None
    summary: dict | None = None
    started_at: datetime
    finished_at: datetime | None = None


class DedupeActiveJobsResponse(BaseModel):
    scan: DedupeJobFrame | None = None
    confirm: DedupeJobFrame | None = None
    delete: DedupeJobFrame | None = None
