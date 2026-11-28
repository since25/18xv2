from __future__ import annotations

import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from app.models.jellyfin import JellyfinMediaItem
from app.services.jellyfin.client import JellyfinError
from app.services.nfo_retranslate.apply_service import (
    ApplyResult,
    apply_run,
    item_ids_for,
    make_refresher,
    restore_run,
)
from app.services.nfo_retranslate.nfo_file import build_plot, read_nfo, replace_fields, sha256_text
from app.services.nfo_retranslate.runs import LedgerEntry, RunDir, TranslationRecord, append_ledger, load_ledger

_FIXTURE = Path(__file__).parent / "fixtures" / "sample.nfo"
_ORIGINAL_TITLE = "MIAA-759 订婚后的我被两位上司在耳边低语诱惑"
_MODEL = "qwen38"


@pytest.fixture
def env(tmp_path):
    """可写根目录（还没有文件）、运行记录根目录、一次新的运行。"""
    root = tmp_path / "302porn_tv1"
    base = str(tmp_path / "nfo_retranslate")
    return root, base, RunDir.create(base)


def _make_nfo(root: Path, rel: str, *, title: str | None = None) -> str:
    """把样例 NFO 放到 root/rel；给了 title 时换掉原标题。返回绝对路径。"""
    text = _FIXTURE.read_bytes().decode("utf-8")
    if title is not None:
        text = text.replace(_ORIGINAL_TITLE, title, 1)
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _sha(path: str) -> str:
    return sha256_text(Path(path).read_bytes().decode("utf-8"))


def _rec(path: str, field: str, new_text: str | None, *, error: str | None = None) -> TranslationRecord:
    """一个 NFO 一组；targets 记下它此刻的哈希，相当于 translate 时读到的。"""
    return TranslationRecord(
        group_key=path,
        field=field,
        num="MIAA-759",
        actors=["西田那津", "森泽佳奈"],
        source_text="日文原文",
        old_text="旧译文",
        new_text=new_text,
        error=error,
        targets={path: _sha(path)},
    )


def _apply(run: RunDir, base: str, root: Path, *, skip_paths: set[str] | None = None, refresher=None) -> ApplyResult:
    return apply_run(
        run, base_dir=base, root=str(root), model=_MODEL, skip_paths=skip_paths or set(), refresher=refresher
    )


def _touch_rating(path: str) -> bytes:
    """模拟 MDC 改了文件里别的内容；返回改后的字节。"""
    changed = Path(path).read_bytes().replace(b"<rating>7.0</rating>", b"<rating>8.0</rating>")
    Path(path).write_bytes(changed)
    return changed


def test_apply_writes_title_and_plot_and_ledger(env):
    root, base, run = env
    rel = os.path.join("西田那津,森泽佳奈", "MIAA-759", "MIAA-759-cd2.nfo")
    nfo = _make_nfo(root, rel, title="MIAA-759 旧标题 cd2")
    original = Path(nfo).read_bytes()
    run.append_translation(_rec(nfo, "title", "新标题译文"))
    run.append_translation(_rec(nfo, "plot", "第一行\n第二行"))

    result = _apply(run, base, root)

    assert result == ApplyResult(written=[nfo], skipped=[], refreshed=0, refresh_failed=[], missing_items=[])
    after = Path(nfo).read_bytes()
    doc = read_nfo(nfo)
    # 番号原样 + 空格 + 译文 + 原来的 cd 后缀；简介结尾带模型名
    assert doc.title == "MIAA-759 新标题译文 cd2"
    assert doc.plot == "第一行<br>第二行<br>  <br>由 qwen38 提供翻译"
    assert ET.fromstring(after).findtext("outline") == doc.plot
    # 只有三个标签变了，其余逐字节不变
    assert after.decode("utf-8") == replace_fields(original.decode("utf-8"), title=doc.title, plot=doc.plot)
    # 备份和原文件逐字节相同
    assert Path(run.backup_dir, rel).read_bytes() == original

    sha_after = sha256_text(after.decode("utf-8"))
    assert load_ledger(base) == {
        nfo: LedgerEntry(sha256_after=sha_after, fields=frozenset({"title", "plot"}), model=_MODEL)
    }
    assert run.load_apply() == [{"path": nfo, "fields": ["plot", "title"], "sha256_after": sha_after, "backup": rel}]


