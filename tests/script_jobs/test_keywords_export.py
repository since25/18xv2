"""关键词导出：18x 写出的文件与 /api/keywords 分页返回完全一致，DEL 两个脚本读文件后的取词结果不变。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.api.routes.keywords import list_keywords
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.script_jobs.media_task import JOBS_DIR, export_keywords


def _entry(name, *, keyword_type="blacklist", status="active", aliases=(), merge_policy="normal") -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type=keyword_type,
        status=status,
        merge_policy=merge_policy,
    )
    entry.aliases = [KeywordAlias(alias=alias, alias_normalized=alias.lower()) for alias in aliases]
    return entry


@pytest.fixture
def keywords(db_session):
    db_session.add_all(
        [
            _entry("示例坏词甲", aliases=("坏词别名", "坏")),
            _entry("示例坏词乙"),
            _entry("示例停用词", status="inactive"),
            _entry("示例好词", keyword_type="whitelist", aliases=("好词别名",)),
            _entry("兜底词", keyword_type="whitelist", merge_policy="fallback_only"),
        ]
    )
    db_session.commit()
    return db_session


def _api_pages(db, keyword_type: str) -> list[dict]:
    entries: list[dict] = []
    skip = 0
    while True:
        page = list_keywords(keyword_type=keyword_type, status="active", query=None, skip=skip, limit=1, db=db)
        data = page.model_dump(mode="json")
        entries.extend(data["entries"])
        skip += len(data["entries"])
        if skip >= data["total"] or not data["entries"]:
            return entries


@pytest.mark.parametrize("keyword_type", ["blacklist", "whitelist"])
def test_export_matches_keywords_api(keywords, tmp_path, keyword_type):
    path = tmp_path / f"{keyword_type}.json"
    count = export_keywords(keywords, keyword_type, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = _api_pages(keywords, keyword_type)
    assert count == len(expected) == data["total"]
    assert data["entries"] == expected


def _load_script(name: str, monkeypatch, keywords_file: Path):
    monkeypatch.setenv("KEYWORDS_FILE", str(keywords_file))
    spec = importlib.util.spec_from_file_location(f"del_script_{name}", JOBS_DIR / "del_something" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def _no_network(*args, **kwargs):
        raise AssertionError("设置了 KEYWORDS_FILE 时不应访问网络")

    monkeypatch.setattr(module.requests, "Session", _no_network)
    return module


def test_delete_files_reads_keywords_file(keywords, tmp_path, monkeypatch):
    path = tmp_path / "blacklist.json"
    export_keywords(keywords, "blacklist", path)
    module = _load_script("delete_files", monkeypatch, path)
    # 别名“坏”只有 1 个字，按原规则过滤掉；停用词条不导出
    assert module.load_keywords_from_api() == {"示例坏词甲", "坏词别名", "示例坏词乙"}


def test_organizer_reads_keywords_file(keywords, tmp_path, monkeypatch):
    path = tmp_path / "whitelist.json"
    export_keywords(keywords, "whitelist", path)
    module = _load_script("local_organize_from_whitelist", monkeypatch, path)
    rules = {rule["canonical_name"]: rule for rule in module.load_whitelist_rules_from_api()}
    # 原规则：长词在前，同长按字典序
    assert rules["示例好词"]["all_terms"] == sorted(["示例好词", "好词别名"], key=lambda x: (-len(x), x))
    assert rules["示例好词"]["is_fallback"] is False
    assert rules["兜底词"]["is_fallback"] is True
