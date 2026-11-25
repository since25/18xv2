from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.script_runs import ScriptJobConfig, ScriptRun, ScriptRunItem
from app.schemas.script_runs import (
    ScriptRunCreate,
    ScriptRunItemKind,
    ScriptRunItemsResponse,
    ScriptRunResponse,
)
from app.api.routes.script_jobs import get_script_job_runner
from app.schemas.script_jobs import ScriptRunLogChunk
from app.services.script_jobs import config_service, run_store
from app.services.script_jobs.logs import read_log
from app.services.script_jobs.runner import RunNotActive, ScriptJobRunner


router = APIRouter(tags=["script-runs"])
SHANGHAI = ZoneInfo("Asia/Shanghai")
# 预定时间过后多久仍没有记录才算“今天没有运行记录”
MISSING_GRACE = timedelta(hours=2)


@router.post("/script-runs", response_model=ScriptRunResponse)
def create_script_run(payload: ScriptRunCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    """接收 Unraid 脚本的回报（切换到 18x 执行前仍在使用）。"""
    now = run_store.now_utc()
    run_store.cleanup_expired_items(db, now)
    existing = db.scalar(select(ScriptRun).where(ScriptRun.run_key == payload.run_key))
    if existing is not None:
        db.commit()
        return run_store.run_response(existing)

    counts = run_store.counts_dict(payload.counts, payload.script_name)
    items = payload.items
    run = ScriptRun(
        run_key=payload.run_key,
        script_name=payload.script_name,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
        exit_code=payload.exit_code,
        status=run_store.status_for(payload.exit_code, counts, [item.kind for item in items]),
        counts=counts,
        items_truncated=len(items) > run_store.ITEM_LIMIT,
        received_at=now,
        trigger="report",
        dry_run=False,
    )
    run.items = run_store.build_items([item.model_dump() for item in items])
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ScriptRun).where(ScriptRun.run_key == payload.run_key))
        if existing is None:
            raise
        return run_store.run_response(existing)
    db.refresh(run)
    return run_store.run_response(run)


def _local_date(value: datetime):
    return run_store.as_utc(value).astimezone(SHANGHAI).date()


def _today_status(config: ScriptJobConfig, today_runs: list[ScriptRun], now_local: datetime) -> str:
    """今日状态：先看今天的真实运行，其次看配置，最后按预定时间判断是否漏跑。"""
    if today_runs:
        latest = max(today_runs, key=lambda run: (run_store.as_utc(run.started_at), run.id))
        return latest.status
    if config.executor == "18x" and not config.enabled:
        return "disabled"
    if config.job_name == "sehuatang" and config.executor == "unraid":
        # 切换前 sehuatang 在 Unraid 上运行且不回报，没法判断是否漏跑
        return "not_tracked"
    cutoff = config_service.scheduled_time_on(now_local.date(), config.run_time) + MISSING_GRACE
    return "pending" if now_local <= cutoff else "missing"