def test_apply_skips_changed_file(env):
    root, base, run = env
    rel = os.path.join("甲", "MIAA-759", "MIAA-759.nfo")
    nfo = _make_nfo(root, rel)
    run.append_translation(_rec(nfo, "title", "新标题译文"))
    run.append_translation(_rec(nfo, "plot", "新简介"))
    changed = _touch_rating(nfo)

    result = _apply(run, base, root)

    assert result.written == []
    assert len(result.skipped) == 1
    path, reason = result.skipped[0]
    assert path == nfo
    assert "已被改动" in reason
    assert Path(nfo).read_bytes() == changed
    assert not os.path.exists(os.path.join(run.backup_dir, rel))
    assert load_ledger(base) == {}
    assert run.load_apply() == [{"path": nfo, "skipped": reason}]


def test_apply_skips_failed_and_listed(env):
    root, base, run = env
    a = _make_nfo(root, "a/A/A.nfo")
    b = _make_nfo(root, "b/B/B.nfo")
    c = _make_nfo(root, "c/C/C.nfo")
    originals = {path: Path(path).read_bytes() for path in (b, c)}
    # A：标题先成功、续跑补翻时失败，以最后一条为准不写；简介成功
    run.append_translation(_rec(a, "title", "第一次的标题"))
    run.append_translation(_rec(a, "plot", "A 的简介"))
    run.append_translation(_rec(a, "title", None, error="假名占比超过 15%，疑似没翻"))
    # B：译文都成功，但在跳过名单里
    run.append_translation(_rec(b, "title", "B 的标题"))
    run.append_translation(_rec(b, "plot", "B 的简介"))
    # C：有译文但带着错误原因，也不写
    run.append_translation(_rec(c, "title", "C 的标题", error="标题超过 60 字"))

    result = _apply(run, base, root, skip_paths={b})

    assert result.written == [a]
    doc = read_nfo(a)
    assert doc.title == _ORIGINAL_TITLE
    assert doc.plot == build_plot("A 的简介", _MODEL)
    assert Path(b).read_bytes() == originals[b]
    assert Path(c).read_bytes() == originals[c]
    assert load_ledger(base)[a].fields == frozenset({"plot"})
    assert set(load_ledger(base)) == {a}
    assert {path for path, _ in result.skipped} == {a, b, c}
    assert any("跳过名单" in reason for path, reason in result.skipped if path == b)


def test_apply_title_skipped_when_title_not_prefixed_by_num(env):
    root, base, run = env
    nfo = _make_nfo(root, "甲/MIAA-759/MIAA-759.nfo", title="订婚后的我被两位上司在耳边低语诱惑")
    run.append_translation(_rec(nfo, "title", "新标题译文"))
    run.append_translation(_rec(nfo, "plot", "新简介"))

    result = _apply(run, base, root)

    assert result.written == [nfo]
    doc = read_nfo(nfo)
    assert doc.title == "订婚后的我被两位上司在耳边低语诱惑"
    assert doc.plot == build_plot("新简介", _MODEL)
    assert len(result.skipped) == 1
    path, reason = result.skipped[0]
    assert path == nfo
    assert "番号" in reason
    assert load_ledger(base)[nfo].fields == frozenset({"plot"})


def test_restore_puts_backup_back_and_drops_ledger(env):
    root, base, run = env
    x = _make_nfo(root, "a/X/X.nfo")
    y = _make_nfo(root, "b/Y/Y.nfo")
    original_x = Path(x).read_bytes()
    for path in (x, y):
        run.append_translation(_rec(path, "title", "新标题译文"))
        run.append_translation(_rec(path, "plot", "新简介"))
    other = LedgerEntry(sha256_after="c" * 64, fields=frozenset({"plot"}), model="gemma3")
    append_ledger(base, "/media/别的运行.nfo", other)
    assert _apply(run, base, root).written == [x, y]
    # 写入后 Y 又被 MDC 改过
    changed_y = _touch_rating(y)
    calls: list[list[str]] = []

    def refresher(paths: list[str]) -> tuple[int, list[tuple[str, str]], list[str]]:
        calls.append(list(paths))
        return len(paths), [], []

    result = restore_run(run, base_dir=base, refresher=refresher)

    assert result.written == [x]
    assert Path(x).read_bytes() == original_x
    assert Path(y).read_bytes() == changed_y
    assert [path for path, _ in result.skipped] == [y]
    assert "已被改动" in result.skipped[0][1]
    assert calls == [[x]]
    assert result.refreshed == 1
    ledger = load_ledger(base)
    assert set(ledger) == {y, "/media/别的运行.nfo"}
    assert ledger["/media/别的运行.nfo"] == other


