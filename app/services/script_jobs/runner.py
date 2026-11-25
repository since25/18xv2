"""脚本执行器：每次运行一个独立子进程（自成进程组），负责排队、互斥、停止、超时和收尾。

数据库里的运行记录是状态的权威来源；内存里只保存进程句柄和停止期限。
网页接口线程和调度线程都会调用这里，所有公开方法用同一把锁串行化。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
from typing import IO, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.script_runs import ScriptRun
from app.services.script_jobs import config_service, run_store
from app.services.script_jobs.definitions import JobDefinition, RunContext, get_definition
from app.services.script_jobs.logs import LOG_FILE_NAME, run_dir


logger = logging.getLogger(__name__)

STOP_GRACE = timedelta(seconds=30)
INTERRUPTED_REASON = "18x 重启，任务被中断"


class JobBusy(Exception):
    """同一个脚本已有排队或运行中的记录。"""


class RunNotActive(Exception):
    """要停止的运行不在排队或运行中。"""


@dataclass
class _Active:
    proc: Any
    log_handle: IO[bytes]
    ctx: RunContext
    deadline: datetime
    # stopped：用户停止；timeout：超时
    stop_reason: str | None = None
    stop_requested_at: datetime | None = None
    killed: bool = False


class ScriptJobRunner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        base_dir: Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        killpg: Callable[[int, int], None] = os.killpg,
        clock: Callable[[], datetime] | None = None,
        definitions: Callable[[str], JobDefinition] = get_definition,
    ) -> None:
        self._session_factory = session_factory
        self._base_dir = Path(base_dir)
        self._popen = popen
        self._killpg = killpg
        self._clock = clock or (lambda: run_store.now_utc())
        self._definitions = definitions
        self._active: dict[int, _Active] = {}
        self._lock = threading.RLock()

    # ── 公开方法 ──────────────────────────────────────────────

    def start(self, job_name: str, *, trigger: str, dry_run: bool) -> int:
        """创建一次运行：同组有任务在跑就排队，否则立即启动。返回运行 ID。"""
        definition = self._definitions(job_name)
        if not definition.runnable:
            raise ValueError("该脚本尚未支持在 18x 执行")
        with self._lock, self._session_factory() as db:
            config = config_service.get_config(db, job_name)
            if config.executor != "18x" and not dry_run:
                raise ValueError("由 Unraid 运行的脚本只能演练")
            if self._active_runs(db, [job_name]):
                raise JobBusy(job_name)
            group_busy = bool(self._active_runs(db, self._group_members(definition.group)))
            run = run_store.create_run(
                db, job_name=job_name, trigger=trigger, dry_run=dry_run, status="queued" if group_busy else "running"
            )
            if not group_busy:
                self._spawn(db, run, definition)
            return run.id

    def stop(self, run_id: int) -> None:
        """停止一次运行：排队中的直接取消；运行中的先 SIGTERM，30 秒后仍在就 SIGKILL。"""
        with self._lock, self._session_factory() as db:
            run = db.get(ScriptRun, run_id)
            if run is None or run.status not in run_store.ACTIVE_STATUSES:
                raise RunNotActive(run_id)
            if run.status == "queued":
                run_store.finish_run(db, run, exit_code=None, status="stopped", counts={}, items=[], error_reason=None)
                return
            active = self._active.get(run_id)
            if active is None:
                raise RunNotActive(run_id)
            if active.stop_reason is None:
                active.stop_reason = "stopped"
                active.stop_requested_at = self._clock()
                self._signal(active.proc.pid, signal.SIGTERM)

    def poll(self) -> None:
        """回收结束的进程、处理超时和强杀、启动排队中的任务。由调度协程每 2 秒调用。"""
        with self._lock:
            now = self._clock()
            for run_id, active in list(self._active.items()):
                exit_code = active.proc.poll()
                if exit_code is not None:
                    self._finish(run_id, active, exit_code)
                    continue
                if active.stop_reason is None and now >= active.deadline:
                    active.stop_reason = "timeout"
                    active.stop_requested_at = now
                    self._signal(active.proc.pid, signal.SIGTERM)
                elif (
                    active.stop_requested_at is not None
                    and not active.killed
                    and now - active.stop_requested_at >= STOP_GRACE
                ):
                    active.killed = True
                    self._signal(active.proc.pid, signal.SIGKILL)
            self._start_queued()

    def recover_on_startup(self) -> int:
        """18x 启动时调用：结束上次残留的进程组，把排队/运行中的记录标为中断。"""
        with self._lock, self._session_factory() as db:
            runs = list(db.scalars(select(ScriptRun).where(ScriptRun.status.in_(run_store.ACTIVE_STATUSES))).all())
            for run in runs:
                counts: dict = {}
                items: list[dict] = []
                if run.status == "running":
                    if run.pid:
                        self._signal(run.pid, signal.SIGTERM)
                    if run.log_path:
                        ctx = RunContext(
                            run_id=run.id,
                            job_name=run.script_name,
                            params={},
                            dry_run=bool(run.dry_run),
                            run_dir=Path(run.log_path).parent,
                        )
                        counts, items = self._salvage(db, run.script_name, ctx)
                        run = db.get(ScriptRun, run.id)
                run_store.finish_run(
                    db,
                    run,
                    exit_code=None,
                    status="interrupted",
                    counts=counts,
                    items=items,
                    error_reason=INTERRUPTED_REASON,
                )
            return len(runs)

    # ── 内部 ──────────────────────────────────────────────────

    def _group_members(self, group: str) -> list[str]:
        from app.services.script_jobs.definitions import JOB_NAMES

        members = []
        for name in JOB_NAMES:
            try:
                if self._definitions(name).group == group:
                    members.append(name)
            except KeyError:
                continue
        return members

    @staticmethod
    def _active_runs(db: Session, job_names: list[str]) -> list[ScriptRun]:
        if not job_names:
            return []
        return list(
            db.scalars(
                select(ScriptRun)
                .where(ScriptRun.script_name.in_(job_names), ScriptRun.status.in_(run_store.ACTIVE_STATUSES))
                .order_by(ScriptRun.started_at.asc(), ScriptRun.id.asc())
            ).all()
        )

    def _salvage(self, db: Session, job_name: str, ctx: RunContext) -> tuple[dict, list[dict]]:
        """被打断的运行：找回已经做完的部分。失败只记日志，返回空结果。"""
        try:
            definition = self._definitions(job_name)
            if definition.salvage is None:
                return {}, []
            outcome = definition.salvage(db, ctx)
            return outcome.counts, outcome.items
        except Exception:
            logger.exception("脚本 %s 部分结果找回失败（运行 %s）", job_name, ctx.run_id)
            db.rollback()
            return {}, []

    def _signal(self, pid: int, sig: int) -> None:
        try:
            self._killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _spawn(self, db: Session, run: ScriptRun, definition: JobDefinition) -> None:
        config = config_service.get_config(db, run.script_name)
        directory = run_dir(self._base_dir, run.script_name, run.id)
        ctx = RunContext(
            run_id=run.id,
            job_name=run.script_name,
            params=dict(config.params),
            dry_run=bool(run.dry_run),
            run_dir=directory,
        )
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if definition.prepare is None:
                raise RuntimeError("脚本没有启动方式")
            prepared = definition.prepare(db, ctx)
            log_path = directory / LOG_FILE_NAME
            log_handle = log_path.open("ab")
            try:
                proc = self._popen(
                    prepared.argv,
                    env=prepared.env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    cwd=str(directory),
                )
            except Exception:
                log_handle.close()
                raise
        except Exception:
            logger.exception("脚本 %s 启动失败（运行 %s）", run.script_name, run.id)
            run_store.finish_run(db, run, exit_code=None, status="failed", counts={}, items=[], error_reason="启动失败")
            return

        now = self._clock()
        run.status = "running"
        run.started_at = now
        run.pid = proc.pid
        run.log_path = str(log_path)
        db.add(run)
        db.commit()
        self._active[run.id] = _Active(
            proc=proc,
            log_handle=log_handle,
            ctx=ctx,
            deadline=now + timedelta(seconds=definition.timeout_seconds),
        )

    def _finish(self, run_id: int, active: _Active, exit_code: int) -> None:
        self._active.pop(run_id, None)
        try:
            active.log_handle.close()
        except OSError:
            pass
        with self._session_factory() as db:
            run = db.get(ScriptRun, run_id)
            if run is None:
                return
            definition = self._definitions(run.script_name)
            if active.stop_reason in ("stopped", "timeout"):
                counts, items = self._salvage(db, run.script_name, active.ctx)
                run = db.get(ScriptRun, run_id)
                if active.stop_reason == "stopped":
                    status, reason = "stopped", None
                else:
                    status, reason = "failed", f"超过运行时限（{definition.timeout_seconds // 60} 分钟）"
                run_store.finish_run(
                    db, run, exit_code=exit_code, status=status, counts=counts, items=items, error_reason=reason
                )
                return
            try:
                if definition.finalize is None:
                    raise RuntimeError("脚本没有结果整理方式")
                outcome = definition.finalize(db, active.ctx, exit_code)
            except Exception:
                logger.exception("脚本 %s 结果整理失败（运行 %s）", run.script_name, run_id)
                db.rollback()
                run = db.get(ScriptRun, run_id)
                run_store.finish_run(db, run, exit_code=exit_code, status="failed", counts={}, items=[],
                                     error_reason="结果整理失败")
                return
            run_store.finish_run(
                db,
                run,
                exit_code=exit_code,
                status=outcome.status,
                counts=outcome.counts,
                items=outcome.items,
                error_reason=outcome.error_reason,
            )

    def _start_queued(self) -> None:
        with self._session_factory() as db:
            queued = list(
                db.scalars(
                    select(ScriptRun)
                    .where(ScriptRun.status == "queued")
                    .order_by(ScriptRun.started_at.asc(), ScriptRun.id.asc())
                ).all()
            )
            for run in queued:
                try:
                    definition = self._definitions(run.script_name)
                except KeyError:
                    continue
                running = [
                    other
                    for other in self._active_runs(db, self._group_members(definition.group))
                    if other.status == "running"
                ]
                if not running:
                    self._spawn(db, run, definition)
