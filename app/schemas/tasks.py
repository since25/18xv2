from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OrganizeTaskCreateRequest(BaseModel):
    import_id: int | None = None
    node_id: int | None = None
    keyword_entry_id: int | None = None
    source_path: str = Field(min_length=1)
    target_path: str = Field(min_length=1)
    matched_canonical_name: str | None = None


class OrganizeTaskGenerateFromKeywordRequest(BaseModel):
    import_id: int
    keyword_entry_id: int
    target_root: str = Field(min_length=1)
    replace_existing: bool = True


class OrganizeTaskGenerateFromImportRequest(BaseModel):
    import_id: int
    replace_existing: bool = True


class OrganizeTaskBatchResponse(BaseModel):
    import_id: int
    keyword_entry_id: int | None = None
    deleted_count: int
    created_count: int
    skipped_ambiguous_count: int = 0
    tasks: list["OrganizeTaskResponse"]


class AmbiguousConflictResolutionImportResponse(BaseModel):
    import_id: int
    created_count: int
    replaced_count: int = 0
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)
    tasks: list["OrganizeTaskResponse"]


class OrganizeTaskUpdateRequest(BaseModel):
    target_path: str | None = Field(default=None, min_length=1)
    status: str | None = None


class DuplicateTargetConflictGroup(BaseModel):
    target_path: str
    tasks: list["OrganizeTaskResponse"]


class DuplicateTargetConflictListResponse(BaseModel):
    import_id: int
    conflict_count: int
    groups: list[DuplicateTargetConflictGroup]


class OrganizeTaskResponse(ORMModel):
    id: int
    import_id: int | None = None
    node_id: int | None = None
    keyword_entry_id: int | None = None
    source_path: str
    target_path: str
    matched_canonical_name: str | None = None
    status: str
    failure_reason: str | None = None
    operation_log: str | None = None
    executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AmbiguousKeywordOption(BaseModel):
    id: int
    name: str


class AmbiguousConflictItem(BaseModel):
    source_path: str
    keyword_options: list[AmbiguousKeywordOption]


class AmbiguousConflictListResponse(BaseModel):
    import_id: int
    conflict_count: int
    items: list[AmbiguousConflictItem]


class AmbiguousResolveItem(BaseModel):
    source_path: str
    keyword_entry_id: int


class AmbiguousResolveRequest(BaseModel):
    import_id: int
    resolutions: list[AmbiguousResolveItem]
    replace_existing: bool = True


class AmbiguousResolveResponse(BaseModel):
    import_id: int
    created_count: int
    replaced_count: int = 0
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)


OrganizeTaskBatchResponse.model_rebuild()
DuplicateTargetConflictGroup.model_rebuild()
DuplicateTargetConflictListResponse.model_rebuild()
