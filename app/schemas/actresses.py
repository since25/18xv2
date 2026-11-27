"""女优档案、待删清单与删除批次接口的请求和返回模型。

已有同名模型（如 CandidateListResponse）的，这里一律加 Actress 前缀，避免接口定义里撞名。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ActressStatus = Literal["none", "blacklist", "whitelist"]
ActressAvatarState = Literal["pending", "uploaded", "present", "not_found", "no_person", "error"]
BatchStatus = Literal["pending", "running", "completed", "failed", "interrupted"]


class ActressSummary(BaseModel):
    id: int
    canonical_name: str
    aliases: list[str]
    status: ActressStatus
    film_count: int
    # 当前待删清单里因为她（黑名单演员）要删的部数
    candidate_count: int


class ActressStatusCounts(BaseModel):
    none: int
    blacklist: int
    whitelist: int


class ActressListResponse(BaseModel):
    items: list[ActressSummary]
    total: int
    # 全部女优按状态的人数，不受筛选影响
    counts: ActressStatusCounts


class ActressMarkItem(BaseModel):
    from_status: ActressStatus
    to_status: ActressStatus
    # web / player / import / merge
    source: str
    media_item_id: int | None = None
    note: str | None = None
    created_at: datetime


class ActressFilmActor(BaseModel):
    name: str
    status: ActressStatus


class ActressFilmItem(BaseModel):
    film_dir: str
    number: str
    title: str | None = None
    actors: list[ActressFilmActor]
    protected: bool
    in_candidates: bool


class ActressAliasItem(BaseModel):
    id: int
    alias: str


class ActressDetail(ActressSummary):
    # 与 aliases 同序，带 id 供网页删除别名
    alias_items: list[ActressAliasItem]
    # 新的在前
    marks: list[ActressMarkItem]
    films: list[ActressFilmItem]
    # 头像：从 Gfriends 找图、上传 Jellyfin 人物主图的状态
    avatar_state: ActressAvatarState
    avatar_note: str | None = None
    avatar_checked_at: datetime | None = None


class MediaActor(BaseModel):
    actress_id: int
    name: str
    status: ActressStatus


class MediaActorsResponse(BaseModel):
    film_dir: str
    number: str
    # 实际查到的扫描条目 id，播放器改状态时作为 media_item_id 回传
    media_item_id: int
    in_candidates: bool
    # 按 NFO 顺序
    actors: list[MediaActor]


class ActressStatusRequest(BaseModel):
    actress_ids: list[int]
    status: ActressStatus
    source: Literal["web", "player"]
    # 从哪部片上标的（扫描条目 id）
    media_item_id: int | None = None


class ActressStatusResponse(BaseModel):
    changed: int
    candidates_added: int
    candidates_removed: int


class ActressJobResponse(BaseModel):
    job_id: str


class ActressAvatarRefreshRequest(BaseModel):
    # 只处理这几个人，且不管当前头像状态都重做一次；不传时按规则挑一批
    actress_ids: list[int] | None = None
    # 本次最多处理几人；不传时用 ACTRESS_AVATARS_PER_RUN
    limit: int | None = Field(default=None, ge=1, le=2000)


class ActressCandidateItem(BaseModel):
    film_dir: str
    number: str
    title: str | None = None
    selected: bool
    added_by: Literal["mark", "daily"]
    added_at: datetime
    # 因为谁：演员里黑名单的人
    black_names: list[str]
    # 同片其他演员及其档案状态
    other_actors: list[ActressFilmActor]
    remote_state: Literal["unchecked", "found", "missing", "error"]
    remote_note: str | None = None


class ActressCandidateListResponse(BaseModel):
    items: list[ActressCandidateItem]
    total: int
    # 本次勾选的部数
    selected: int


class ActressFilmDirsRequest(BaseModel):
    film_dirs: list[str]


class ActressCandidateSelectRequest(ActressFilmDirsRequest):
    selected: bool


class ActressCountResponse(BaseModel):
    count: int


class ActressKeptItem(BaseModel):
    film_dir: str
    number: str
    created_at: datetime


class ActressKeptListResponse(BaseModel):
    items: list[ActressKeptItem]


class ActressDeleteBatchSummary(BaseModel):
    id: int
    job_id: str | None = None
    status: BatchStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deleted_films: int
    failed_films: int
    skipped_films: int
    # 删完后触发 Jellyfin 扫库的结果；没走到这一步（如中断）时为空
    jellyfin_refresh: Literal["done", "skipped", "error"] | None = None
    note: str | None = None


class ActressDeleteBatchListResponse(BaseModel):
    # 新的在前
    items: list[ActressDeleteBatchSummary]


class ActressDeleteBatchFileItem(BaseModel):
    id: int
    group: Literal[
        "remote_115", "openlist_dir", "source_strm", "organized_dir", "remote_leftover", "source_leftover"
    ]
    target: str
    remote_file_id: str | None = None
    status: Literal["pending", "deleted", "missing", "skipped", "refreshed", "failed"]
    error: str | None = None
    executed_at: datetime | None = None


class ActressDeleteBatchFilmItem(BaseModel):
    id: int
    film_dir: str
    number: str
    status: Literal["pending", "deleted", "skipped", "failed"]
    reason: str | None = None
    error: str | None = None
    finished_at: datetime | None = None
    files: list[ActressDeleteBatchFileItem]


class ActressDeleteBatchDetail(ActressDeleteBatchSummary):
    films: list[ActressDeleteBatchFilmItem]


class ActressDeleteBatchStartResponse(BaseModel):
    batch_id: int
    job_id: str


class ActressAliasRequest(BaseModel):
    alias: str


class ActressMergeRequest(BaseModel):
    into_id: int
