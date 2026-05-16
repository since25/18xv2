from __future__ import annotations

from pydantic import BaseModel, Field


class NoiseFilePreviewRequest(BaseModel):
    import_id: int
    filenames: list[str] = Field(min_length=1, max_length=100)
    limit_per_filename: int = Field(default=50, ge=1, le=200)


class NoiseFilePreviewItemResponse(BaseModel):
    file_id: int
    filename: str
    raw_path: str
    parent_path: str | None


class NoiseFilePreviewGroupResponse(BaseModel):
    filename: str
    count: int
    items: list[NoiseFilePreviewItemResponse]


class NoiseFilePreviewResponse(BaseModel):
    import_id: int
    total_selected_files: int
    groups: list[NoiseFilePreviewGroupResponse]


class NoiseFileDeleteRequest(BaseModel):
    import_id: int
    file_ids: list[int] = Field(min_length=1, max_length=200)
    dry_run: bool = True
    confirm_delete: bool = False


class NoiseFileDeleteItemResponse(BaseModel):
    file_id: int
    raw_path: str
    remote_file_id: str | None = None
    success: bool
    status: str
    error_message: str | None = None


class NoiseFileDeleteResponse(BaseModel):
    import_id: int
    dry_run: bool
    total_requested: int
    total_processed: int
    items: list[NoiseFileDeleteItemResponse]
