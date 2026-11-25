from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.script_runs import ScriptJobConfig
from app.schemas.script_jobs import (
    ScriptJobChangeListResponse,
    ScriptJobListResponse,
    ScriptJobUpdate,
    ScriptJobView,
)
from app.services.script_jobs import config_service
from app.services.script_jobs.definitions import get_definition


router = APIRouter(tags=["script-jobs"])


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _job_view(config: ScriptJobConfig, now: datetime) -> dict[str, object]:
    definition = get_definition(config.job_name)
    return {
        "job_name": config.job_name,
        "label": definition.label,
        "executor": config.executor,
        "enabled": bool(config.enabled),
        "run_time": config.run_time,
        "params": config.params,
        "runnable": definition.runnable,
        "next_run_at": _iso(config_service.next_run_at(config, now)),
    }


def _get_config_or_404(db: Session, job_name: str) -> ScriptJobConfig:
    try:
        return config_service.get_config(db, job_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="脚本不存在") from exc


@router.get("/script-jobs", response_model=ScriptJobListResponse)
def list_script_jobs(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(UTC)
    return {"items": [_job_view(config, now) for config in config_service.list_configs(db)]}


@router.put("/script-jobs/{job_name}", response_model=ScriptJobView)
def update_script_job(job_name: str, payload: ScriptJobUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    _get_config_or_404(db, job_name)
    try:
        config = config_service.update_config(
            db,
            job_name,
            enabled=payload.enabled,
            run_time=payload.run_time,
            executor=payload.executor,
            params=payload.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _job_view(config, datetime.now(UTC))


@router.get("/script-jobs/{job_name}/changes", response_model=ScriptJobChangeListResponse)
def list_script_job_changes(
    job_name: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _get_config_or_404(db, job_name)
    rows = config_service.list_changes(db, job_name, limit)
    return {
        "items": [
            {
                "id": row.id,
                "job_name": row.job_name,
                "changed_at": _iso(row.changed_at),
                "before": row.before,
                "after": row.after,
            }
            for row in rows
        ]
    }
