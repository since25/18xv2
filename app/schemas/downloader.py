from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DownloaderSelectRequest(BaseModel):
    selected: bool


class DownloaderSubmitRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)


class DownloaderPackageSubmitRequest(BaseModel):
    # 未命中白名单的资源包直接按资源包 ID 提交
    package_ids: list[int] = Field(min_length=1)


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


class DownloaderIgnoreRequest(BaseModel):
    candidate_ids: list[int] | None = None
    package_ids: list[int] | None = None
    # 按频道忽略：忽略该频道当前在收件箱里的全部资源包
    channel_title: str | None = None
    reason: str | None = None


class DownloaderKeywordQuickAddRequest(BaseModel):
    # 收件箱搜索词一键加入白名单 / 黑名单；dry_run=True 只预览影响，不落库
    keyword: str = Field(min_length=1, max_length=255)
    list_type: Literal["whitelist", "blacklist"]
    dry_run: bool = True


class DownloaderUnignoreRequest(BaseModel):
    package_ids: list[int] = Field(min_length=1)


class DownloaderRetryRequest(BaseModel):
    only_failed: bool = False


class DownloaderInboxResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
