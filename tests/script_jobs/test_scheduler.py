from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.script_runs import ScriptJobConfig, ScriptRun
from app.services.script_jobs.scheduler import due_jobs, run_due_jobs


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, 25, hour, minute, second, tzinfo=SHANGHAI).astimezone(UTC)


def _config(*, executor="18x", enabled=True, run_time="01:28") -> ScriptJobConfig:
    return ScriptJobConfig(job_name="sehuatang", executor=executor, enabled=enabled, run_time=run_time, params={})


def _run(*, status="success", trigger="scheduled", dry_run=False) -> ScriptRun:
    return ScriptRun(
        run_key="k",
        script_name="sehuatang",
        started_at=_at(1, 28),
        status=status,
        counts={},
        trigger=trigger,
        dry_run=dry_run,
    )


def test_due_at_run_time():
    assert due_jobs([_config()], [], _at(1, 28)) == ["sehuatang"]


def test_not_due_before_run_time():
    assert due_jobs([_config()], [], _at(1, 27, 59)) == []


def test_catch_up_within_two_hours():
    assert due_jobs([_config()], [], _at(3, 27)) == ["sehuatang"]


def test_no_catch_up_after_two_hours():
    assert due_jobs([_config()], [], _at(3, 28)) == []


def test_interrupted_run_allows_rerun():
    assert due_jobs([_config()], [_run(status="interrupted")], _at(1, 40)) == ["sehuatang"]


@pytest.mark.parametrize("status", ["queued", "running", "success", "warning", "failed", "stopped"])
def test_finished_or_active_scheduled_run_blocks_rerun(status):
    assert due_jobs([_config()], [_run(status=status)], _at(1, 40)) == []


def test_manual_real_run_does_not_block_schedule():
    assert due_jobs([_config()], [_run(trigger="manual")], _at(1, 40)) == ["sehuatang"]


def test_dry_run_does_not_block_schedule():
    assert due_jobs([_config()], [_run(dry_run=True)], _at(1, 40)) == ["sehuatang"]


@pytest.mark.parametrize("config", [_config(executor="unraid"), _config(enabled=False)])
def test_unraid_executor_or_disabled_never_due(config):
    assert due_jobs([config], [], _at(1, 28)) == []


def test_config_changed_after_todays_run_time_does_not_catch_up():
    # 01:40 刚切到 18x（Unraid 今天可能已经跑过），当天不补跑
    config = _config()
    config.updated_at = _at(1, 40)
    assert due_jobs([config], [], _at(1, 45)) == []


def test_config_changed_before_run_time_still_runs():
    config = _config()
    config.updated_at = _at(1, 0)
    assert due_jobs([config], [], _at(1, 28)) == ["sehuatang"]


def test_config_changed_yesterday_still_catches_up():
    config = _config()
    config.updated_at = _at(23, 0) - timedelta(days=1)
    assert due_jobs([config], [], _at(2, 0)) == ["sehuatang"]


def test_config_updated_at_naive_is_treated_as_utc():
    config = _config()
    config.updated_at = _at(1, 40).replace(tzinfo=None)
    assert due_jobs([config], [], _at(1, 45)) == []


class _RecordingRunner:
    def __init__(self):
        self.started: list[tuple[str, str, bool]] = []

    def start(self, job_name, *, trigger, dry_run):
        self.started.append((job_name, trigger, dry_run))
        return 1


def test_run_due_jobs_starts_scheduled_real_runs(db_session):
    from sqlalchemy.orm import sessionmaker

    from app.services.script_jobs.config_service import ensure_default_configs, get_config

    ensure_default_configs(db_session)
    config = get_config(db_session, "sehuatang")
    config.executor = "18x"
    config.enabled = True
    # 配置是昨天改的；今天预定时间之后才改的配置当天不补跑（见上面的用例）
    config.updated_at = _at(1, 0) - timedelta(days=1)
    db_session.commit()
    # 今天已有一条前一天的旧记录不影响
    db_session.add(
        ScriptRun(
            run_key="yesterday",
            script_name="sehuatang",
            started_at=_at(1, 28) - timedelta(days=1),
            status="success",
            counts={},
            trigger="scheduled",
        )
    )
    db_session.commit()
    runner = _RecordingRunner()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    assert run_due_jobs(runner, factory, _at(1, 30)) == ["sehuatang"]
    assert runner.started == [("sehuatang", "scheduled", False)]
