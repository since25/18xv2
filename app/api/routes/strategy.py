from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.node import NodeResponse, StrategyAnalyzeRequest
from app.schemas.strategy import (
    KeywordCandidateListResponse,
    KeywordCandidateRequest,
    KeywordCandidateResponse,
    NoiseFileCandidateListResponse,
    NoiseFileCandidateRequest,
    NoiseFileCandidateResponse,
)
from app.services.classifier.keyword_candidate_service import KeywordCandidateService
from app.services.classifier.noise_file_service import NoiseFileService
from app.services.planner.plan_service import PlanService
from app.services.strategy_rule_service import StrategyRuleService

router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.post("/analyze", response_model=list[NodeResponse])
def analyze_strategy(payload: StrategyAnalyzeRequest, db: Session = Depends(get_db)) -> list[NodeResponse]:
    if payload.import_id is None:
        raise HTTPException(status_code=400, detail="import_id is required")
    planner = PlanService(db, StrategyRuleService(db).build_classifier())
    nodes = planner.analyze(import_id=payload.import_id, node_ids=payload.node_ids)
    return [NodeResponse.model_validate(node) for node in nodes]


@router.post("/keywords/candidates", response_model=KeywordCandidateListResponse)
def list_keyword_candidates(payload: KeywordCandidateRequest, db: Session = Depends(get_db)) -> KeywordCandidateListResponse:
    service = KeywordCandidateService(db)
    candidates, total_nodes = service.list_candidates(
        import_id=payload.import_id,
        min_count=payload.min_count,
        limit=payload.limit,
        node_ids=payload.node_ids,
    )
    return KeywordCandidateListResponse(
        import_id=payload.import_id,
        total_nodes=total_nodes,
        total_candidates=len(candidates),
        candidates=[
            KeywordCandidateResponse(
                keyword=item.keyword,
                count=item.count,
                score=item.score,
                bracket_hits=item.bracket_hits,
                examples=item.examples,
            )
            for item in candidates
        ],
    )


@router.post("/noise-files/candidates", response_model=NoiseFileCandidateListResponse)
def list_noise_file_candidates(
    payload: NoiseFileCandidateRequest,
    db: Session = Depends(get_db),
) -> NoiseFileCandidateListResponse:
    service = NoiseFileService(db)
    candidates, total_files = service.list_candidates(
        import_id=payload.import_id,
        min_count=payload.min_count,
        limit=payload.limit,
        file_ids=payload.file_ids or payload.node_ids,
        suspicious_only=payload.suspicious_only,
    )
    return NoiseFileCandidateListResponse(
        import_id=payload.import_id,
        total_files=total_files,
        total_candidates=len(candidates),
        candidates=[
            NoiseFileCandidateResponse(
                filename=item.filename,
                count=item.count,
                score=item.score,
                reasons=sorted(item.reasons),
                examples=item.examples,
            )
            for item in candidates
        ],
    )


@router.get("/keywords/workbench")
def keyword_workbench() -> RedirectResponse:
    return RedirectResponse(url="/extractor/keywords/workbench", status_code=307)
