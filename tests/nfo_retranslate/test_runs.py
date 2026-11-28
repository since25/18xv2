from __future__ import annotations

from dataclasses import asdict
import json
import os
import re

import pytest

from app.services.nfo_retranslate.runs import (
    LedgerEntry,
    RunDir,
    TranslationRecord,
    append_ledger,
    drop_ledger,
    latest_translations,
    load_ledger,
)


def _rec(group_key: str, field: str = "title", **overrides) -> TranslationRecord:
    """造一条翻译记录；默认是成功的标题记录。"""
    values = {
        "group_key": group_key,
        "field": field,
        "num": "ABC-001",
        "actors": ["三上悠亜", "河北彩花"],
        "source_text": "人妻の秘密",
        "old_text": "人妻的秘密（旧）",
        "new_text": "人妻的秘密",
        "error": None,
        "targets": {"/media/甲/ABC-001/ABC-001.nfo": "a" * 64},
    }
    values.update(overrides)
    return TranslationRecord(**values)


def test_translation_roundtrip_and_done_keys(tmp_path):
    run = RunDir.create(str(tmp_path))

    assert re.fullmatch(r"\d{8}-\d{6}", run.run_id)
    assert run.path == os.path.join(str(tmp_path), run.run_id)
    assert os.path.isdir(run.path)
    assert run.backup_dir == os.path.join(run.path, "backup")
    assert run.report_path == os.path.join(run.path, "report.html")

    first = _rec("甲|ABC-001")
    second = _rec("乙|XYZ-002", "plot", num="XYZ-002", new_text=None, error="假名占比超过 15%，疑似没翻")
    run.append_translation(first)
    run.append_translation(second)

    reopened = RunDir.open(str(tmp_path), run.run_id)
    assert reopened.load_translations() == [first, second]
    assert reopened.done_group_keys() == {"甲|ABC-001", "乙|XYZ-002"}

    # 一条记录一行，中文不转义
    with open(os.path.join(run.path, "translations.jsonl"), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 2
    assert "三上悠亜" in lines[0]


def test_open_missing_run_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RunDir.open(str(tmp_path), "20991231-235959")


def test_load_translations_skips_truncated_line(tmp_path):
    run = RunDir.create(str(tmp_path))
    first = _rec("甲|ABC-001")
    run.append_translation(first)

    # 模拟断电：末尾只写了半行，而且截在一个汉字的多字节中间
    half = json.dumps(asdict(_rec("乙|XYZ-002")), ensure_ascii=False).encode("utf-8")
    cut = half.index("悠".encode("utf-8")) + 1
    with open(os.path.join(run.path, "translations.jsonl"), "ab") as fh:
        fh.write(half[:cut])

    assert run.load_translations() == [first]
    assert run.done_group_keys() == {"甲|ABC-001"}

    # 续跑接着写：新记录不能接在半行后面一起作废
    third = _rec("丙|DEF-003", num="DEF-003")
    run.append_translation(third)
    assert run.load_translations() == [first, third]


def test_apply_log_roundtrip(tmp_path):
    run = RunDir.create(str(tmp_path))
    assert run.load_apply() == []

    written = {"path": "/media/甲/ABC-001/ABC-001.nfo", "fields": ["title", "plot"], "sha256_after": "b" * 64}
    skipped = {"path": "/media/乙/XYZ-002/XYZ-002.nfo", "skipped": "已被改动"}
    run.append_apply(written)
    run.append_apply(skipped)

    assert RunDir.open(str(tmp_path), run.run_id).load_apply() == [written, skipped]


def test_ledger_last_entry_wins_and_drop(tmp_path):
    base = str(tmp_path)
    assert load_ledger(base) == {}
    # 没有记录文件时删除也不报错
    drop_ledger(base, ["/media/甲.nfo"])

    first = LedgerEntry(sha256_after="a" * 64, fields=frozenset({"title"}), model="qwen38")
    second = LedgerEntry(sha256_after="b" * 64, fields=frozenset({"title", "plot"}), model="qwen38")
    other = LedgerEntry(sha256_after="c" * 64, fields=frozenset({"plot"}), model="gemma3")
    append_ledger(base, "/media/甲.nfo", first)
    append_ledger(base, "/media/乙.nfo", other)
    append_ledger(base, "/media/甲.nfo", second)

    assert load_ledger(base) == {"/media/甲.nfo": second, "/media/乙.nfo": other}
    assert os.path.isfile(os.path.join(base, "applied.jsonl"))

    drop_ledger(base, iter(["/media/甲.nfo"]))
    assert load_ledger(base) == {"/media/乙.nfo": other}


def test_latest_translations_last_record_wins():
    first_try = _rec("甲|ABC-001", new_text=None, error="翻译接口请求失败（HTTP 500，已尝试 4 次）")
    plot = _rec("甲|ABC-001", "plot")
    other = _rec("乙|XYZ-002", num="XYZ-002")
    # 续跑补翻：同一部片同一字段的后一条覆盖前一条，位置按第一次出现
    retry = _rec("甲|ABC-001", new_text="补翻成功的标题")
    # 反过来，先成功后失败的也以失败那条为准
    plot_redo_failed = _rec("甲|ABC-001", "plot", new_text=None, error="假名占比超过 15%，疑似没翻")

    assert latest_translations([first_try, plot, other, retry, plot_redo_failed]) == [retry, plot_redo_failed, other]
    assert latest_translations([]) == []
