from __future__ import annotations

from pydantic import BaseModel, Field


class LocalTreeExportRequest(BaseModel):
    root_path: str = Field(min_length=1)
    root_name: str | None = Field(default=None, max_length=255)
    output_name: str | None = Field(default=None, max_length=255)
    include_files: bool = True


class LocalTreeExportResponse(BaseModel):
    root_path: str
    root_name: str
    output_path: str
    output_filename: str
    folder_count: int
    file_count: int
    line_count: int


class LocalTreeExportFileResponse(BaseModel):
    filename: str
    path: str
    size_bytes: int
    updated_at: float
