from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os

from app.services.script_jobs.logs import cleanup_old_runs, read_log, run_dir


def test_read_log_never_splits_multibyte(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes("第一行\n第二".encode())
    text, offset = read_log(path, 0, finished=False)
    assert text == "第一行\n"
    assert offset == len("第一行\n".encode())
    rest, end = read_log(path, offset, finished=True)
    assert rest == "第二"
    assert end == path.stat().st_size


def test_read_log_limit_cut_inside_char_backs_off(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes("啊啊\n".encode())
    text, offset = read_log(path, 0, limit=4, finished=True)
    assert text == "啊"
    assert offset == 3
    rest, _ = read_log(path, offset, limit=4, finished=True)
    assert rest == "啊\n"


def test_read_log_unfinished_without_newline_waits(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes("还没写完".encode())
    assert read_log(path, 0, finished=False) == ("", 0)


def test_read_log_offset_at_end_returns_empty(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes(b"abc\n")
    assert read_log(path, 4, finished=True) == ("", 4)


def test_run_dir_layout(tmp_path):
    assert run_dir(tmp_path, "sehuatang", 12) == tmp_path / "sehuatang" / "12"


def test_cleanup_old_runs_removes_only_older_than_30_days(tmp_path):
    now = datetime(2026, 11, 25, tzinfo=UTC)
    old = run_dir(tmp_path, "sehuatang", 1)
    new = run_dir(tmp_path, "sehuatang", 2)
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "output.log").write_text("x")
    old_ts = (now - timedelta(days=31)).timestamp()
    os.utime(old, (old_ts, old_ts))
    new_ts = (now - timedelta(days=29)).timestamp()
    os.utime(new, (new_ts, new_ts))

    assert cleanup_old_runs(tmp_path, now) == 1
    assert not old.exists()
    assert new.exists()
