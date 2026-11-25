"""运行记录的读写：Unraid 回报和 18x 执行共用一套记录。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.script_runs import ScriptRun, ScriptRunItem
from app.schemas.script_runs import ScriptRunCounts


ALL_COUNT_KEYS = tuple(ScriptRunCounts.model_fields)
ACTIVE_STATUSES = ("queued", "running")
ITEM_LIMIT = 5000
ITEM_RETENTION_DAYS = 90

# 各脚本不适用的计数强制归零，避免回报里的杂值混进趋势
_IRRELEVANT_COUNTS = {
    "DEL_SOMETHING": ("moved", "duplicates_removed", "failed"),
    "MOVE_SSD_CACHE_TO_DISK2": (
        "deleted_dirs",
        "deleted_files",
        "empty_dirs",
        "moved_new",
        "moved_rescan",
        "ambiguous",
        "errors",
        "warnings",
    ),
}


def now_utc() -> datetime:
    """当前 UTC 时间；测试里替换它来固定“现在”。"""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def counts_dict(value: dict[str, int] | ScriptRunCounts | None, script_name: str | None = None) -> dict[str, int]:
    raw = value.model_dump() if isinstance(value, ScriptRunCounts) else (value or {})
    counts = {key: max(0, int(raw.get(key, 0) or 0)) for key in ALL_COUNT_KEYS}
    for key in _IRRELEVANT_COUNTS.get(script_name or "", ()):
        counts[key] = 0
    return counts


def status_for(
    exit_code: int,
    counts: dict[str, int],
    item_kinds: list[str] | None = None,
) -> Literal["success", "warning", "failed"]:
    """Unraid 回报的状态判定（阶段 6 规则）。"""
    kinds = set(item_kinds or [])
    if exit_code != 0 or counts.get("errors", 0) > 0 or counts.get("failed", 0) > 0 or "error" in kinds:
        return "failed"
    if counts.get("warnings", 0) > 0 or counts.get("ambiguous", 0) > 0 or "warning" in kinds or "ambiguous" in kinds:
        return "warning"
    return "success"


def run_response(run: ScriptRun) -> dict[str, object]:
    return {
        "id": run.id,
        "run_key": run.run_key,
        "script_name": run.script_name,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "exit_code": run.exit_code,
        "status": run.status,
        "counts": counts_dict(run.counts),
        "items_truncated": bool(run.items_truncated),
        "received_at": iso(run.received_at),
        "trigger": run.trigger or "report",
        "dry_run": bool(run.dry_run),
        "error_reason": run.error_reason,
        "has_log": bool(run.log_path),
    }


def cleanup_expired_items(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(days=ITEM_RETENTION_DAYS)
    db.execute(
        delete(ScriptRunItem).where(
            ScriptRunItem.run_id.in_(select(ScriptRun.id).where(ScriptRun.finished_at < cutoff))
        )
    )


def build_items(items: list[dict]) -> list[ScriptRunItem]:
    return [
        ScriptRunItem(
            kind=item["kind"],
            path=item.get("path"),
            target_path=item.get("target_path"),
            keyword=item.get("keyword"),
            message=item.get("message"),
        )
        for item in items[:ITEM_LIMIT]
    ]


def create_run(db: Session, *, job_name: str, trigger: str, dry_run: bool, status: str) -> ScriptRun:
    """创建一条 18x 执行的运行记录（排队或运行中）。"""
    now = now_utc()
    run = ScriptRun(
        run_key=f"{job_name}:{trigger}:{iso(now)}:{uuid4().hex[:8]}",
        script_name=job_name,
        started_at=now,
        status=status,
        counts={},
        items_truncated=False,
        received_at=now,
        trigger=trigger,
        dry_run=dry_run,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session,
    run: ScriptRun,
    *,
    exit_code: int | None,
    status: str,
    counts: dict,
    items: list[dict],
    error_reason: str | None,
) -> None:
    """写入结束状态、计数和名单（名单最多 5000 条），并顺带清理过期名单。"""
    now = now_utc()
    cleanup_expired_items(db, now)
    run.finished_at = now
    run.exit_code = exit_code
    run.status = status
    run.counts = counts_dict(counts, run.script_name)
    run.error_reason = error_reason
    run.items_truncated = len(items) > ITEM_LIMIT
    run.items = build_items(items)
    db.add(run)
    db.commit()
