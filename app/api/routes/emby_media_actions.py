from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMediaMapping, EmbyMetadataCandidate
from app.schemas.emby_media_actions import (
    EmbyDeleteConfirmRequest,
    EmbyDeletePlanResponse,
    EmbyDeleteScopeRequest,
    EmbyMediaIntakeRequest,
    EmbyMediaIntakeResponse,
    EmbyMetadataApplyRequest,
    EmbyMetadataCandidateResponse,
)
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService
from app.services.emby_media_actions.emby_client import EmbyClient, EmbyItemContext, build_item_context
from app.services.emby_media_actions.metadata_candidate_service import VALID_TARGET_LISTS, EmbyMetadataCandidateService
from app.services.emby_media_actions.strm_mapping_service import StrmMappingService, decode_115_open_path

router = APIRouter(prefix="/emby-media-actions", tags=["emby-media-actions"])


def _ensure_emby_media_actions_enabled() -> None:
    if not get_settings().emby_media_actions_enabled:
        raise HTTPException(status_code=404, detail="emby media actions disabled")


def _delete_plan_response(plan: EmbyDeletePlan) -> EmbyDeletePlanResponse:
    return EmbyDeletePlanResponse.model_validate(plan)


def _candidate_snapshot_actors(candidate: EmbyMetadataCandidate) -> list[dict]:
    try:
        raw_actors = json.loads(candidate.snapshot.actors_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_actors, list):
        return []
    actors: list[dict] = []
    for raw_actor in raw_actors:
        if isinstance(raw_actor, str):
            actor = {"name": raw_actor, "role": None, "provider_ids": {}}
        elif isinstance(raw_actor, dict):
            name = raw_actor.get("name") or raw_actor.get("Name")
            if not name:
                continue
            provider_ids = raw_actor.get("provider_ids") or raw_actor.get("ProviderIds") or {}
            actor = {
                "name": str(name),
                "role": raw_actor.get("role") or raw_actor.get("Role"),
                "provider_ids": provider_ids if isinstance(provider_ids, dict) else {},
            }
        else:
            continue
        actors.append(actor)
    return actors


def _metadata_candidate_response(candidate: EmbyMetadataCandidate) -> EmbyMetadataCandidateResponse:
    return EmbyMetadataCandidateResponse(
        id=candidate.id,
        target_list=candidate.target_list,
        status=candidate.status,
        emby_item_id=candidate.emby_item_id,
        snapshot_id=candidate.snapshot_id,
        created_at=candidate.created_at,
        applied_at=candidate.applied_at,
        snapshot_title=candidate.snapshot.title,
        snapshot_nfo_path=candidate.snapshot.nfo_path,
        snapshot_actors=_candidate_snapshot_actors(candidate),
    )


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


def _emby_hierarchy_ids(payload: EmbyMediaIntakeRequest, emby_item_type: str) -> tuple[str | None, str | None, str | None]:
    if emby_item_type.strip().lower() != "episode":
        return None, None, None
    emby_payload = payload.emby_payload or {}
    emby_series_id = emby_payload.get("SeriesId")
    emby_season_id = emby_payload.get("SeasonId")
    emby_episode_id = emby_payload.get("Id") or payload.emby_item_id
    return (
        str(emby_series_id) if emby_series_id else None,
        str(emby_season_id) if emby_season_id else None,
        str(emby_episode_id) if emby_episode_id else None,
    )


