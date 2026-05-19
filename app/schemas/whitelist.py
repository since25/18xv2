"""白名单批处理 API schemas。详见
docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4.4
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


# ── 请求 ──────────────────────────────────────────────────────────────
class ScanJobRequest(BaseModel):
    tree_import_id: int
    keyword_entry_ids: list[int] | None = None
    per_keyword_limit: int = Field(default=10, ge=1, le=200)


class SubmitJobRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
    force_submit: bool = False


class DismissRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class BulkDismissRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)


# ── 汇总 ──────────────────────────────────────────────────────────────
class ScanSummary(BaseModel):
    scanned_keywords: int
    new: int
    updated: int
    skipped: int
    failed_keywords: int


class SubmitSummary(BaseModel):
    submitted: int
    failed: int
    skipped: int


# ── 进度帧 ────────────────────────────────────────────────────────────
class JobFrame(BaseModel):
    job_id: str
    job_type: Literal["scan", "submit"]
    stage: str
    current: int
    total: int
    done: bool
    error: str | None = None
    summary: ScanSummary | SubmitSummary | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ActiveJobsResponse(BaseModel):
    scan: JobFrame | None = None
    submit: JobFrame | None = None


# ── 候选行 ────────────────────────────────────────────────────────────
class CandidateResponse(ORMModel):
    id: int
    source_tid: int
    source_magnet: str
    source_title: str
    source_section: str | None
    source_detail_url: str | None
    matched_keyword_entry_id: int
    matched_keyword: str
    matched_alias: str | None
    match_score: float
    last_scanned_tree_import_id: int | None
    duplicate_status: str
    duplicate_reason: str | None
    matched_import_label: str | None
    target_path: str
    lifecycle_status: str
    magnet_task_id: int | None
    dismissed_at: datetime | None
    submitted_at: datetime | None
    failure_reason: str | None
    first_seen_at: datetime
    last_scanned_at: datetime
    updated_at: datetime


class CandidateListResponse(BaseModel):
    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int
