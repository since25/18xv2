"""脚本定时调度：每 2 秒推进执行器，每分钟检查一次到期任务，每天清理一次旧日志。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.script_runs import ScriptJobConfig, ScriptRun
from app.services.script_jobs import config_service, run_store
from app.services.script_jobs.logs import cleanup_old_runs
from app.services.script_jobs.runner import JobBusy, ScriptJobRunner


logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")
# 预定时间之后多久内仍会启动（含 18x 停机或任务被中断后的补跑）
CATCH_UP_WINDOW = timedelta(hours=2)
# 今天已有这些状态的“定时、非演练”记录，就不再定时启动；中断（interrupted）不算
DONE_STATUSES = frozenset({"queued", "running", "success", "warning", "failed", "stopped"})


def due_jobs(configs: list[ScriptJobConfig], today_runs: list[ScriptRun], now: datetime) -> list[str]:
    """返回此刻应当定时启动的脚本名。today_runs 是今天（上海日期）开始的运行记录。"""
    now_local = now.astimezone(SHANGHAI)
    due: list[str] = []
    for config in configs:
        if config.executor != "18x" or not config.enabled:
            continue
        scheduled = config_service.scheduled_time_on(now_local.date(), config.run_time)
        if not (scheduled <= now_local < scheduled + CATCH_UP_WINDOW):
            continue
        # 预定时间之后才改的配置（例如刚从 Unraid 切过来，或把时间改成刚过去的点）当天不补跑，
        # 避免同一天 Unraid 和 18x 各跑一次；补跑只用于 18x 停机或任务被中断
        if config.updated_at is not None and run_store.as_utc(config.updated_at) > scheduled:
            continue
        already = any(
            run.script_name == config.job_name
            and run.trigger == "scheduled"
            and not run.dry_run
            and run.status in DONE_STATUSES
            for run in today_runs
        )
        if not already:
            due.append(config.job_name)
    return due


def _today_runs(db: Session, now: datetime) -> list[ScriptRun]:
    today = now.astimezone(SHANGHAI).date()
    start = datetime.combine(today, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    return list(db.scalars(select(ScriptRun).where(ScriptRun.started_at >= start)).all())


def run_due_jobs(runner: ScriptJobRunner, session_factory: Callable[[], Session], now: datetime) -> list[str]:
    """启动到期的脚本，返回实际启动的脚本名。"""
    with session_factory() as db:
        names = due_jobs(config_service.list_configs(db), _today_runs(db, now), now)
    started: list[str] = []
    for name in names:
        try:
            runner.start(name, trigger="scheduled", dry_run=False)
        except JobBusy:
            logger.info("脚本 %s 已在运行，跳过本次定时启动", name)
            continue
        except ValueError as exc:
            logger.warning("脚本 %s 定时启动被拒绝：%s", name, exc)
            continue
        started.append(name)
    return started


async def script_jobs_loop(
    runner: ScriptJobRunner,
    session_factory: Callable[[], Session],
    base_dir: Path,
    *,
    poll_seconds: float = 2,
    schedule_seconds: float = 60,
) -> None:
    """常驻协程：推进执行器、按时启动、每天清理一次 30 天前的运行目录。单轮出错只记日志。"""
    last_schedule: datetime | None = None
    last_cleanup_date = None
    while True:
        try:
            await asyncio.to_thread(runner.poll)
            now = run_store.now_utc()
            if last_schedule is None or (now - last_schedule).total_seconds() >= schedule_seconds:
                last_schedule = now
                await asyncio.to_thread(run_due_jobs, runner, session_factory, now)
            today = now.astimezone(SHANGHAI).date()
            if last_cleanup_date != today:
                last_cleanup_date = today
                await asyncio.to_thread(cleanup_old_runs, base_dir, now)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 单轮失败不能让调度停下
            logger.exception("脚本调度循环本轮出错")
        await asyncio.sleep(poll_seconds)
