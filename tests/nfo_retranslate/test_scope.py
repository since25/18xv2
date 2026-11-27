from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app.services.nfo_retranslate.nfo_file import NfoDoc
from app.services.nfo_retranslate.scope import (
    CN_SOURCES,
    FieldSources,
    FilmGroup,
    count_orphans,
    field_in_scope,
    group_films,
    group_matches_engine,
    has_kana,
    load_task_sources,
    snapshot_mdc_db,
)

_CREATE_TASK = (
    "CREATE TABLE task (id INTEGER PRIMARY KEY, primary_task_id INTEGER, "
    "target_path TEXT, metadata_provider_info TEXT)"
)


def _make_mdc_db(path: Path, rows: list[tuple]) -> None:
    """建一个只有 task 表的小库（普通日志模式）。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute(_CREATE_TASK)
        conn.executemany("INSERT INTO task VALUES (?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def _doc(path: str = "/lib/a/ABC-001/ABC-001.nfo", **fields) -> NfoDoc:
    """造一个 NfoDoc，只填测试关心的字段。"""
    values = {
        "raw": "",
        "sha256": "",
        "num": "ABC-001",
        "title": "ABC-001 旧标题",
        "original_title": "ABC-001 婚約したばかりの僕",
        "plot": "旧简介<br>  <br>由 OpenAI 提供翻译",
        "original_plot": "婚約したばかりの僕に囁く",
        "actors": (),
        "studio": "",
        "series": "",
    }
    values.update(fields)
    return NfoDoc(path=path, **values)


def _write_nfo(path: Path, num: str, plot: str = "") -> None:
    """照生产格式写一个最小 NFO。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8" ?>\n'
        "<movie>\n"
        f"  <title><![CDATA[{num} 标题]]></title>\n"
        f"  <originaltitle><![CDATA[{num} 婚約したばかりの僕]]></originaltitle>\n"
        f"  <plot><![CDATA[{plot}]]></plot>\n"
        "  <originalplot>囁く&amp;誘惑する</originalplot>\n"
        f"  <num>{num}</num>\n"
        "</movie>\n",
        encoding="utf-8",
    )


def test_cn_sources_exact():
    assert CN_SOURCES == frozenset({"airav_io", "sehuatang", "Madou", "Madouqu", "xiao_huang_shu"})


def test_load_task_sources_maps_paths_and_children(tmp_path):
    db = tmp_path / "mdc_ng.db"
    root = tmp_path / "302porn_tv1"
    _make_mdc_db(
        db,
        [
            (
                1,
                None,
                "/302video/302porn_tv1/森泽佳奈/ABC-001/ABC-001-cd1.strm",
                json.dumps({"Title": "dmm", "Outline": "airav_io", "Actor": "dmm"}),
            ),
            (2, 1, "/302video/302porn_tv1/森泽佳奈/ABC-001/ABC-001-cd2.strm", None),
            (3, None, "/302video/302porn_tv1/甲/XYZ-002/XYZ-002.strm", "{坏 json"),
            (4, None, "/302video/302porn_tv10/乙/DEF-003/DEF-003.strm", json.dumps({"Title": "dmm"})),
        ],
    )

    sources = load_task_sources(str(db), str(root))

    expected = FieldSources(title="dmm", outline="airav_io")
    assert sources == {
        str(root / "森泽佳奈/ABC-001/ABC-001-cd1.nfo"): expected,
        str(root / "森泽佳奈/ABC-001/ABC-001-cd2.nfo"): expected,
        str(root / "甲/XYZ-002/XYZ-002.nfo"): FieldSources(title=None, outline=None),
    }


def test_has_kana():
    assert has_kana("婚約したばかり")
    assert has_kana("カタカナ")
    assert not has_kana("订婚后的我")
    assert not has_kana("")


