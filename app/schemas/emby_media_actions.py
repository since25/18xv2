from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EmbyAction = Literal["delete_plan", "metadata_blacklist", "metadata_whitelist"]


class EmbyActorPayload(BaseModel):
    name: str
    role: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)


class EmbyMediaIntakeRequest(BaseModel):
    action: EmbyAction
    path: str | None = None
    url: str | None = None
    title: str | None = None
    emby_item_id: str | None = None
    emby_payload: dict | None = None
    nfo_path: str | None = None
    source: str = "api"
    nfo_xml: str | None = None
    actors: list[EmbyActorPayload] = Field(default_factory=list)


class EmbyMetadataCandidateResponse(BaseModel):
    id: int
    target_list: str
    status: str
    emby_item_id: str
    snapshot_id: int
    created_at: datetime
    applied_at: datetime | None

    model_config = {"from_attributes": True}


class EmbyDeletePlanItemResponse(BaseModel):
    id: int
    group: str
    target_type: str
    target_path: str | None
    remote_file_id: str | None
    display_name: str
    status: str
    blocked_reason: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class EmbyDeletePlanResponse(BaseModel):
    id: int
    source: str
    emby_item_id: str
    scope: str
    status: str
    summary: str
    total_items: int
    deleted_count: int
    failed_count: int
    blocked_count: int
    items: list[EmbyDeletePlanItemResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EmbyMediaIntakeResponse(BaseModel):
    ok: bool
    delete_plan: EmbyDeletePlanResponse | None = None
    metadata_candidate: EmbyMetadataCandidateResponse | None = None


class EmbyMetadataApplyRequest(BaseModel):
    actors: list[str]
    note: str | None = None


class EmbyDeleteConfirmRequest(BaseModel):
    confirm: bool = False
