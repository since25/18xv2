"""DEL 编排真实运行（Python 子进程 + 原两个脚本 + 临时目录 + 假 chown），顺序与 Unraid 原 bash 外壳一致。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.script_jobs import del_main, media_task
from app.services.script_jobs.definitions import RunContext, get_definition
from app.services.script_jobs.logs import LOG_FILE_NAME
from app.services.script_jobs.media_output import parse_del_dry_run, parse_output

from tests.script_jobs.media_helpers import env_with, fake_bin, snapshot, write


GOOD_DIR = "示例好词 带 空格'和$"


def _keywords(words: list[str], *, keyword_type: str) -> dict:
    entries = [
        {
            "id": index,
            "canonical_name": word,
            "canonical_name_normalized": word,
            "keyword_type": keyword_type,
            "status": "active",
            "merge_policy": "normal",
            "note": None,
            "aliases": [],
        }
        for index, word in enumerate(words, 1)
    ]
    return {"total": len(entries), "entries": entries}


def _setup(tmp_path: Path, *, dry_run=False, blacklist=("示例坏词",), fix_permissions=True) -> tuple[Path, Path, Path]:
    scan = tmp_path / "media" / "finish"
    target = tmp_path / "media" / "已整理"
    write(scan / "示例坏词 合集" / "a.mp4")
    write(scan / GOOD_DIR / "b.mp4")
    write(scan / "无关目录" / "c.mp4")
    target.mkdir(parents=True)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / del_main.TARGET_DIRS_FILE).write_text(f"{scan}\n{tmp_path / '不存在'}\n", encoding="utf-8")
    (run_dir / del_main.BLACKLIST_FILE).write_text(
        json.dumps(_keywords(list(blacklist), keyword_type="blacklist"), ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / del_main.WHITELIST_FILE).write_text(
        json.dumps(_keywords(["示例好词"], keyword_type="whitelist"), ensure_ascii=False), encoding="utf-8"
    )
    payload = {
        "dry_run": dry_run,
        "organize_jobs": [
            {"scan_root": str(scan), "target_root": str(target)},
            {"scan_root": str(tmp_path / "media" / "不存在的扫描目录"), "target_root": str(target)},
        ],
        "merge_on_conflict": True,
        "fix_permissions": fix_permissions,
        "scripts_dir": str(media_task.JOBS_DIR / "del_something"),
        "run_dir": str(run_dir),
    }
    (run_dir / "input.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return scan, target, run_dir


def _run(tmp_path: Path, run_dir: Path) -> subprocess.CompletedProcess:
    bin_dir, _ = fake_bin(tmp_path)
    return subprocess.run(
        [sys.executable, "-m", "app.services.script_jobs.del_main", "--input", str(run_dir / "input.json")],
        env=env_with(bin_dir, PYTHONPATH=str(media_task.PROJECT_ROOT), PYTHONUNBUFFERED="1"),
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_del_real_run_deletes_then_organizes_then_fixes_permissions(tmp_path):
    scan, target, run_dir = _setup(tmp_path)
    proc = _run(tmp_path, run_dir)
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, output
    assert not (scan / "示例坏词 合集").exists()
    assert (target / "示例好词" / GOOD_DIR / "b.mp4").is_file()
    assert (scan / "无关目录" / "c.mp4").is_file()
    assert "[SKIP] 扫描根不存在, 跳过:" in output
    calls = (tmp_path / "chown_calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls == [f"-R 99:100 {target}"]
    assert (run_dir / "delete_log.txt").is_file()

    counts = parse_output("DEL_SOMETHING", proc.stdout).counts
    assert counts["deleted_dirs"] == 1
    assert counts["moved_new"] == 1
    assert counts["errors"] == 0


def test_del_dry_run_changes_nothing_and_lists_plan(tmp_path):
    _scan, _target, run_dir = _setup(tmp_path, dry_run=True)
    media = tmp_path / "media"
    before = snapshot(media)
    proc = _run(tmp_path, run_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert snapshot(media) == before
    assert not (tmp_path / "chown_calls.txt").exists()
    assert "[INFO] 演练模式，跳过修正权限" in proc.stdout
    result = parse_del_dry_run(proc.stdout)
    plan = [item for item in result.items if item["message"] == "演练"]
    assert [item["kind"] for item in plan] == ["deleted_dir", "moved_new"]


def test_del_without_permission_fix_skips_chown(tmp_path):
    _scan, _target, run_dir = _setup(tmp_path, fix_permissions=False)
    proc = _run(tmp_path, run_dir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (tmp_path / "chown_calls.txt").exists()


def test_del_empty_blacklist_fails_before_organize(tmp_path):
    scan, _target, run_dir = _setup(tmp_path, blacklist=())
    proc = _run(tmp_path, run_dir)

    assert proc.returncode == 1
    assert "[INFO] Organizing" not in proc.stdout
    assert (scan / GOOD_DIR / "b.mp4").is_file()
    assert not (tmp_path / "chown_calls.txt").exists()


def _entry(name, *, keyword_type="blacklist", aliases=()) -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name, canonical_name_normalized=name, keyword_type=keyword_type, status="active"
    )
    entry.aliases = [KeywordAlias(alias=alias, alias_normalized=alias) for alias in aliases]
    return entry


DEL_PARAMS = {
    "delete_dirs": ["/mnt/cache/docker1/SSD_cache", "/mnt/disk2/qbbtdn/已整理"],
    "organize_jobs": [{"scan_root": "/mnt/cache/docker1/SSD_cache/finish", "target_root": "/mnt/cache/docker1/SSD_cache/已整理"}],
    "merge_on_conflict": False,
    "fix_permissions": True,
}


def test_del_prepare_writes_inputs(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("KEYWORDS_API_PASSWORD", "不应传给子进程")
    db_session.add_all([_entry("示例坏词", aliases=("别名甲",)), _entry("示例好词", keyword_type="whitelist")])
    db_session.commit()
    run_dir = tmp_path / "DEL_SOMETHING" / "3"
    run_dir.mkdir(parents=True)
    ctx = RunContext(run_id=3, job_name="DEL_SOMETHING", params=DEL_PARAMS, dry_run=True, run_dir=run_dir)

    prepared = media_task.del_prepare(db_session, ctx)

    assert prepared.argv[1:] == ["-m", "app.services.script_jobs.del_main", "--input", str(run_dir.resolve() / "input.json")]
    assert "KEYWORDS_API_PASSWORD" not in prepared.env
    assert str(media_task.PROJECT_ROOT) in prepared.env["PYTHONPATH"]
    lines = (run_dir / del_main.TARGET_DIRS_FILE).read_text(encoding="utf-8").splitlines()
    assert lines == DEL_PARAMS["delete_dirs"]
    assert json.loads((run_dir / del_main.BLACKLIST_FILE).read_text(encoding="utf-8"))["total"] == 1
    assert json.loads((run_dir / del_main.WHITELIST_FILE).read_text(encoding="utf-8"))["total"] == 1
    payload = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["organize_jobs"] == DEL_PARAMS["organize_jobs"]
    assert payload["merge_on_conflict"] is False
    assert payload["fix_permissions"] is True
    assert payload["scripts_dir"] == str(media_task.JOBS_DIR / "del_something")
    assert payload["run_dir"] == str(run_dir.resolve())


def test_del_stop_salvages_partial_deletions(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / LOG_FILE_NAME).write_text(
        "[处理] /data/x\n[DELETED] 已删除目录：/data/x/示例A\n[DELETED] 已删除文件：/data/x/示例B.mp4\n", encoding="utf-8"
    )
    ctx = RunContext(run_id=1, job_name="DEL_SOMETHING", params=DEL_PARAMS, dry_run=False, run_dir=run_dir)
    outcome = media_task.media_salvage(None, ctx)
    assert outcome.counts["deleted_dirs"] == 1
    assert outcome.counts["deleted_files"] == 1
    assert len(outcome.items) == 2


def test_del_definition_is_runnable_with_hooks():
    definition = get_definition("DEL_SOMETHING")
    assert definition.runnable is True
    assert definition.prepare is not None
    assert definition.finalize is not None
    assert definition.salvage is not None


@pytest.mark.parametrize("dry_run", [True, False])
def test_del_finalize_uses_matching_parser(tmp_path, dry_run):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / LOG_FILE_NAME).write_text(
        "[DRY-RUN] 将删除目录：/data/x/示例A\n[DELETED] 已删除目录：/data/x/示例B\n", encoding="utf-8"
    )
    ctx = RunContext(run_id=1, job_name="DEL_SOMETHING", params=DEL_PARAMS, dry_run=dry_run, run_dir=run_dir)
    outcome = media_task.media_finalize(None, ctx, 0)
    # 演练时两行都计（演练行 + 正式行）；正式运行只计正式行
    assert outcome.counts["deleted_dirs"] == (2 if dry_run else 1)
    assert outcome.status == "success"


def test_del_prepare_keeps_comma_in_delete_dir(db_session, tmp_path):
    # 删除目录名里有英文逗号时不能被 csv 拆开，否则会去删别的目录
    import importlib.util

    comma_dir = tmp_path / "media" / "a,b"
    comma_dir.mkdir(parents=True)
    (tmp_path / "media" / "a").mkdir()
    run_dir = tmp_path / "DEL_SOMETHING" / "4"
    run_dir.mkdir(parents=True)
    params = dict(DEL_PARAMS, delete_dirs=[str(comma_dir)])
    media_task.del_prepare(db_session, RunContext(run_id=4, job_name="DEL_SOMETHING", params=params, dry_run=True, run_dir=run_dir))

    spec = importlib.util.spec_from_file_location("del_files_csv_check", media_task.JOBS_DIR / "del_something" / "delete_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.load_target_dirs(str(run_dir / del_main.TARGET_DIRS_FILE)) == [str(comma_dir)]
