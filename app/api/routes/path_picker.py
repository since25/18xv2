from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.schemas.path_picker import DirectoryPickerRequest, DirectoryPickerResponse
from app.schemas.path_picker import PathPresetResponse
from app.services.path_picker_service import PathPickerError, PathPickerService

router = APIRouter(prefix="/system/path-picker", tags=["path-picker"])


@router.post("/directory", response_model=DirectoryPickerResponse)
def pick_directory(payload: DirectoryPickerRequest) -> DirectoryPickerResponse:
    try:
        path = PathPickerService().pick_directory(title=payload.title, initial_path=payload.initial_path)
    except PathPickerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DirectoryPickerResponse(path=path)


@router.get("/presets", response_model=list[PathPresetResponse])
def list_path_presets() -> list[PathPresetResponse]:
    settings = get_settings()
    items: list[PathPresetResponse] = []
    for raw_path in settings.local_path_presets:
        cleaned = raw_path.strip()
        if not cleaned:
            continue
        label = cleaned.rstrip("/").split("/")[-1] or cleaned
        items.append(PathPresetResponse(label=label, path=cleaned))
    return items
