from __future__ import annotations

from pathlib import Path

from app.services.script_jobs import media_task
from app.services.script_jobs.definitions import RunContext, get_definition
from app.services.script_jobs.logs import LOG_FILE_NAME


MOVE_PARAMS = {"source_dir": "/mnt/cache/docker1/SSD_cache/已整理", "target_dir": "/mnt/disk2/qbbtdn/已整理"}
SUMMARY_OK = "完成: 移动 2 个, 删除重复 1 个, 跳过 0 个, 失败 0 个"
SUMMARY_FAILED = "完成: 移动 2 个, 删除重复 0 个, 跳过 0 个, 失败 1 个"


def _ctx(tmp_path: Path, *, job_name="MOVE_SSD_CACHE_TO_DISK2", dry_run=False, params=None, log: str | None = None):
    directory = tmp_path / job_name / "7"
    directory.mkdir(parents=True, exist_ok=True)
    if log is not None:
        (directory / LOG_FILE_NAME).write_text(log, encoding="utf-8")
    return RunContext(run_id=7, job_name=job_name, params=params or MOVE_PARAMS, dry_run=dry_run, run_dir=directory)


def test_move_prepare_runs_repo_script_with_dirs_in_env(tmp_path):
    real = media_task.move_prepare(None, _ctx(tmp_path))
    assert real.argv == ["bash", str(media_task.MOVE_SCRIPT)]
    assert real.env["MOVE_SOURCE_DIR"] == MOVE_PARAMS["source_dir"]
    assert real.env["MOVE_TARGET_DIR"] == MOVE_PARAMS["target_dir"]
    assert media_task.MOVE_SCRIPT.is_file()

    dry = media_task.move_prepare(None, _ctx(tmp_path, dry_run=True))
    assert dry.argv == ["bash", str(media_task.MOVE_SCRIPT), "--dry-run"]


def test_move_finalize_status_from_summary(tmp_path):
    ok = media_task.media_finalize(None, _ctx(tmp_path, log=f"移动: a\n{SUMMARY_OK}\n"), 0)
    assert ok.status == "success"
    assert ok.counts["moved"] == 2
    assert ok.error_reason is None

    failed = media_task.media_finalize(None, _ctx(tmp_path, log=f"{SUMMARY_FAILED}\n"), 0)
    assert failed.status == "failed"

    no_summary = media_task.media_finalize(None, _ctx(tmp_path, log="移动: a\n"), 0)
    assert no_summary.status == "failed"


def test_finalize_nonzero_exit_has_reason(tmp_path):
    outcome = media_task.media_finalize(None, _ctx(tmp_path, log="错误: 源目录不存在: /x\n"), 1)
    assert outcome.status == "failed"
    assert outcome.error_reason == "运行异常退出（退出码 1）"


def test_finalize_missing_log_is_failed(tmp_path):
    outcome = media_task.media_finalize(None, _ctx(tmp_path), 0)
    assert outcome.status == "failed"


def test_move_salvage_does_not_invent_failure(tmp_path):
    outcome = media_task.media_salvage(None, _ctx(tmp_path, log="开始移动\n移动: a\n移动: b\n"))
    assert outcome.counts.get("failed", 0) == 0


def test_move_definition_is_runnable_with_hooks():
    definition = get_definition("MOVE_SSD_CACHE_TO_DISK2")
    assert definition.runnable is True
    assert definition.prepare is not None
    assert definition.finalize is not None
    assert definition.salvage is not None


def test_move_salvage_counts_work_done_before_stop(tmp_path):
    log = "\n".join(
        [
            "开始移动: /src -> /dst",
            "移动: 甲.mp4",
            "合并目录: 乙",
            "移动: 乙/内层.mp4",
            "删除重复(目标已有相同文件, 5 字节): 丙.mp4",
            "大小不同(5 vs 9),另存为新版本: 丁_新版本.mp4",
            "移动: 戊.mp4",
            "  移动失败: 戊.mp4",
        ]
    )
    outcome = media_task.media_salvage(None, _ctx(tmp_path, log=log))
    # 失败那次也先打印了“移动:”，按原脚本计数规则不算移动成功
    assert outcome.counts["moved"] == 3
    assert outcome.counts["duplicates_removed"] == 1
    assert outcome.counts["failed"] == 1