def test_refresh_failure_is_recorded_not_raised(env, db_session, tmp_path):
    root, base, run = env
    strm_root = tmp_path / "strm" / "302porn_tv1"
    a = _make_nfo(root, "a/A-001/A-001.nfo")
    b1 = _make_nfo(root, "b/B-002/B-002-cd1.nfo")
    b2 = _make_nfo(root, "b/B-002/B-002-cd2.nfo")
    c = _make_nfo(root, "c/C-003/C-003.nfo")
    # 两段视频在 Jellyfin 里是同一个条目
    for rel, item_id in [
        ("a/A-001/A-001.strm", "j1"),
        ("b/B-002/B-002-cd1.strm", "j2"),
        ("b/B-002/B-002-cd2.strm", "j2"),
    ]:
        db_session.add(JellyfinMediaItem(source="strm_115", path=str(strm_root / rel), jellyfin_item_id=item_id))
    db_session.commit()
    for path in (a, b1, b2, c):
        run.append_translation(_rec(path, "plot", "新简介"))
    calls: list[str] = []

    class FakeClient:
        def refresh_item(self, item_id: str) -> None:
            calls.append(item_id)
            if item_id == "j1":
                raise JellyfinError("Jellyfin 请求失败（HTTP 500）")

    refresher = make_refresher(db_session, FakeClient, root=str(root), strm_root=str(strm_root), workers=2)

    result = _apply(run, base, root, refresher=refresher)

    assert result.written == [a, b1, b2, c]
    # 同一条目只刷新一次；j1 失败不影响 j2
    assert sorted(calls) == ["j1", "j2"]
    assert result.refreshed == 1
    assert result.refresh_failed == [("j1", "Jellyfin 请求失败（HTTP 500）")]
    assert result.missing_items == [c]
    # 刷新失败不回滚 NFO
    assert read_nfo(a).plot == build_plot("新简介", _MODEL)
    assert set(load_ledger(base)) == {a, b1, b2, c}
    assert run.load_apply()[-1] == {
        "refresh": {"refreshed": 1, "failed": [["j1", "Jellyfin 请求失败（HTTP 500）"]], "missing": [c]}
    }


def test_item_ids_for_maps_paths(db_session):
    root = "/mnt/cache/媒体/302porn_tv1"
    strm_root = "/mnt/user/媒体/302porn_tv1"
    db_session.add(
        JellyfinMediaItem(source="strm_115", path=f"{strm_root}/甲/ABC-001/ABC-001.strm", jellyfin_item_id="j1")
    )
    # 别的来源、已下线的同名条目都不算
    db_session.add(
        JellyfinMediaItem(source="local", path=f"{strm_root}/乙/XYZ-002/XYZ-002.strm", jellyfin_item_id="j2")
    )
    db_session.add(
        JellyfinMediaItem(
            source="strm_115", path=f"{strm_root}/丙/DEF-003/DEF-003.strm", jellyfin_item_id="j3", active=False
        )
    )
    db_session.commit()
    found = f"{root}/甲/ABC-001/ABC-001.nfo"
    other_source = f"{root}/乙/XYZ-002/XYZ-002.nfo"
    inactive = f"{root}/丙/DEF-003/DEF-003.nfo"
    nothing = f"{root}/丁/GHI-004/GHI-004.nfo"

    ids, missing = item_ids_for(db_session, [found, other_source, inactive, nothing], root=root, strm_root=strm_root)

    assert ids == {found: "j1"}
    assert missing == [other_source, inactive, nothing]
