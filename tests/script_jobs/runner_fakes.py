"""执行器测试用的假进程、假时钟和假任务定义。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import signal

from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from app.models.script_runs import ScriptJobConfig
from app.services.script_jobs.config_service import ensure_default_configs
from app.services.script_jobs.definitions import JobDefinition, PreparedCommand, RunOutcome
from app.services.script_jobs.runner import ScriptJobRunner


class EmptyParams(BaseModel):
    pass


class FakeProc:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class FakePopen:
    """记录每次启动；返回可手动设置退出码的假进程。"""

    def __init__(self):
        self.procs: list[FakeProc] = []
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        proc = FakeProc(pid=1000 + len(self.procs))
        self.procs.append(proc)
        self.calls.append({"argv": argv, **kwargs})
        return proc


class FakeKillpg:
    def __init__(self, popen: FakePopen | None = None, *, missing: bool = False):
        self.calls: list[tuple[int, int]] = []
        self.popen = popen
        self.missing = missing

    def __call__(self, pid: int, sig: int) -> None:
        self.calls.append((pid, sig))
        if self.missing:
            raise ProcessLookupError(pid)
        if self.popen is not None and sig == signal.SIGKILL:
            for proc in self.popen.procs:
                if proc.pid == pid:
                    proc.returncode = -9


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 11, 25, 5, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def make_definition(name: str, group: str, *, timeout: int = 600, finalize=None, salvage=None) -> JobDefinition:
    def prepare(db, ctx):
        return PreparedCommand(argv=["fake", ctx.job_name], env={"X": "1"})

    def default_finalize(db, ctx, exit_code):
        return RunOutcome(status="success" if exit_code == 0 else "failed", counts={"submitted": 1}, items=[],
                          error_reason=None)

    return JobDefinition(
        name=name,
        label=name,
        group=group,
        timeout_seconds=timeout,
        runnable=True,
        params_model=EmptyParams,
        default_run_time="01:00",
        default_params={},
        prepare=prepare,
        finalize=finalize or default_finalize,
        salvage=salvage,
    )


def build_runner(db_session, tmp_path, *, definitions: dict[str, JobDefinition], executor: str = "18x",
                 killpg_missing: bool = False):
    """用测试库建执行器；三条配置的执行方统一设成 executor。"""
    ensure_default_configs(db_session)
    for config in db_session.query(ScriptJobConfig).all():
        config.executor = executor
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    popen = FakePopen()
    killpg = FakeKillpg(popen, missing=killpg_missing)
    clock = FakeClock()
    runner = ScriptJobRunner(
        factory,
        tmp_path,
        popen=popen,
        killpg=killpg,
        clock=clock,
        definitions=definitions.__getitem__,
    )
    return runner, popen, killpg, clock
