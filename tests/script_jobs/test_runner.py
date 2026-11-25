from __future__ import annotations

import signal

import pytest
from sqlalchemy import select

from app.models.script_runs import ScriptRun
from app.services.script_jobs.runner import JobBusy, RunNotActive

from tests.script_jobs.runner_fakes import build_runner, make_definition


MOVE = "MOVE_SSD_CACHE_TO_DISK2"
DEL = "DEL_SOMETHING"


def _defs(**overrides):
    defs = {
        "sehuatang": make_definition("sehuatang", "sehuatang"),
        MOVE: make_definition(MOVE, "media"),
        DEL: make_definition(DEL, "media"),
    }
    defs.update(overrides)
    return defs


def _run(db_session, run_id) -> ScriptRun:
    db_session.expire_all()
    return db_session.scalar(select(ScriptRun).where(ScriptRun.id == run_id))


def test_start_spawns_in_new_session_and_records_pid_and_log(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    run = _run(db_session, run_id)
    assert run.status == "running"
    assert run.pid == popen.procs[0].pid
    assert run.log_path.endswith(f"sehuatang/{run_id}/output.log")
    assert popen.calls[0]["start_new_session"] is True
    assert popen.calls[0]["argv"] == ["fake", "sehuatang"]


def test_second_start_same_job_raises_busy(db_session, tmp_path):
    runner, _, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    runner.start("sehuatang", trigger="manual", dry_run=False)
    with pytest.raises(JobBusy):
        runner.start("sehuatang", trigger="manual", dry_run=True)


def test_finished_process_is_finalized(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    run_id = runner.start("sehuatang", trigger="scheduled", dry_run=False)
    popen.procs[0].returncode = 0
    runner.poll()
    run = _run(db_session, run_id)
    assert run.status == "success"
    assert run.exit_code == 0
    assert run.counts["submitted"] == 1
    assert run.finished_at is not None


def test_media_group_queues_second_job_and_starts_after_first_finishes(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    first = runner.start(MOVE, trigger="manual", dry_run=False)
    second = runner.start(DEL, trigger="manual", dry_run=False)
    assert _run(db_session, second).status == "queued"
    assert len(popen.procs) == 1

    popen.procs[0].returncode = 0
    runner.poll()
    assert _run(db_session, first).status == "success"
    assert _run(db_session, second).status == "running"
    assert len(popen.procs) == 2


def test_other_group_runs_in_parallel(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    runner.start(MOVE, trigger="manual", dry_run=False)
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    assert _run(db_session, run_id).status == "running"
    assert len(popen.procs) == 2


def test_stop_running_sends_sigterm_then_sigkill_after_30s(db_session, tmp_path):
    runner, popen, killpg, clock = build_runner(db_session, tmp_path, definitions=_defs())
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    pid = popen.procs[0].pid
    runner.stop(run_id)
    assert killpg.calls == [(pid, signal.SIGTERM)]

    clock.advance(29)
    runner.poll()
    assert killpg.calls == [(pid, signal.SIGTERM)]

    clock.advance(2)
    runner.poll()
    assert (pid, signal.SIGKILL) in killpg.calls

    runner.poll()
    run = _run(db_session, run_id)
    assert run.status == "stopped"
    assert run.finished_at is not None


def test_stop_queued_marks_stopped_without_spawning(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    runner.start(MOVE, trigger="manual", dry_run=False)
    queued = runner.start(DEL, trigger="manual", dry_run=False)
    runner.stop(queued)
    assert _run(db_session, queued).status == "stopped"
    popen.procs[0].returncode = 0
    runner.poll()
    assert len(popen.procs) == 1


def test_stop_finished_run_raises(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    popen.procs[0].returncode = 0
    runner.poll()
    with pytest.raises(RunNotActive):
        runner.stop(run_id)


def test_timeout_marks_failed_with_reason(db_session, tmp_path):
    defs = _defs(sehuatang=make_definition("sehuatang", "sehuatang", timeout=120))
    runner, popen, killpg, clock = build_runner(db_session, tmp_path, definitions=defs)
    run_id = runner.start("sehuatang", trigger="scheduled", dry_run=False)
    clock.advance(121)
    runner.poll()
    assert killpg.calls[0] == (popen.procs[0].pid, signal.SIGTERM)
    popen.procs[0].returncode = -15
    runner.poll()
    run = _run(db_session, run_id)
    assert run.status == "failed"
    assert run.error_reason == "超过运行时限（2 分钟）"


def test_finalize_exception_marks_failed(db_session, tmp_path):
    def broken(db, ctx, exit_code):
        raise RuntimeError("boom")

    defs = _defs(sehuatang=make_definition("sehuatang", "sehuatang", finalize=broken))
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=defs)
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    popen.procs[0].returncode = 0
    runner.poll()
    run = _run(db_session, run_id)
    assert run.status == "failed"
    assert run.error_reason == "结果整理失败"


def test_unraid_executor_rejects_real_run_allows_dry_run(db_session, tmp_path):
    runner, _, _, _ = build_runner(db_session, tmp_path, definitions=_defs(), executor="unraid")
    with pytest.raises(ValueError, match="只能演练"):
        runner.start("sehuatang", trigger="manual", dry_run=False)
    run_id = runner.start("sehuatang", trigger="manual", dry_run=True)
    assert _run(db_session, run_id).dry_run is True


def test_unrunnable_job_rejected(db_session, tmp_path):
    from dataclasses import replace

    defs = _defs()
    defs[MOVE] = replace(defs[MOVE], runnable=False)
    runner, _, _, _ = build_runner(db_session, tmp_path, definitions=defs)
    with pytest.raises(ValueError, match="尚未支持"):
        runner.start(MOVE, trigger="manual", dry_run=True)


def test_recover_on_startup_kills_process_group_then_marks_interrupted(db_session, tmp_path):
    runner, popen, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    running = runner.start(MOVE, trigger="scheduled", dry_run=False)
    queued = runner.start(DEL, trigger="manual", dry_run=False)
    pid = popen.procs[0].pid

    # 模拟 18x 重启：新的执行器实例，内存状态清空
    fresh, _, killpg, _ = build_runner(db_session, tmp_path, definitions=_defs())
    assert fresh.recover_on_startup() == 2
    assert (pid, signal.SIGTERM) in killpg.calls
    for run_id in (running, queued):
        run = _run(db_session, run_id)
        assert run.status == "interrupted"
        assert run.error_reason == "18x 重启，任务被中断"
        assert run.finished_at is not None


def test_recover_ignores_already_dead_process(db_session, tmp_path):
    runner, _, _, _ = build_runner(db_session, tmp_path, definitions=_defs())
    run_id = runner.start("sehuatang", trigger="manual", dry_run=False)
    fresh, _, _, _ = build_runner(db_session, tmp_path, definitions=_defs(), killpg_missing=True)
    assert fresh.recover_on_startup() == 1
    assert _run(db_session, run_id).status == "interrupted"