def test_field_in_scope_title():
    doc = _doc()

    assert field_in_scope("title", doc, FieldSources(title="dmm", outline="dmm")) is True
    assert field_in_scope("title", doc, FieldSources(title="airav_io", outline="dmm")) is False
    assert field_in_scope("title", doc, None) is False
    # MDC 没记录标题来源，和找不到任务一样跳过
    assert field_in_scope("title", doc, FieldSources(title=None, outline="dmm")) is False
    no_kana = _doc(original_title="ABC-001 新人出道")
    assert field_in_scope("title", no_kana, FieldSources(title="dmm", outline="dmm")) is False
    # 假名只在番号里，去掉番号后没有假名
    kana_num = _doc(num="2017-11-18 MIDE-488 新人デビュー", original_title="2017-11-18 MIDE-488 新人デビュー")
    assert field_in_scope("title", kana_num, FieldSources(title="dmm", outline="dmm")) is False


def test_field_in_scope_plot_follows_outline_source():
    doc = _doc()

    assert field_in_scope("plot", doc, FieldSources(title="airav_io", outline="dmm")) is True
    assert field_in_scope("plot", doc, FieldSources(title="dmm", outline="sehuatang")) is False
    chinese = _doc(original_plot="订婚后的我")
    assert field_in_scope("plot", chinese, FieldSources(title="dmm", outline="dmm")) is False


def test_field_in_scope_plot_unknown_outline_uses_marker():
    unknown = FieldSources(title="dmm", outline=None)
    marked = _doc(plot="旧译文<br>  <br>由 Google 提供翻译")
    unmarked = _doc(plot="中文站给的简介")

    assert field_in_scope("plot", marked, unknown) is True
    assert field_in_scope("plot", unmarked, unknown) is False


def test_field_in_scope_plot_without_task_uses_marker():
    marked = _doc(plot="旧译文<br>  <br>由 Google 提供翻译")
    unmarked = _doc(plot="中文站给的简介")
    marked_chinese = _doc(plot="旧译文<br>  <br>由 Google 提供翻译", original_plot="中文原简介")

    assert field_in_scope("plot", marked, None) is True
    assert field_in_scope("plot", unmarked, None) is False
    assert field_in_scope("plot", marked_chinese, None) is False


def test_group_films_groups_parts_and_versions(tmp_path):
    root = tmp_path / "302porn_tv1"
    film_dir = root / "森泽佳奈" / "ABC-001"
    for name in ("ABC-001-cd2.nfo", "ABC-001-cd1.nfo", "ABC-001-C.nfo"):
        _write_nfo(film_dir / name, "ABC-001")
    other_dir = root / "甲" / "XYZ-002"
    _write_nfo(other_dir / "XYZ-002.nfo", "XYZ-002")
    broken = other_dir / "broken.nfo"
    broken.write_text("<movie><title>没闭合</movie>", encoding="utf-8")
    (other_dir / "XYZ-002.strm").write_text("http://example.invalid/x", encoding="utf-8")

    groups, errors = group_films(str(root))

    assert [g.key for g in groups] == ["森泽佳奈/ABC-001|ABC-001", "甲/XYZ-002|XYZ-002"]
    assert [d.path for d in groups[0].docs] == [
        str(film_dir / "ABC-001-C.nfo"),
        str(film_dir / "ABC-001-cd1.nfo"),
        str(film_dir / "ABC-001-cd2.nfo"),
    ]
    assert [d.path for d in groups[1].docs] == [str(other_dir / "XYZ-002.nfo")]
    assert len(errors) == 1
    assert errors[0][0] == str(broken)
    assert errors[0][1]


def test_group_films_empty_num_not_merged(tmp_path):
    root = tmp_path / "302porn_tv1"
    film_dir = root / "甲" / "无番号"
    _write_nfo(film_dir / "片子甲.nfo", "")
    _write_nfo(film_dir / "片子乙.nfo", "")
    _write_nfo(film_dir / "ABC-001.nfo", "ABC-001")

    groups, errors = group_films(str(root))

    assert errors == []
    assert [g.key for g in groups] == ["甲/无番号|ABC-001", "甲/无番号|片子乙", "甲/无番号|片子甲"]
    assert [[d.path for d in g.docs] for g in groups] == [
        [str(film_dir / "ABC-001.nfo")],
        [str(film_dir / "片子乙.nfo")],
        [str(film_dir / "片子甲.nfo")],
    ]


