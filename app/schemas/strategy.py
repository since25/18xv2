from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordCandidateRequest(BaseModel):
    import_id: int
    node_ids: list[int] | None = None
    min_count: int = Field(default=2, ge=1, le=100)
    limit: int = Field(default=30, ge=1, le=200)


class KeywordCandidateResponse(BaseModel):
    keyword: str
    count: int
    score: float
    bracket_hits: int
    examples: list[str]


class KeywordCandidateListResponse(BaseModel):
    import_id: int
    total_nodes: int
    total_candidates: int
    candidates: list[KeywordCandidateResponse]


class NoiseFileCandidateRequest(BaseModel):
    import_id: int
    file_ids: list[int] | None = None
    node_ids: list[int] | None = None
    min_count: int = Field(default=2, ge=1, le=500)
    limit: int = Field(default=30, ge=1, le=200)
    suspicious_only: bool = True


class NoiseFileCandidateResponse(BaseModel):
    filename: str
    count: int
    score: float
    reasons: list[str]
    examples: list[str]


class NoiseFileCandidateListResponse(BaseModel):
    import_id: int
    total_files: int
    total_candidates: int
    candidates: list[NoiseFileCandidateResponse]
