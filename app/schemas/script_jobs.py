from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.script_runs import ScriptRunResponse


class ScriptJobUpdate(BaseModel):
    """修改脚本配置；不传的字段保持不变。"""

    enabled: bool | None = None
    run_time: str | None = None
    executor: str | None = None
    params: dict[str, Any] | None = None


class ScriptJobView(BaseModel):
    job_name: str
    label: str
    executor: str
    enabled: bool
    run_time: str
    params: dict[str, Any]
    runnable: bool
    next_run_at: str | None
    active_run: ScriptRunResponse | None = None
    latest_run: ScriptRunResponse | None = None
    alert: str | None = None


class ScriptJobListResponse(BaseModel):
    items: list[ScriptJobView]


class ScriptJobRunRequest(BaseModel):
    dry_run: bool = False


class ScriptJobRunStarted(BaseModel):
    run_id: int
    status: str


class ScriptRunLogChunk(BaseModel):
    text: str
    next_offset: int
    finished: bool


class ScriptJobChange(BaseModel):
    id: int
    job_name: str
    changed_at: str
    before: dict[str, Any]
    after: dict[str, Any]


class ScriptJobChangeListResponse(BaseModel):
    items: list[ScriptJobChange]
