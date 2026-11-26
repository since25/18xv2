from __future__ import annotations

from pathlib import Path

from app.models.actresses import JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.films import Film, load_films, read_nfo_title
from app.services.actresses.names import normalize_actress_name


def _add_item(
    db_session,
    path: Path,
    actors: tuple[str, ...] = (),
    *,
    source: str = "strm_115",
    active: bool = True,
    jellyfin_item_id: str | None = None,
) -> JellyfinMediaItem:
    """插入一个扫描条目和它的 NFO 演员行（只写库，不建文件）。"""
    item = JellyfinMediaItem(
        source=source,
        path=str(path),
        active=active,
        jellyfin_item_id=jellyfin_item_id,
        resolve_state="resolved" if jellyfin_item_id else "pending",
    )
    db_session.add(item)
    db_session.flush()
    for position, name in enumerate(actors):
        db_session.add(
            JellyfinMediaActor(
                media_item_id=item.id,
                position=position,
                raw_name=name,
                name_normalized=normalize_actress_name(name),
            )
        )
    db_session.commit()
    return item


def test_load_films_groups_parts_and_unions_actors(db_session, tmp_path):
    root = tmp_path / "strm"
    # 两段都带 NFO、演员不同：整部片取并集
    cd1 = _add_item(db_session, root / "甲" / "ABC-001" / "ABC-001-cd1.strm", ("甲", "乙"), jellyfin_item_id="jf-1")
    cd2 = _add_item(db_session, root / "甲" / "ABC-001" / "ABC-001-cd2.strm", ("乙 ", "丙"))
    # 只有一段带 NFO：另一段没有演员行，整部片仍按带 NFO 那段的演员算
    part1 = _add_item(db_session, root / "甲" / "ABC-002" / "ABC-002-cd1.strm")
    part2 = _add_item(db_session, root / "甲" / "ABC-002" / "ABC-002-cd2.strm", ("乙",), jellyfin_item_id="jf-2")

    films = load_films(db_session, strm_roots=[str(root)])

    assert films == [
        Film(
            film_dir=str(root / "甲" / "ABC-001"),
            number="ABC-001",
            actor_dir=str(root / "甲"),
            strm_paths=(cd1.path, cd2.path),
            media_item_ids=(cd1.id, cd2.id),
            jellyfin_item_ids=("jf-1",),
            actor_names=("甲", "乙", "丙"),
        ),
        Film(
            film_dir=str(root / "甲" / "ABC-002"),
            number="ABC-002",
            actor_dir=str(root / "甲"),
            strm_paths=(part1.path, part2.path),
            media_item_ids=(part1.id, part2.id),
            jellyfin_item_ids=("jf-2",),
            actor_names=("乙",),
        ),
    ]


def test_load_films_skips_inactive_local_and_wrong_depth(db_session, tmp_path):
    root = tmp_path / "strm"
    valid = _add_item(db_session, root / "甲" / "ABC-001" / "ABC-001.strm", ("甲",))
    # 文件消失后扫描只把条目置为无效、演员行还在
    _add_item(db_session, root / "甲" / "ABC-002" / "ABC-002.strm", ("甲",), active=False)
    _add_item(db_session, root / "甲" / "ABC-003" / "ABC-003.strm", ("甲",), source="local")
    _add_item(db_session, root / "甲" / "ABC-004.strm", ("甲",))
    _add_item(db_session, root / "甲" / "ABC-005" / "子目录" / "ABC-005.strm", ("甲",))
    _add_item(db_session, root / "甲" / "ABC-006" / "ABC-006.mp4", ("甲",))
    _add_item(db_session, tmp_path / "其他" / "甲" / "ABC-007" / "ABC-007.strm", ("甲",))

    films = load_films(db_session, strm_roots=[str(root)])

    assert [film.film_dir for film in films] == [str(root / "甲" / "ABC-001")]
    assert films[0].media_item_ids == (valid.id,)


def test_load_films_filters_by_film_dirs(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_item(db_session, root / "甲" / "ABC-001" / "ABC-001.strm", ("甲",))
    _add_item(db_session, root / "甲" / "ABC-002" / "ABC-002.strm", ("甲",))
    _add_item(db_session, root / "甲" / "ABC-003" / "ABC-003.strm", ("乙",))

    films = load_films(
        db_session,
        strm_roots=[str(root) + "/"],
        film_dirs={str(root / "甲" / "ABC-002"), str(root / "甲" / "ABC-003") + "/"},
    )

    assert [film.number for film in films] == ["ABC-002", "ABC-003"]
    assert load_films(db_session, strm_roots=[str(root)], film_dirs=set()) == []


def _film(film_dir: Path) -> Film:
    return Film(
        film_dir=str(film_dir),
        number=film_dir.name,
        actor_dir=str(film_dir.parent),
        strm_paths=(),
        media_item_ids=(),
        jellyfin_item_ids=(),
        actor_names=(),
    )


def test_read_nfo_title_returns_none_on_broken_xml(tmp_path):
    good_dir = tmp_path / "甲" / "ABC-001"
    good_dir.mkdir(parents=True)
    (good_dir / "ABC-001.nfo").write_text("<movie><title> 标题甲 </title></movie>", encoding="utf-8")
    broken_dir = tmp_path / "甲" / "ABC-002"
    broken_dir.mkdir(parents=True)
    (broken_dir / "ABC-002.nfo").write_text("<movie><title>标题乙", encoding="utf-8")
    no_nfo_dir = tmp_path / "甲" / "ABC-003"
    no_nfo_dir.mkdir(parents=True)

    assert read_nfo_title(_film(good_dir)) == "标题甲"
    assert read_nfo_title(_film(broken_dir)) is None
    assert read_nfo_title(_film(no_nfo_dir)) is None
    assert read_nfo_title(_film(tmp_path / "甲" / "ABC-404")) is None
