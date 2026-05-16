from __future__ import annotations

from pydantic import BaseModel, Field


class LocalCleanupScanRequest(BaseModel):
    root_path: str
    blacklist_keywords: list[str] = Field(default_factory=list, max_length=500)
    fuzzy_match: bool = True
    suffix_filter: list[str] = Field(default_factory=list, max_length=50)
    max_file_size_mb: float = Field(default=0, ge=0)
    include_files: bool = True
    include_directories: bool = True
    max_results: int = Field(default=500, ge=1, le=5000)


class LocalCleanupScanCandidateResponse(BaseModel):
    entry_type: str
    path: str
    name: str
    size_bytes: int | None = None
    decision: str
    reasons: list[str]


class LocalCleanupScanResponse(BaseModel):
    root_path: str
    total_candidates: int
    total_delete_candidates: int
    total_keep_candidates: int
    skipped_count: int
    items: list[LocalCleanupScanCandidateResponse]


class LocalCleanupDeleteRequest(BaseModel):
    root_path: str
    paths: list[str] = Field(min_length=1, max_length=2000)
    dry_run: bool = True
    confirm_delete: bool = False
    remove_empty_dirs: bool = True


class LocalCleanupDeleteItemResponse(BaseModel):
    path: str
    entry_type: str
    success: bool
    status: str
    error_message: str | None = None


class LocalCleanupDeleteResponse(BaseModel):
    root_path: str
    dry_run: bool
    total_requested: int
    total_processed: int
    removed_empty_dirs: int
    items: list[LocalCleanupDeleteItemResponse]
