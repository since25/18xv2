from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DownloaderSelectRequest(BaseModel):
    selected: bool


class DownloaderSubmitRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)


class DownloaderControlRequest(BaseModel):
    state: Literal["pause", "resume"]


class DownloaderCandidateListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class DownloaderTaskListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
