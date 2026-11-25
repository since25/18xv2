"""脚本配置的读取、校验和修改（修改前后完整留痕）。"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.script_runs import ScriptJobConfig, ScriptJobConfigChange
from app.services.script_jobs.definitions import DEFINITIONS, JOB_NAMES, get_definition, validate_run_time


SHANGHAI = ZoneInfo("Asia/Shanghai")
EXECUTORS = ("unraid", "18x")


def ensure_default_configs(db: Session) -> None:
    """缺少的脚本配置按默认值补齐（生产库由迁移写入，这里兜底测试库和开发库）。"""
    existing = set(db.scalars(select(ScriptJobConfig.job_name)).all())
    added = False
    for name in JOB_NAMES:
        if name in existing:
            continue
        definition = DEFINITIONS[name]
        db.add(
            ScriptJobConfig(
                job_name=name,
                executor="unraid",
                enabled=False,
                run_time=definition.default_run_time,
                params=copy.deepcopy(definition.default_params),
                updated_at=datetime.now(UTC),
            )
        )
        added = True
    if added:
        db.commit()


def list_configs(db: Session) -> list[ScriptJobConfig]:
    """按固定顺序返回三个脚本的配置。"""
    ensure_default_configs(db)
    rows = {row.job_name: row for row in db.scalars(select(ScriptJobConfig)).all()}
    return [rows[name] for name in JOB_NAMES if name in rows]


def get_config(db: Session, job_name: str) -> ScriptJobConfig:
    """取单个脚本配置；未知脚本名抛 KeyError。"""
    get_definition(job_name)
    ensure_default_configs(db)
    row = db.scalar(select(ScriptJobConfig).where(ScriptJobConfig.job_name == job_name))
    if row is None:
        raise KeyError(job_name)
    return row


def config_snapshot(config: ScriptJobConfig) -> dict:
    return {
        "executor": config.executor,
        "enabled": bool(config.enabled),
        "run_time": config.run_time,
        "params": copy.deepcopy(config.params),
    }


def _validate_params(job_name: str, params: dict) -> dict:
    model = get_definition(job_name).params_model
    try:
        return model.model_validate(params).model_dump()
    except ValidationError as exc:
        reasons = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error.get("loc", ())) or "参数"
            message = str(error.get("msg", "")).removeprefix("Value error, ")
            reasons.append(f"{field}：{message}")
        raise ValueError("参数不合法：" + "；".join(reasons)) from exc


def update_config(
    db: Session,
    job_name: str,
    *,
    enabled: bool | None,
    run_time: str | None,
    executor: str | None,
    params: dict | None,
) -> ScriptJobConfig:
    """修改配置；校验失败抛中文 ValueError，有变化时记一条修改记录。"""
    config = get_config(db, job_name)
    definition = get_definition(job_name)
    before = config_snapshot(config)
    after = copy.deepcopy(before)

    if run_time is not None:
        after["run_time"] = validate_run_time(run_time)
    if executor is not None:
        if executor not in EXECUTORS:
            raise ValueError("执行方只能是 unraid 或 18x")
        if executor == "18x" and not definition.runnable:
            raise ValueError("该脚本尚未支持在 18x 执行")
        after["executor"] = executor
    if enabled is not None:
        after["enabled"] = bool(enabled)
    if params is not None:
        after["params"] = _validate_params(job_name, params)

    if after == before:
        return config

    config.executor = after["executor"]
    config.enabled = after["enabled"]
    config.run_time = after["run_time"]
    config.params = after["params"]
    config.updated_at = datetime.now(UTC)
    db.add(ScriptJobConfigChange(job_name=job_name, changed_at=config.updated_at, before=before, after=after))
    db.commit()
    db.refresh(config)
    return config


def list_changes(db: Session, job_name: str, limit: int = 20) -> list[ScriptJobConfigChange]:
    get_definition(job_name)
    return list(
        db.scalars(
            select(ScriptJobConfigChange)
            .where(ScriptJobConfigChange.job_name == job_name)
            .order_by(ScriptJobConfigChange.changed_at.desc(), ScriptJobConfigChange.id.desc())
            .limit(limit)
        ).all()
    )


def scheduled_time_on(day, run_time: str) -> datetime:
    """某天（上海日期）的预定运行时刻，带上海时区。"""
    hour, minute = (int(part) for part in run_time.split(":", 1))
    return datetime.combine(day, time(hour, minute), tzinfo=SHANGHAI)


def next_run_at(config: ScriptJobConfig, now: datetime) -> datetime | None:
    """由 18x 执行且已启用时，返回下一次预定运行的 UTC 时刻；否则返回 None。"""
    if config.executor != "18x" or not config.enabled:
        return None
    local_now = now.astimezone(SHANGHAI)
    candidate = scheduled_time_on(local_now.date(), config.run_time)
    if candidate <= local_now:
        candidate = scheduled_time_on(local_now.date() + timedelta(days=1), config.run_time)
    return candidate.astimezone(UTC)
