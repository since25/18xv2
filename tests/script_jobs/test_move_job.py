"""MOVE 脚本真实运行（bash 子进程 + 临时目录 + 假 chown），规则与 Unraid 原脚本一致。"""

from __future__ import annotations

from pathlib import Path
import subprocess

from app.services.script_jobs.media_output import parse_move_ssd_cache_output
from app.services.script_jobs.media_task import MOVE_SCRIPT

from tests.script_jobs.media_helpers import env_with, fake_bin, snapshot, write


ODD_NAME = "新片 带 空格'和$符号.mp4"


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    write(src / ODD_NAME, "new")
    write(src / "合并目录" / "新的.mp4", "inner")
    write(dst / "合并目录" / "旧的.mp4", "old")
    write(src / "重复.mp4", "same")
    write(dst / "重复.mp4", "same")
    write(src / "a.mp4", "longer content")
    write(dst / "a.mp4", "short")
    (src / "冲突").mkdir(parents=True)
    write(src / "冲突" / "里面.mp4")
    write(dst / "冲突", "file")
    return src, dst


def _run(tmp_path: Path, src: Path, dst: Path, *extra: str) -> subprocess.CompletedProcess:
    bin_dir, _ = fake_bin(tmp_path)
    return subprocess.run(
        ["bash", str(MOVE_SCRIPT), *extra],
        env=env_with(bin_dir, MOVE_SOURCE_DIR=str(src), MOVE_TARGET_DIR=str(dst)),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_move_real_run_matches_original_rules(tmp_path):
    src, dst = _tree(tmp_path)
    proc = _run(tmp_path, src, dst)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (dst / ODD_NAME).read_text(encoding="utf-8") == "new"
    assert (dst / "合并目录" / "新的.mp4").is_file()
    assert (dst / "合并目录" / "旧的.mp4").is_file()
    assert not (src / "合并目录").exists()
    assert not (src / "重复.mp4").exists()
    assert (dst / "a.mp4").read_text(encoding="utf-8") == "short"
    assert (dst / "a_新版本.mp4").read_text(encoding="utf-8") == "longer content"
    assert (src / "冲突" / "里面.mp4").is_file()

    counts = parse_move_ssd_cache_output(proc.stdout).counts
    assert counts["moved"] == 3
    assert counts["duplicates_removed"] == 1
    assert counts["skipped"] == 1
    assert counts["failed"] == 0
    calls = (tmp_path / "chown_calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls == [f"-R 99:100 {dst}"]


def test_move_dry_run_changes_nothing(tmp_path):
    src, dst = _tree(tmp_path)
    before = (snapshot(src), snapshot(dst))
    proc = _run(tmp_path, src, dst, "--dry-run")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (snapshot(src), snapshot(dst)) == before
    assert not (tmp_path / "chown_calls.txt").exists()
    assert parse_move_ssd_cache_output(proc.stdout).counts["moved"] == 3


def test_move_script_has_no_named_owner_or_report_hook():
    text = MOVE_SCRIPT.read_text(encoding="utf-8")
    assert "chown -R nobody" not in text
    assert "report_script_run" not in text
    assert "chown -R 99:100" in text
