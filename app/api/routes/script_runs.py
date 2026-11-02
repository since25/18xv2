from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import json
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.script_runs import ScriptRun, ScriptRunItem
from app.schemas.script_runs import (
    ScriptRunCreate,
    ScriptRunCounts,
    ScriptRunItemKind,
    ScriptRunItemsResponse,
    ScriptRunResponse,
)


router = APIRouter(tags=["script-runs"])
SHANGHAI = ZoneInfo("Asia/Shanghai")
SCRIPT_NAMES = ("DEL_SOMETHING", "MOVE_SSD_CACHE_TO_DISK2")
DEFAULT_SCHEDULES = {"DEL_SOMETHING": "12:09", "MOVE_SSD_CACHE_TO_DISK2": "01:01"}
ALL_COUNT_KEYS = tuple(ScriptRunCounts.model_fields)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _counts_dict(value: dict[str, int] | ScriptRunCounts, script_name: str | None = None) -> dict[str, int]:
    raw = value.model_dump() if isinstance(value, ScriptRunCounts) else value
    counts = {key: max(0, int(raw.get(key, 0))) for key in ALL_COUNT_KEYS}
    if script_name == "DEL_SOMETHING":
        for key in ("moved", "duplicates_removed", "failed"):
            counts[key] = 0
    elif script_name == "MOVE_SSD_CACHE_TO_DISK2":
        for key in (
            "deleted_dirs",
            "deleted_files",
            "empty_dirs",
            "moved_new",
            "moved_rescan",
            "ambiguous",
            "errors",
            "warnings",
        ):
            counts[key] = 0
    return counts


def _status_for(
    script_name: str,
    exit_code: int,
    counts: dict[str, int],
    item_kinds: list[str] | None = None,
) -> Literal["success", "warning", "failed"]:
    kinds = set(item_kinds or [])
    if exit_code != 0 or counts.get("errors", 0) > 0 or counts.get("failed", 0) > 0 or "error" in kinds:
        return "failed"
    if counts.get("warnings", 0) > 0 or counts.get("ambiguous", 0) > 0 or "warning" in kinds or "ambiguous" in kinds:
        return "warning"
    return "success"


def _run_response(run: ScriptRun) -> dict[str, object]:
    return {
        "id": run.id,
        "run_key": run.run_key,
        "script_name": run.script_name,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "exit_code": run.exit_code,
        "status": run.status,
        "counts": _counts_dict(run.counts),
        "items_truncated": bool(run.items_truncated),
        "received_at": _iso(run.received_at),
    }


def _parse_schedules(raw: str | None) -> dict[str, str]:
    schedules = dict(DEFAULT_SCHEDULES)
    if not raw:
        return schedules
    try:
        if raw.lstrip().startswith("{"):
            values = json.loads(raw)
            if isinstance(values, dict):
                pairs = values.items()
            else:
                pairs = []
        else:
            pairs = (part.split("=", 1) for part in raw.replace(";", ",").split(",") if "=" in part)
        for key, value in pairs:
            key = str(key).strip()
            value = str(value).strip()
            if key in SCRIPT_NAMES and _valid_schedule(value):
                schedules[key] = value
    except (TypeError, ValueError, json.JSONDecodeError):
        return schedules
    return schedules


def _valid_schedule(value: str) -> bool:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59 and len(value.split(":", 1)[0]) in (1, 2)


def _schedule_cutoff(today: date, schedule: str) -> datetime:
    hour, minute = (int(part) for part in schedule.split(":", 1))
    return datetime.combine(today, time(hour, minute), tzinfo=SHANGHAI) + timedelta(hours=2)


def _cleanup_expired_items(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(days=90)
    db.execute(
        delete(ScriptRunItem).where(
            ScriptRunItem.run_id.in_(select(ScriptRun.id).where(ScriptRun.finished_at < cutoff))
        )
    )


@router.post("/script-runs", response_model=ScriptRunResponse)
def create_script_run(payload: ScriptRunCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(UTC)
    _cleanup_expired_items(db, now)
    existing = db.scalar(select(ScriptRun).where(ScriptRun.run_key == payload.run_key))
    if existing is not None:
        db.commit()
        return _run_response(existing)

    counts = _counts_dict(payload.counts, payload.script_name)
    items = payload.items
    status = _status_for(payload.script_name, payload.exit_code, counts, [item.kind for item in items])
    run = ScriptRun(
        run_key=payload.run_key,
        script_name=payload.script_name,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
        exit_code=payload.exit_code,
        status=status,
        counts=counts,
        items_truncated=len(items) > 5000,
        received_at=now,
    )
    run.items = [
        ScriptRunItem(
            kind=item.kind,
            path=item.path,
            target_path=item.target_path,
            keyword=item.keyword,
            message=item.message,
        )
        for item in items[:5000]
    ]
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ScriptRun).where(ScriptRun.run_key == payload.run_key))
        if existing is None:
            raise
        return _run_response(existing)
    db.refresh(run)
    return _run_response(run)


@router.get("/script-runs/summary")
def script_runs_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = datetime.now(UTC).astimezone(SHANGHAI)
    today = now.date()
    first_day = today - timedelta(days=days - 1)
    start_utc = datetime.combine(first_day, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    end_utc = datetime.combine(today + timedelta(days=1), time.min, tzinfo=SHANGHAI).astimezone(UTC)
    recent_runs = list(
        db.scalars(
            select(ScriptRun)
            .where(ScriptRun.started_at >= start_utc, ScriptRun.started_at < end_utc)
            .order_by(ScriptRun.started_at.asc(), ScriptRun.id.asc())
        ).all()
    )
    days_result: list[dict[str, object]] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        day_runs = [run for run in recent_runs if _as_utc(run.started_at).astimezone(SHANGHAI).date() == day]
        del_runs = [run for run in day_runs if run.script_name == "DEL_SOMETHING"]
        counts = [_counts_dict(run.counts) for run in del_runs]
        days_result.append(
            {
                "date": day.isoformat(),
                "has_run": bool(del_runs),
                "cleaned": sum(item["deleted_dirs"] + item["deleted_files"] for item in counts),
                "moved_new": sum(item["moved_new"] for item in counts),
            }
        )

    schedules = _parse_schedules(getattr(get_settings(), "script_report_schedules", None))
    scripts: list[dict[str, object]] = []
    for script_name in SCRIPT_NAMES:
        latest = db.scalar(
            select(ScriptRun)
            .where(ScriptRun.script_name == script_name)
            .order_by(ScriptRun.started_at.desc(), ScriptRun.id.desc())
            .limit(1)
        )
        today_runs = [
            run
            for run in recent_runs
            if run.script_name == script_name and _as_utc(run.started_at).astimezone(SHANGHAI).date() == today
        ]
        if today_runs:
            latest_today = max(today_runs, key=lambda run: (_as_utc(run.started_at), run.id))
            today_status = latest_today.status
        else:
            today_status = "pending" if now <= _schedule_cutoff(today, schedules[script_name]) else "missing"
        scripts.append(
            {
                "script_name": script_name,
                "expected_time": schedules[script_name],
                "latest_run": _run_response(latest) if latest is not None else None,
                "today_status": today_status,
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
    return {"total": total, "items": [_run_response(row) for row in rows]}


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