def _looks_like_real_emby_id(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        return False
    candidate = Path(value)
    if candidate.is_absolute():
        return False
    return "/" not in value and "\\" not in value


def _item_paths(item: dict) -> set[str]:
    paths = {str(item["Path"])} if item.get("Path") else set()
    for source in item.get("MediaSources") or []:
        path = source.get("Path")
        if path:
            paths.add(str(path))
    return paths


def _select_item_for_path(items: list[dict], path: str | None) -> dict | None:
    if not items:
        return None
    if path:
        for item in items:
            if path in _item_paths(item):
                return item
    return items[0]


def _emby_client_for_request(request: Request) -> EmbyClient | None:
    existing = getattr(request.app.state, "emby_client", None)
    if existing is not None:
        return existing
    settings = get_settings()
    if not (settings.emby_base_url and settings.emby_api_key and settings.emby_user_id):
        return None
    return EmbyClient(
        base_url=settings.emby_base_url,
        api_key=settings.emby_api_key,
        user_id=settings.emby_user_id,
    )


def _title_search_candidates(payload: EmbyMediaIntakeRequest) -> list[str]:
    candidates: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in candidates:
            candidates.append(value)

    add(payload.title)
    if payload.title and Path(payload.title).suffix:
        add(Path(payload.title).stem)
    if payload.path:
        add(Path(payload.path).stem)
    return candidates


def _resolve_item_context(payload: EmbyMediaIntakeRequest, request: Request) -> EmbyItemContext | None:
    if payload.emby_payload is not None:
        try:
            return build_item_context(payload.emby_payload)
        except KeyError as exc:
            missing_key = exc.args[0] if exc.args else "required key"
            raise HTTPException(status_code=400, detail=f"invalid emby_payload: missing {missing_key}") from exc
        except (TypeError, ValueError) as exc:
            detail = str(exc) or exc.__class__.__name__
            raise HTTPException(status_code=400, detail=f"invalid emby_payload: {detail}") from exc

    client = _emby_client_for_request(request)
    if client is None:
        return None

    if _looks_like_real_emby_id(payload.emby_item_id):
        try:
            return build_item_context(client.get_item(str(payload.emby_item_id)))
        except Exception:
            pass

    titles = _title_search_candidates(payload)
    if not titles:
        return None
    for title in titles:
        try:
            item = _select_item_for_path(client.find_items_by_title(title), payload.path)
        except Exception:
            continue
        if item is not None:
            return build_item_context(item)
    return None


def _payload_context_for_delete(payload: EmbyMediaIntakeRequest, context: EmbyItemContext | None) -> tuple[str, str, str, str | None, str | None, str | None]:
    if context is not None:
        return (
            context.emby_item_id,
            context.item_type,
            context.title or payload.title or context.emby_item_id,
            context.series_id if context.item_type.strip().lower() == "episode" else None,
            context.season_id if context.item_type.strip().lower() == "episode" else None,
            context.emby_item_id if context.item_type.strip().lower() == "episode" else None,
        )
    if not payload.emby_item_id:
        raise HTTPException(status_code=400, detail="emby_item_id is required")
    emby_item_type = _emby_item_type(payload)
    emby_series_id, emby_season_id, emby_episode_id = _emby_hierarchy_ids(payload, emby_item_type)
    return (
        payload.emby_item_id,
        emby_item_type,
        payload.title or payload.emby_item_id,
        emby_series_id,
        emby_season_id,
        emby_episode_id,
    )


@router.post("/intake", response_model=EmbyMediaIntakeResponse)
def intake(payload: EmbyMediaIntakeRequest, request: Request, db: Session = Depends(get_db)) -> EmbyMediaIntakeResponse:
    _ensure_emby_media_actions_enabled()
    item_context = _resolve_item_context(payload, request)
    if payload.action in {"metadata_blacklist", "metadata_whitelist"}:
        if item_context is None and payload.source == "iina_lua" and not payload.emby_payload:
            raise HTTPException(status_code=400, detail="emby_payload or resolvable Emby item is required")
        emby_item_id = item_context.emby_item_id if item_context is not None else payload.emby_item_id
        if not emby_item_id:
            raise HTTPException(status_code=400, detail="emby_item_id is required")
        target_list = "emby_blacklist" if payload.action == "metadata_blacklist" else "emby_whitelist"
        emby_payload = item_context.raw if item_context is not None else payload.emby_payload or {"Id": emby_item_id, "Name": payload.title}
        actors = [actor.model_dump() for actor in payload.actors] or (item_context.actors if item_context is not None else [])
        try:
            candidate = EmbyMetadataCandidateService(db).create_candidate(
                target_list=target_list,
                emby_item_id=emby_item_id,
                title=(item_context.title if item_context is not None else None) or payload.title or emby_item_id,
                nfo_xml=payload.nfo_xml,
                emby_payload=emby_payload,
                actors=actors,
                source_path=payload.nfo_path,
            )
        except ET.ParseError as exc:
            raise HTTPException(status_code=400, detail=f"invalid nfo_xml: {exc}") from exc
        return EmbyMediaIntakeResponse(ok=True, metadata_candidate=EmbyMetadataCandidateResponse.model_validate(candidate))
    if payload.action == "delete_plan":
        (
            emby_item_id,
            emby_item_type,
            emby_title,
            emby_series_id,
            emby_season_id,
            emby_episode_id,
        ) = _payload_context_for_delete(payload, item_context)
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
        mapping = service.create_mapping_from_matches(
            emby_item_id=emby_item_id,
            emby_item_type=emby_item_type,
            emby_title=emby_title,
            alist_url=stream_url,
            mount_name=decoded.mount_name,
            remote_path=decoded.remote_path,
            remote_file_id=remote_file_id or None,
            matches=matches,
            emby_series_id=emby_series_id,
            emby_season_id=emby_season_id,
            emby_episode_id=emby_episode_id,
        )
        plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope=_delete_scope_for_item_type(emby_item_type), source=payload.source)
        return EmbyMediaIntakeResponse(ok=True, delete_plan=_delete_plan_response(plan))
    raise HTTPException(status_code=400, detail="delete_plan intake requires a resolved mapping")


