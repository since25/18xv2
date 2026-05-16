from __future__ import annotations

from pydantic import BaseModel


class TokenPayload(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None


class DeviceCodePayload(BaseModel):
    uid: str
    time: int | str
    qrcode: str
    sign: str


class NodePayload(BaseModel):
    id: str
    name: str
    path: str
    parent_id: str | None = None
    is_file: bool | None = None


class ClientActionResult(BaseModel):
    success: bool
    action: str
    message: str
    payload: dict | None = None


class OfflineTaskPayload(BaseModel):
    task_id: str | None = None
    info_hash: str | None = None
    url: str | None = None
    name: str | None = None
    status: str | None = None
