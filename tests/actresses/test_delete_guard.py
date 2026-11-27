from __future__ import annotations

from pathlib import Path

import pytest

from app.services.actresses.delete_guard import (
    FilmDeleteGuard,
    GuardError,
    PathMapper,
    build_url_index,
    parse_path_map,
    read_strm_url,
)

URL = "http://openlist.test/d/115_OPEN/AV/ABC-001.mp4"


def _make_guard(tmp_path: Path) -> tuple[FilmDeleteGuard, Path, Path]:
    """建 source/ 和 organized/甲/ABC-001/（含 STRM 与 NFO），返回守卫和两个根目录。"""
    source = tmp_path / "source"
    organized = tmp_path / "organized"
    source.mkdir()
    film = organized / "甲" / "ABC-001"
    film.mkdir(parents=True)
    (film / "ABC-001.strm").write_text(URL + "\n", encoding="utf-8")
    (film / "ABC-001.nfo").write_text("<movie/>", encoding="utf-8")
    return FilmDeleteGuard(str(source), str(organized)), source, organized


def test_path_mapper_longest_prefix_on_dir_boundary():
    m = PathMapper(parse_path_map("/mnt/user/v=>/mnt/cache/v,/mnt/user/v/x=>/other"))
    assert m.map("/mnt/user/v/a/b.strm") == "/mnt/cache/v/a/b.strm"
    assert m.map("/mnt/user/v/x/c") == "/other/c"
    assert m.map("/mnt/user/vv/a") == "/mnt/user/vv/a"


def test_parse_path_map_empty_and_malformed():
    assert parse_path_map("") == []
    assert parse_path_map(" /a/ => /b/ , ") == [("/a/", "/b/")]
    # 末尾斜杠不影响目录边界匹配
    assert PathMapper(parse_path_map("/a/=>/b/")).map("/a/x") == "/b/x"
    for value in ("/a", "/a=>", "=>/b"):
        with pytest.raises(ValueError):
            parse_path_map(value)


def test_guard_requires_absolute_roots(tmp_path):
    for source, organized in (("", str(tmp_path)), (str(tmp_path), "organized")):
        with pytest.raises(GuardError):
            FilmDeleteGuard(source, organized)
    guard = FilmDeleteGuard(str(tmp_path / "source"), str(tmp_path / "organized"))
    assert guard.source_root == str(tmp_path / "source")
    assert guard.organized_root == str(tmp_path / "organized")


def test_delete_film_dir_requires_exact_depth(tmp_path):
    guard, _, organized = _make_guard(tmp_path)
    deep = organized / "甲" / "ABC-001" / "sub"
    deep.mkdir()

    for path in (
        str(organized),
        str(organized / "甲"),
        str(deep),
        # 用 .. 绕回根下一层
        f"{organized}/甲/ABC-001/../..",
        f"{organized}/甲/../甲",
        # 相对路径
        "甲/ABC-001",
    ):
        with pytest.raises(GuardError):
            guard.delete_film_dir(path)
    assert deep.is_dir()


def test_delete_film_dir_rejects_symlink_and_outside_root(tmp_path):
    guard, source, organized = _make_guard(tmp_path)
    outside = tmp_path / "outside" / "乙" / "ABC-002"
    outside.mkdir(parents=True)
    # 番号目录本身是链接
    (organized / "甲" / "ABC-002").symlink_to(outside, target_is_directory=True)
    # 演员目录是链接，指到根外
    (organized / "乙").symlink_to(tmp_path / "outside" / "乙", target_is_directory=True)
    # 番号位置上是普通文件
    (organized / "甲" / "ABC-003").write_text("x", encoding="utf-8")
    (source / "甲" / "ABC-004").mkdir(parents=True)

    for path in (
        organized / "甲" / "ABC-002",
        organized / "乙" / "ABC-002",
        outside,
        source / "甲" / "ABC-004",
        organized / "甲" / "ABC-003",
    ):
        with pytest.raises(GuardError):
            guard.delete_film_dir(str(path))
    assert outside.is_dir()
    assert (organized / "甲" / "ABC-002").is_symlink()
    assert (source / "甲" / "ABC-004").is_dir()
    assert (organized / "甲" / "ABC-003").is_file()