@router.get("/delete-plans", response_model=list[EmbyDeletePlanResponse])
def list_delete_plans(limit: int = 20, db: Session = Depends(get_db)) -> list[EmbyDeletePlanResponse]:
    _ensure_emby_media_actions_enabled()
    safe_limit = max(1, min(limit, 100))
    plans = db.scalars(select(EmbyDeletePlan).order_by(EmbyDeletePlan.id.desc()).limit(safe_limit)).all()
    return [_delete_plan_response(plan) for plan in plans]


@router.get("/delete-plans/{plan_id}", response_model=EmbyDeletePlanResponse)
def get_delete_plan(plan_id: int, db: Session = Depends(get_db)) -> EmbyDeletePlanResponse:
    _ensure_emby_media_actions_enabled()
    plan = db.get(EmbyDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="delete plan not found")
    return _delete_plan_response(plan)


@router.delete("/delete-plans/{plan_id}")
def delete_delete_plan(plan_id: int, db: Session = Depends(get_db)):
    _ensure_emby_media_actions_enabled()
    plan = db.get(EmbyDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="delete plan not found")
    if plan.status == "running":
        raise HTTPException(status_code=400, detail="running delete plan cannot be removed")
    db.delete(plan)
    db.commit()
    return {"ok": True, "plan_id": plan_id}


@router.post("/delete-plans/{plan_id}/scope", response_model=EmbyDeletePlanResponse)
def create_delete_plan_for_scope(
    plan_id: int,
    payload: EmbyDeleteScopeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> EmbyDeletePlanResponse:
    _ensure_emby_media_actions_enabled()
    plan = db.get(EmbyDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="delete plan not found")
    mapping = db.scalar(
        select(EmbyMediaMapping)
        .where(EmbyMediaMapping.emby_item_id == plan.emby_item_id)
        .order_by(EmbyMediaMapping.id.desc())
    )
    if mapping is None:
        raise HTTPException(status_code=404, detail="mapping not found for delete plan")
    settings = get_settings()
    try:
        scoped_plan = EmbyDeletePlanService(
            db,
            client_115=getattr(request.app.state, "client_115", None),
            allowed_roots=settings.emby_media_actions_source_roots + settings.emby_media_actions_organized_roots,
        ).create_plan_from_mapping(mapping_id=mapping.id, scope=payload.scope, source=plan.source)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _delete_plan_response(scoped_plan)


@router.post("/delete-plans/{plan_id}/confirm")
def confirm_delete_plan(plan_id: int, payload: EmbyDeleteConfirmRequest, request: Request, db: Session = Depends(get_db)):
    _ensure_emby_media_actions_enabled()
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    settings = get_settings()
    if settings.emby_media_actions_delete_dry_run_default:
        raise HTTPException(status_code=400, detail="real deletion disabled by EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT")
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


@router.get("/metadata-candidates", response_model=list[EmbyMetadataCandidateResponse])
def list_metadata_candidates(
    target_list: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[EmbyMetadataCandidateResponse]:
    _ensure_emby_media_actions_enabled()
    if target_list is not None and target_list not in VALID_TARGET_LISTS:
        raise HTTPException(status_code=400, detail="target_list must be emby_blacklist or emby_whitelist")
    safe_limit = max(1, min(limit, 100))
    statement = select(EmbyMetadataCandidate)
    if target_list is not None:
        statement = statement.where(EmbyMetadataCandidate.target_list == target_list)
    candidates = db.scalars(statement.order_by(EmbyMetadataCandidate.id.desc()).limit(safe_limit)).all()
    return [_metadata_candidate_response(candidate) for candidate in candidates]


@router.get("/metadata-candidates/{candidate_id}", response_model=EmbyMetadataCandidateResponse)
def get_metadata_candidate(candidate_id: int, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    _ensure_emby_media_actions_enabled()
    candidate = db.get(EmbyMetadataCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="metadata candidate not found")
    return _metadata_candidate_response(candidate)


@router.post("/metadata-candidates/{candidate_id}/apply", response_model=EmbyMetadataCandidateResponse)
def apply_metadata_candidate(candidate_id: int, payload: EmbyMetadataApplyRequest, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    _ensure_emby_media_actions_enabled()
    try:
        candidate = EmbyMetadataCandidateService(db).apply_actors(candidate_id=candidate_id, actors=payload.actors, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _metadata_candidate_response(candidate)