def test_group_films_path_prefix(tmp_path):
    root = tmp_path / "302porn_tv1"
    _write_nfo(root / "森泽佳奈" / "ABC-001" / "ABC-001.nfo", "ABC-001")
    _write_nfo(root / "森泽佳奈" / "MIAA-759" / "MIAA-759.nfo", "MIAA-759")
    _write_nfo(root / "甲" / "XYZ-002" / "XYZ-002.nfo", "XYZ-002")

    by_actor, _ = group_films(str(root), path_prefix="森泽佳奈")
    by_film, _ = group_films(str(root), path_prefix="森泽佳奈/MIAA-759")

    assert [g.key for g in by_actor] == ["森泽佳奈/ABC-001|ABC-001", "森泽佳奈/MIAA-759|MIAA-759"]
    assert [g.key for g in by_film] == ["森泽佳奈/MIAA-759|MIAA-759"]


def test_count_orphans_and_engine_filter():
    google = FilmGroup(
        key="甲/ABC-001|ABC-001",
        docs=[
            _doc("/lib/甲/ABC-001/ABC-001-cd1.nfo", plot="旧译<br>  <br>由 Google 提供翻译"),
            _doc("/lib/甲/ABC-001/ABC-001-cd2.nfo", plot="旧译<br>  <br>由 OpenAI 提供翻译"),
        ],
    )
    openai = FilmGroup(
        key="乙/XYZ-002|XYZ-002",
        docs=[_doc("/lib/乙/XYZ-002/XYZ-002.nfo", num="XYZ-002", plot="旧译<br>  <br>由 OpenAI 提供翻译")],
    )
    sources = {
        "/lib/甲/ABC-001/ABC-001-cd1.nfo": FieldSources(title="dmm", outline="dmm"),
        "/lib/乙/XYZ-002/XYZ-002.nfo": FieldSources(title="dmm", outline="dmm"),
    }

    assert count_orphans([google, openai], sources) == 1
    assert group_matches_engine(google, "Google") is True
    assert group_matches_engine(openai, "Google") is False
    assert group_matches_engine(openai, "OpenAI") is True


def test_snapshot_copies_wal(tmp_path):
    src_dir = tmp_path / "mdc"
    src_dir.mkdir()
    src = src_dir / "mdc_ng.db"
    conn = sqlite3.connect(src)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute(_CREATE_TASK)
        conn.execute(
            "INSERT INTO task VALUES (1, NULL, ?, ?)",
            ("/302video/302porn_tv1/甲/ABC-001/ABC-001.strm", json.dumps({"Title": "dmm", "Outline": "dmm"})),
        )
        conn.commit()
        # 连接保持打开，数据只在 -wal 里，没并回主库
        assert (src_dir / "mdc_ng.db-wal").stat().st_size > 0
        copy = snapshot_mdc_db(str(src), str(tmp_path / "run" / "mdc"))
    finally:
        conn.close()

    assert copy == str(tmp_path / "run" / "mdc" / "mdc_ng.db")
    assert Path(copy + "-wal").is_file()
    sources = load_task_sources(copy, "/lib")
    assert sources == {"/lib/甲/ABC-001/ABC-001.nfo": FieldSources(title="dmm", outline="dmm")}


def test_snapshot_drops_stale_wal(tmp_path):
    src = tmp_path / "mdc_ng.db"
    _make_mdc_db(src, [(1, None, "/302video/302porn_tv1/甲/ABC-001/ABC-001.strm", json.dumps({"Title": "dmm"}))])
    workdir = tmp_path / "run" / "mdc"
    workdir.mkdir(parents=True)
    (workdir / "mdc_ng.db-wal").write_bytes(b"stale")
    (workdir / "mdc_ng.db-shm").write_bytes(b"stale")

    copy = snapshot_mdc_db(str(src), str(workdir))

    assert not Path(copy + "-wal").exists()
    assert not Path(copy + "-shm").exists()
    assert load_task_sources(copy, "/lib") == {"/lib/甲/ABC-001/ABC-001.nfo": FieldSources(title="dmm", outline=None)}


def test_snapshot_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot_mdc_db(str(tmp_path / "missing.db"), str(tmp_path / "run"))