def test_delete_film_dir_removes_whole_dir(tmp_path):
    guard, _, organized = _make_guard(tmp_path)
    film = organized / "甲" / "ABC-001"
    outside_file = tmp_path / "poster.jpg"
    outside_file.write_text("x", encoding="utf-8")
    # 番号目录里指到外面的链接只删链接本身
    (film / "poster.jpg").symlink_to(outside_file)

    assert guard.delete_film_dir(str(film) + "/") == "deleted"
    assert not film.exists()
    assert outside_file.is_file()
    # 演员目录不在这一步删
    assert (organized / "甲").is_dir()
    assert guard.delete_film_dir(str(film)) == "missing"


def test_remove_actor_dir_only_when_empty(tmp_path):
    guard, _, organized = _make_guard(tmp_path)
    actor = organized / "甲"

    assert guard.remove_actor_dir_if_empty(str(actor)) is False
    assert actor.is_dir()

    guard.delete_film_dir(str(actor / "ABC-001"))
    assert guard.remove_actor_dir_if_empty(str(actor)) is True
    assert not actor.exists()
    assert organized.is_dir()
    assert guard.remove_actor_dir_if_empty(str(actor)) is False

    empty_outside = tmp_path / "empty"
    empty_outside.mkdir()
    (organized / "乙").symlink_to(empty_outside, target_is_directory=True)
    for path in (organized, organized / "乙" / "ABC-002", organized / "乙"):
        with pytest.raises(GuardError):
            guard.remove_actor_dir_if_empty(str(path))
    assert empty_outside.is_dir()
    assert organized.is_dir()


def test_delete_source_strm_rejects_non_strm(tmp_path):
    guard, source, organized = _make_guard(tmp_path)
    strm = source / "AV" / "ABC-001.strm"
    strm.parent.mkdir()
    strm.write_text(URL, encoding="utf-8")
    nfo = source / "AV" / "ABC-001.nfo"
    nfo.write_text("x", encoding="utf-8")
    strm_dir = source / "AV" / "ABC-002.strm"
    strm_dir.mkdir()
    outside_strm = tmp_path / "outside.strm"
    outside_strm.write_text(URL, encoding="utf-8")
    link = source / "AV" / "ABC-003.strm"
    link.symlink_to(outside_strm)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "ABC-004.strm").write_text(URL, encoding="utf-8")
    (source / "linked").symlink_to(outside_dir, target_is_directory=True)
    organized_strm = organized / "甲" / "ABC-001" / "ABC-001.strm"

    for path in (
        nfo,
        strm_dir,
        outside_strm,
        link,
        source / "linked" / "ABC-004.strm",
        organized_strm,
    ):
        with pytest.raises(GuardError):
            guard.delete_source_strm(str(path))
    with pytest.raises(GuardError):
        guard.delete_source_strm("AV/ABC-001.strm")
    for path in (nfo, strm_dir, outside_strm, link, outside_dir / "ABC-004.strm", organized_strm):
        assert path.exists()

    assert guard.delete_source_strm(str(strm)) == "deleted"
    assert not strm.exists()
    assert guard.delete_source_strm(str(strm)) == "missing"


