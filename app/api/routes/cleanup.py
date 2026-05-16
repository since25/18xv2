from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db
from app.schemas.cleanup import (
    NoiseFileDeleteRequest,
    NoiseFileDeleteResponse,
    NoiseFilePreviewRequest,
    NoiseFilePreviewResponse,
)
from app.services.cleanup.noise_cleanup_service import NoiseCleanupService
from app.services.client_115.client import Real115Client

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post("/noise-files/preview", response_model=NoiseFilePreviewResponse)
def preview_noise_files(
    payload: NoiseFilePreviewRequest,
    db: Session = Depends(get_db),
) -> NoiseFilePreviewResponse:
    return NoiseCleanupService(db).preview_files(
        import_id=payload.import_id,
        filenames=payload.filenames,
        limit_per_filename=payload.limit_per_filename,
    )


@router.post("/noise-files/delete", response_model=NoiseFileDeleteResponse)
def delete_noise_files(
    payload: NoiseFileDeleteRequest,
    db: Session = Depends(get_db),
    client: Real115Client = Depends(get_115_client),
) -> NoiseFileDeleteResponse:
    try:
        return NoiseCleanupService(db, client=client).delete_files(
            import_id=payload.import_id,
            file_ids=payload.file_ids,
            dry_run=payload.dry_run,
            confirm_delete=payload.confirm_delete,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


