from __future__ import annotations

from pydantic import BaseModel, Field


class DirectoryPickerRequest(BaseModel):
    title: str = Field(default="选择目录", max_length=255)
    initial_path: str | None = Field(default=None, max_length=2000)


class DirectoryPickerResponse(BaseModel):
    path: str


class PathPresetResponse(BaseModel):
    label: str
    path: str