def test_build_url_index_normalizes_scheme_and_host_case(tmp_path):
    root = tmp_path / "source"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "ABC-001.strm").write_text("HTTP://OpenList.Test/d/115_OPEN/AV/ABC-001.mp4\n", encoding="utf-8")
    # 开头空行、BOM 都跳过
    (root / "b" / "ABC-001.strm").write_text("\n" + URL, encoding="utf-8-sig")
    (root / "b" / "ABC-002.strm").write_text("http://openlist.test/d/115_OPEN/AV/ABC-002.mp4", encoding="utf-8")
    (root / "b" / "ABC-002.nfo").write_text(URL, encoding="utf-8")
    (root / "b" / "empty.strm").write_text("\n", encoding="utf-8")

    assert build_url_index(str(root)) == {
        URL: [str(root / "a" / "ABC-001.strm"), str(root / "b" / "ABC-001.strm")],
        "http://openlist.test/d/115_OPEN/AV/ABC-002.mp4": [str(root / "b" / "ABC-002.strm")],
    }
    assert read_strm_url(str(root / "b" / "empty.strm")) is None
    assert read_strm_url(str(root / "b" / "missing.strm")) is None
    # 根目录不在时报错，不能当成「没有对应 STRM」
    with pytest.raises(OSError):
        build_url_index(str(tmp_path / "missing"))


def test_check_film_dir_validates_without_deleting(tmp_path):
    guard, source, organized = _make_guard(tmp_path)
    film = organized / "甲" / "ABC-001"
    outside = tmp_path / "outside" / "乙" / "ABC-002"
    outside.mkdir(parents=True)
    (organized / "甲" / "ABC-002").symlink_to(outside, target_is_directory=True)
    (organized / "乙").symlink_to(tmp_path / "outside" / "乙", target_is_directory=True)
    (organized / "甲" / "ABC-003").write_text("x", encoding="utf-8")
    (source / "甲" / "ABC-004").mkdir(parents=True)

    assert guard.check_film_dir(str(film) + "/") == str(film)
    assert film.is_dir()
    for path in (
        organized / "甲" / "ABC-002",
        organized / "乙" / "ABC-002",
        outside,
        source / "甲" / "ABC-004",
        organized / "甲" / "ABC-003",
        # 不存在也不合格
        organized / "甲" / "ABC-009",
        organized / "甲",
        film / "sub",
    ):
        with pytest.raises(GuardError):
            guard.check_film_dir(str(path))
    assert (organized / "甲" / "ABC-002").is_symlink()
    assert outside.is_dir()


def test_delete_source_dir_removes_dir_under_root(tmp_path):
    guard, source, _ = _make_guard(tmp_path)
    target = source / "AV" / "ABC-001"
    target.mkdir(parents=True)
    (target / "a.nfo").write_text("x", encoding="utf-8")

    assert guard.delete_source_dir(str(target) + "/") == "deleted"
    assert not target.exists()


def test_delete_source_dir_rejects_root_and_outside(tmp_path):
    guard, source, _ = _make_guard(tmp_path)
    outside = tmp_path / "other"
    outside.mkdir()

    for path in (source, outside):
        with pytest.raises(GuardError):
            guard.delete_source_dir(str(path))
    assert source.is_dir()
    assert outside.is_dir()


def test_delete_source_dir_missing(tmp_path):
    guard, source, _ = _make_guard(tmp_path)

    assert guard.delete_source_dir(str(source / "AV" / "nope")) == "missing"


def test_delete_source_sidecar_only_sidecar_exts(tmp_path):
    guard, source, _ = _make_guard(tmp_path)
    folder = source / "AV"
    folder.mkdir()
    nfo = folder / "a.nfo"
    nfo.write_text("x", encoding="utf-8")
    strm = folder / "a.strm"
    strm.write_text(URL, encoding="utf-8")
    mp4 = folder / "a.mp4"
    mp4.write_text("x", encoding="utf-8")

    assert guard.delete_source_sidecar(str(nfo)) == "deleted"
    assert not nfo.exists()
    for path in (strm, mp4):
        with pytest.raises(GuardError):
            guard.delete_source_sidecar(str(path))
        assert path.exists()
    assert guard.delete_source_sidecar(str(folder / "missing.nfo")) == "missing"
