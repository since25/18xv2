from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class JellyfinJobResponse(BaseModel):
    job_id: str
    job_type: str
    stage: str
    current: int
    total: int
    done: bool
    error: str | None = None
    summary: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None


class JellyfinStatusResponse(BaseModel):
    scan_enabled: bool
    sync_enabled: bool
    local_roots: list[str]
    strm_roots: list[str]
    latest_scan: JellyfinJobResponse | None = None
    latest_sync: JellyfinJobResponse | None = None
    counts: dict[str, int]
    collections: dict[str, int]


class JellyfinUnmatchedItem(BaseModel):
    id: int
    source: Literal["local", "strm_115"]
    path: str
    match_state: Literal["unmatched", "nfo_error"]
    match_note: str | None = None


class JellyfinUnmatchedResponse(BaseModel):
    total: int
    items: list[JellyfinUnmatchedItem]


class JellyfinConflictItem(BaseModel):
    keyword_entry_id: int | None = None
    canonical_name_snapshot: str
    status: str
    last_error: str | None = None


class JellyfinConflictResponse(BaseModel):
    items: list[JellyfinConflictItem]
