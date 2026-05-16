from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ORMModel


class NodeTagResponse(ORMModel):
    id: int
    tag: str
    score: float
    source: str


class NodeResponse(ORMModel):
    id: int
    import_id: int
    raw_name: str
    normalized_name: str
    raw_path: str
    parent_path: str | None
    depth: int
    node_type: str
    parent_id: int | None
    fingerprint_hint: str
    tags: list[NodeTagResponse] = []


class NodePageResponse(BaseModel):
    total: int
    items: list[NodeResponse]


class StrategyAnalyzeRequest(BaseModel):
    node_ids: list[int] | None = None
    import_id: int | None = None
