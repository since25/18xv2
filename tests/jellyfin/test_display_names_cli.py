from __future__ import annotations

from contextlib import nullcontext
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.background_jobs import BackgroundJob
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin.job_runner import JOB_NAMES


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "jellyfin_display_names.py"


@pytest.fixture
def cli(db_session, monkeypatch):
    """按文件路径加载命令行脚本，数据库会话换成测试库。"""
    spec = importlib.util.spec_from_file_location("jellyfin_display_names_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr("sys.argv", ["jellyfin_display_names.py"])
    return module


def _names_job(db_session) -> BackgroundJob:
    return db_session.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_NAMES)).one()


def test_interrupt_marks_job_failed_so_later_runs_are_not_blocked(cli, db_session, monkeypatch):
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_names_job", interrupted)

    assert cli.main() == 130

    job = _names_job(db_session)
    assert job.done is True
    assert job.stage == "失败"
    assert "中断" in (job.error or "")


def test_partial_failures_return_nonzero(cli, db_session, monkeypatch):
    def finished_with_failures(job_id, **_kwargs):
        BackgroundJobService.update(db_session, job_id, stage="完成", done=True, summary={"updated": 3, "failed": 2})

    monkeypatch.setattr(cli, "run_names_job", finished_with_failures)

    assert cli.main() == 1


def test_clean_run_returns_zero(cli, db_session, monkeypatch):
    def finished(job_id, **_kwargs):
        BackgroundJobService.update(db_session, job_id, stage="完成", done=True, summary={"updated": 3, "failed": 0})

    monkeypatch.setattr(cli, "run_names_job", finished)

    assert cli.main() == 0
