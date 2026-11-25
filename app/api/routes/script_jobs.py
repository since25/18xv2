from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.script_runs import ScriptJobConfig, ScriptRun
from app.schemas.script_jobs import (
    ScriptJobChangeListResponse,
    ScriptJobListResponse,
    ScriptJobRunRequest,
    ScriptJobRunStarted,
    ScriptJobUpdate,
    ScriptJobView,
    SiteSessionStatus,
    SiteSessionUpdate,
)
from app.core.config import get_settings
from app.services.script_jobs import config_service, run_store
from app.services.script_jobs.definitions import get_definition
from app.services.script_jobs.runner import JobBusy, ScriptJobRunner
from app.services.script_jobs.site_session import save_site_session, site_session_status


router = APIRouter(tags=["script-jobs"])


def _session_path() -> Path:
    return Path(get_settings().sehuatang_session_path)


def get_script_job_runner(request: Request) -> ScriptJobRunner:
    """取 lifespan 里创建的执行器单例。"""
    runner = getattr(request.app.state, "script_job_runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="脚本执行器尚未启动")
    return runner


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _latest_run(db: Session, job_name: str, *, active: bool) -> ScriptRun | None:
    status_filter = (
        ScriptRun.status.in_(run_store.ACTIVE_STATUSES) if active else ScriptRun.status.not_in(run_store.ACTIVE_STATUSES)
    )
    return db.scalar(
        select(ScriptRun)
        .where(ScriptRun.script_name == job_name, status_filter)
        .order_by(ScriptRun.started_at.desc(), ScriptRun.id.desc())
        .limit(1)
    )


def _job_view(db: Session, config: ScriptJobConfig, now: datetime) -> dict[str, object]:
    definition = get_definition(config.job_name)
    active_run = _latest_run(db, config.job_name, active=True)
    latest_run = _latest_run(db, config.job_name, active=False)
    # 最近一次结束的运行失败时，在页面顶部提示原因（例如站点 cookie 失效），直到下一次成功
    alert = latest_run.error_reason if latest_run is not None and latest_run.status == "failed" else None
    return {
        "job_name": config.job_name,
        "label": definition.label,
        "executor": config.executor,
        "enabled": bool(config.enabled),
        "run_time": config.run_time,
        "params": config.params,
        "runnable": definition.runnable,
        "next_run_at": _iso(config_service.next_run_at(config, now)),
        "active_run": run_store.run_response(active_run) if active_run is not None else None,
        "latest_run": run_store.run_response(latest_run) if latest_run is not None else None,
        "alert": alert,
        "site_session": site_session_status(_session_path()) if config.job_name == "sehuatang" else None,
    }


def _get_config_or_404(db: Session, job_name: str) -> ScriptJobConfig:
    try:
        return config_service.get_config(db, job_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="脚本不存在") from exc


@router.get("/script-jobs", response_model=ScriptJobListResponse)
def list_script_jobs(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(UTC)
    return {"items": [_job_view(db, config, now) for config in config_service.list_configs(db)]}


@router.put("/script-jobs/sehuatang/site-session", response_model=SiteSessionStatus)
def update_sehuatang_site_session(payload: SiteSessionUpdate) -> dict[str, object]:
    """保存 sehuatang 站点 cookie 和浏览器 User-Agent；响应里不含 cookie。"""
    try:
        save_site_session(_session_path(), payload.cookie, payload.user_agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return site_session_status(_session_path())


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
    return _job_view(db, config, datetime.now(UTC))


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


@router.post("/script-jobs/{job_name}/runs", response_model=ScriptJobRunStarted, status_code=201)
def start_script_job_run(
    job_name: str,
    payload: ScriptJobRunRequest,
    db: Session = Depends(get_db),
    runner: ScriptJobRunner = Depends(get_script_job_runner),
) -> dict[str, object]:
    """手动运行或演练一次。"""
    _get_config_or_404(db, job_name)
    try:
        run_id = runner.start(job_name, trigger="manual", dry_run=payload.dry_run)
    except JobBusy as exc:
        raise HTTPException(status_code=409, detail="该脚本已有运行中或排队中的任务") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.expire_all()
    run = db.get(ScriptRun, run_id)
    return {"run_id": run_id, "status": run.status if run is not None else "running"}
