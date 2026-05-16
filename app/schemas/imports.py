from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TreeImportResponse(ORMModel):
    id: int
    source_filename: str
    imported_at: datetime
    status: str
    note: str | None
    source_type: str = "file_upload"


class TreeImportSummaryResponse(ORMModel):
    id: int
    source_filename: str
    imported_at: datetime
    status: str
    note: str | None
    source_type: str = "file_upload"


class TreeImportPageResponse(BaseModel):
    total: int
    items: list[TreeImportSummaryResponse]


class TreeImportEntryResponse(BaseModel):
    id: int
    entry_type: str
    raw_name: str
    normalized_name: str
    raw_path: str
    parent_path: str | None = None
    depth: int
    remote_id: str | None = None


class TreeImportEntryPageResponse(BaseModel):
    total: int
    items: list[TreeImportEntryResponse]


class RemoteFetchRequest(BaseModel):
    cid: str = Field(..., min_length=1, description="115 目录 ID")
    path_label: str = Field(default="", description="可读路径标签（仅展示用）")
    depth_limit: int = Field(default=3, ge=1, le=6, description="最大递归层数")
    folders_only: bool = Field(default=True, description="仅抓文件夹，跳过文件")
