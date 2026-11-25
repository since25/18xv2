from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ScriptName = Literal["sehuatang", "DEL_SOMETHING", "MOVE_SSD_CACHE_TO_DISK2"]
ScriptRunItemKind = Literal[
    "deleted_dir",
    "deleted_file",
    "empty_dir",
    "moved_new",
    "moved_rescan",
    "ambiguous",
    "skipped",
    "error",
    "warning",
    # sehuatang
    "submitted",
    "title_blocked",
    "torrent_blocked",
    "submit_failed",
    "parse_failed",
]
ScriptRunStatus = Literal["queued", "running", "success", "warning", "failed", "stopped", "interrupted"]
ScriptRunTrigger = Literal["report", "scheduled", "manual"]


class ScriptRunCounts(BaseModel):
    deleted_dirs: int = Field(default=0, ge=0)
    deleted_files: int = Field(default=0, ge=0)
    empty_dirs: int = Field(default=0, ge=0)
    moved_new: int = Field(default=0, ge=0)
    moved_rescan: int = Field(default=0, ge=0)
    ambiguous: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    unparsed_lines: int = Field(default=0, ge=0)
    moved: int = Field(default=0, ge=0)
    duplicates_removed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    # sehuatang
    pages_ok: int = Field(default=0, ge=0)
    pages_failed: int = Field(default=0, ge=0)
    posts_found: int = Field(default=0, ge=0)
    title_blocked: int = Field(default=0, ge=0)
    torrent_blocked: int = Field(default=0, ge=0)
    skipped_seen: int = Field(default=0, ge=0)
    submitted: int = Field(default=0, ge=0)
    submit_failed: int = Field(default=0, ge=0)
    parse_failed: int = Field(default=0, ge=0)


class ScriptRunItemPayload(BaseModel):
    kind: ScriptRunItemKind
    path: str | None = None
    target_path: str | None = None
    keyword: str | None = None
    message: str | None = None


class ScriptRunCreate(BaseModel):
    run_key: str = Field(min_length=1, max_length=512)
    script_name: ScriptName
    started_at: datetime
    finished_at: datetime
    exit_code: int
    counts: ScriptRunCounts
    items: list[ScriptRunItemPayload] = Field(default_factory=list)

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value.astimezone(UTC)


class ScriptRunResponse(BaseModel):
    id: int
    run_key: str
    script_name: str
    started_at: str
    finished_at: str | None
    exit_code: int | None
    status: ScriptRunStatus
    counts: ScriptRunCounts
    items_truncated: bool
    received_at: str
    trigger: ScriptRunTrigger
    dry_run: bool
    error_reason: str | None
    has_log: bool


class ScriptRunItemResponse(BaseModel):
    id: int
    kind: str
    path: str | None = None
    target_path: str | None = None
    keyword: str | None = None
    message: str | None = None


class ScriptRunItemsResponse(BaseModel):
    total: int
    items: list[ScriptRunItemResponse]
    kind_counts: dict[str, int]