@router.get("/script-runs/summary")
def script_runs_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now_local = run_store.now_utc().astimezone(SHANGHAI)
    today = now_local.date()
    first_day = today - timedelta(days=days - 1)
    start_utc = datetime.combine(first_day, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    end_utc = datetime.combine(today + timedelta(days=1), time.min, tzinfo=SHANGHAI).astimezone(UTC)
    # 演练不计入趋势，也不算“今天已运行”
    recent_runs = list(
        db.scalars(
            select(ScriptRun)
            .where(
                ScriptRun.started_at >= start_utc,
                ScriptRun.started_at < end_utc,
                ScriptRun.dry_run.is_(False),
            )
            .order_by(ScriptRun.started_at.asc(), ScriptRun.id.asc())
        ).all()
    )
    days_result: list[dict[str, object]] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        del_runs = [
            run for run in recent_runs if run.script_name == "DEL_SOMETHING" and _local_date(run.started_at) == day
        ]
        counts = [run_store.counts_dict(run.counts) for run in del_runs]
        days_result.append(
            {
                "date": day.isoformat(),
                "has_run": bool(del_runs),
                "cleaned": sum(item["deleted_dirs"] + item["deleted_files"] for item in counts),
                "moved_new": sum(item["moved_new"] for item in counts),
            }
        )

    scripts: list[dict[str, object]] = []
    for config in config_service.list_configs(db):
        latest = db.scalar(
            select(ScriptRun)
            .where(ScriptRun.script_name == config.job_name)
            .order_by(ScriptRun.started_at.desc(), ScriptRun.id.desc())
            .limit(1)
        )
        today_runs = [
            run for run in recent_runs if run.script_name == config.job_name and _local_date(run.started_at) == today
        ]
        scripts.append(
            {
                "script_name": config.job_name,
                "expected_time": config.run_time,
                "executor": config.executor,
                "enabled": bool(config.enabled),
                "latest_run": run_store.run_response(latest) if latest is not None else None,
                "today_status": _today_status(config, today_runs, now_local),
            }
        )
    return {"timezone": "Asia/Shanghai", "days": days_result, "scripts": scripts}


@router.get("/script-runs")
def list_script_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    total = int(db.scalar(select(func.count()).select_from(ScriptRun)) or 0)
    rows = db.scalars(
        select(ScriptRun)
        .order_by(ScriptRun.started_at.desc(), ScriptRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"total": total, "items": [run_store.run_response(row) for row in rows]}


@router.post("/script-runs/{run_id}/stop")
def stop_script_run(
    run_id: int,
    db: Session = Depends(get_db),
    runner: ScriptJobRunner = Depends(get_script_job_runner),
) -> dict[str, object]:
    if db.get(ScriptRun, run_id) is None:
        raise HTTPException(status_code=404, detail="脚本运行记录不存在")
    try:
        runner.stop(run_id)
    except RunNotActive as exc:
        raise HTTPException(status_code=409, detail="这次运行已经结束") from exc
    return {"ok": True}


@router.get("/script-runs/{run_id}/log", response_model=ScriptRunLogChunk)
def read_script_run_log(
    run_id: int,
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    run = db.get(ScriptRun, run_id)
    if run is None or not run.log_path or not Path(run.log_path).is_file():
        raise HTTPException(status_code=404, detail="这次运行没有日志")
    path = Path(run.log_path)
    run_ended = run.status not in run_store.ACTIVE_STATUSES
    text, next_offset = read_log(path, offset, finished=run_ended)
    # 运行结束且已读到文件末尾才算读完；一次最多 64KB，没读完时前端继续取
    finished = run_ended and next_offset >= path.stat().st_size
    return {"text": text, "next_offset": next_offset, "finished": finished}


@router.get("/script-runs/{run_id}/items", response_model=ScriptRunItemsResponse)
def list_script_run_items(
    run_id: int,
    kind: ScriptRunItemKind | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(ScriptRun, run_id) is None:
        raise HTTPException(status_code=404, detail="脚本运行记录不存在")
    kind_counts = dict(
        db.execute(
            select(ScriptRunItem.kind, func.count(ScriptRunItem.id))
            .where(ScriptRunItem.run_id == run_id)
            .group_by(ScriptRunItem.kind)
        ).all()
    )
    conditions = [ScriptRunItem.run_id == run_id]
    if kind is not None:
        conditions.append(ScriptRunItem.kind == kind)
    if q:
        conditions.append(
            or_(
                ScriptRunItem.path.contains(q, autoescape=True),
                ScriptRunItem.target_path.contains(q, autoescape=True),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(ScriptRunItem).where(*conditions)) or 0)
    rows = db.scalars(
        select(ScriptRunItem).where(*conditions).order_by(ScriptRunItem.id.asc()).offset(offset).limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "path": row.path,
                "target_path": row.target_path,
                "keyword": row.keyword,
                "message": row.message,
            }
            for row in rows
        ],
        "kind_counts": {key: int(value) for key, value in kind_counts.items()},
    }
