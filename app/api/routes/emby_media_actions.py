from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMetadataCandidate
from app.schemas.emby_media_actions import (
    EmbyDeleteConfirmRequest,
    EmbyDeletePlanResponse,
    EmbyMediaIntakeRequest,
    EmbyMediaIntakeResponse,
    EmbyMetadataApplyRequest,
    EmbyMetadataCandidateResponse,
)
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService
from app.services.emby_media_actions.metadata_candidate_service import EmbyMetadataCandidateService
from app.services.emby_media_actions.strm_mapping_service import StrmMappingService, decode_115_open_path

router = APIRouter(prefix="/emby-media-actions", tags=["emby-media-actions"])


def _delete_plan_response(plan: EmbyDeletePlan) -> EmbyDeletePlanResponse:
    return EmbyDeletePlanResponse.model_validate(plan)


def _emby_item_type(payload: EmbyMediaIntakeRequest) -> str:
    if payload.emby_payload:
        item_type = payload.emby_payload.get("Type")
        if item_type:
            return str(item_type)
    return "Unknown"


def _delete_scope_for_item_type(emby_item_type: str) -> str:
    if emby_item_type.strip().lower() == "episode":
        return "episode"
    return "movie"


@router.post("/intake", response_model=EmbyMediaIntakeResponse)
def intake(payload: EmbyMediaIntakeRequest, request: Request, db: Session = Depends(get_db)) -> EmbyMediaIntakeResponse:
    if payload.action in {"metadata_blacklist", "metadata_whitelist"}:
        if not payload.emby_item_id:
            raise HTTPException(status_code=400, detail="emby_item_id is required")
        target_list = "emby_blacklist" if payload.action == "metadata_blacklist" else "emby_whitelist"
        emby_payload = payload.emby_payload or {"Id": payload.emby_item_id, "Name": payload.title}
        try:
            candidate = EmbyMetadataCandidateService(db).create_candidate(
                target_list=target_list,
                emby_item_id=payload.emby_item_id,
                title=payload.title or payload.emby_item_id,
                nfo_xml=payload.nfo_xml,
                emby_payload=emby_payload,
                actors=[actor.model_dump() for actor in payload.actors],
                source_path=payload.nfo_path,
            )
        except ET.ParseError as exc:
            raise HTTPException(status_code=400, detail=f"invalid nfo_xml: {exc}") from exc
        return EmbyMediaIntakeResponse(ok=True, metadata_candidate=EmbyMetadataCandidateResponse.model_validate(candidate))
    if payload.action == "delete_plan":
        if not payload.emby_item_id:
            raise HTTPException(status_code=400, detail="emby_item_id is required")
        stream_url = payload.url
        if not stream_url and payload.path and payload.path.endswith(".strm"):
            try:
                with open(payload.path, "r", encoding="utf-8", errors="ignore") as file:
                    stream_url = file.readline().strip()
            except OSError as exc:
                raise HTTPException(status_code=400, detail=f"cannot read strm path: {exc}") from exc
        if not stream_url:
            raise HTTPException(status_code=400, detail="url or readable strm path is required")

        settings = get_settings()
        try:
            decoded = decode_115_open_path(stream_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        matches = StrmMappingService(
            strm_roots=settings.emby_media_actions_strm_roots,
            source_roots=settings.emby_media_actions_source_roots,
            organized_roots=settings.emby_media_actions_organized_roots,
        ).scan_for_url(stream_url)
        remote_file_id = None
        client_115 = getattr(request.app.state, "client_115", None)
        if client_115 is not None:
            try:
                remote_payload = client_115.get_file(path=decoded.remote_path)
                remote_file_id = str((remote_payload.get("data") or {}).get("file_id") or "")
            except Exception:
                remote_file_id = None
        service = EmbyDeletePlanService(
            db,
            client_115=client_115,
            allowed_roots=settings.emby_media_actions_source_roots + settings.emby_media_actions_organized_roots,
        )
        emby_item_type = _emby_item_type(payload)
        mapping = service.create_mapping_from_matches(
            emby_item_id=payload.emby_item_id,
            emby_item_type=emby_item_type,
            emby_title=payload.title or payload.emby_item_id,
            alist_url=stream_url,
            mount_name=decoded.mount_name,
            remote_path=decoded.remote_path,
            remote_file_id=remote_file_id or None,
            matches=matches,
        )
        plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope=_delete_scope_for_item_type(emby_item_type), source=payload.source)
        return EmbyMediaIntakeResponse(ok=True, delete_plan=_delete_plan_response(plan))
    raise HTTPException(status_code=400, detail="delete_plan intake requires a resolved mapping")


@router.get("/delete-plans/{plan_id}", response_model=EmbyDeletePlanResponse)
def get_delete_plan(plan_id: int, db: Session = Depends(get_db)) -> EmbyDeletePlanResponse:
    plan = db.get(EmbyDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="delete plan not found")
    return _delete_plan_response(plan)


@router.post("/delete-plans/{plan_id}/confirm")
def confirm_delete_plan(plan_id: int, payload: EmbyDeleteConfirmRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        summary = EmbyDeletePlanService(
            db,
            client_115=getattr(request.app.state, "client_115", None),
            allowed_roots=settings.emby_media_actions_source_roots + settings.emby_media_actions_organized_roots,
        ).execute_plan(plan_id, confirm=payload.confirm)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"plan_id": summary.plan_id, "total": summary.total, "deleted": summary.deleted, "failed": summary.failed, "blocked": summary.blocked}


@router.get("/metadata-candidates/{candidate_id}", response_model=EmbyMetadataCandidateResponse)
def get_metadata_candidate(candidate_id: int, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    candidate = db.get(EmbyMetadataCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="metadata candidate not found")
    return EmbyMetadataCandidateResponse.model_validate(candidate)


@router.post("/metadata-candidates/{candidate_id}/apply", response_model=EmbyMetadataCandidateResponse)
def apply_metadata_candidate(candidate_id: int, payload: EmbyMetadataApplyRequest, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    try:
        candidate = EmbyMetadataCandidateService(db).apply_actors(candidate_id=candidate_id, actors=payload.actors, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmbyMetadataCandidateResponse.model_validate(candidate)
