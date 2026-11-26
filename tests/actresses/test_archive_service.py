from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.actresses import Actress, ActressAlias, ActressMark, JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.actresses.archive_service import ActressError, ArchiveService
from app.services.actresses.names import build_name_index, normalize_actress_name


def _add_film(
    db_session,
    root: Path,
    number: str,
    actors: tuple[str, ...],
    *,
    actor_dir: str = "甲",
    active: bool = True,
) -> JellyfinMediaItem:
    """插入一部单段片子：一个 115 STRM 条目和它的 NFO 演员行。"""
    item = JellyfinMediaItem(
        source="strm_115",
        path=str(root / actor_dir / number / f"{number}.strm"),
        active=active,
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


def _add_actress(db_session, name: str, *, status: str = "none", aliases: tuple[str, ...] = ()) -> Actress:
    actress = Actress(canonical_name=name, canonical_name_normalized=normalize_actress_name(name), status=status)
    actress.aliases = [ActressAlias(alias=alias, alias_normalized=normalize_actress_name(alias)) for alias in aliases]
    db_session.add(actress)
    db_session.commit()
    return actress


def _by_name(db_session, normalized: str) -> Actress | None:
    return db_session.scalar(select(Actress).where(Actress.canonical_name_normalized == normalized))


def _count(db_session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model))


def test_refresh_creates_unknown_actors_and_counts_films(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_film(db_session, root, "ABC-001", ("甲", "乙　Ａ"))
    _add_film(db_session, root, "ABC-002", ("甲", "乙A"))
    # 无效条目（文件已消失）的演员不建档、不计片数
    _add_film(db_session, root, "ABC-003", ("丙", "甲"), active=False)
    stale = _add_actress(db_session, "丁")
    stale.film_count = 5
    db_session.commit()

    result = ArchiveService().refresh(db_session, strm_roots=[str(root)])

    assert result == {"created": 2, "actresses": 3}
    jia = _by_name(db_session, "甲")
    yi = _by_name(db_session, "乙A")
    assert jia is not None and jia.status == "none" and jia.film_count == 2
    # 规范名取首次出现的原样写法
    assert yi is not None and yi.canonical_name == "乙　Ａ" and yi.film_count == 2
    assert _by_name(db_session, "丙") is None
    assert stale.film_count == 0

    # 再刷新一次不重复建档
    assert ArchiveService().refresh(db_session, strm_roots=[str(root)]) == {"created": 0, "actresses": 3}


def test_refresh_matches_alias_instead_of_creating(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲", aliases=("甲甲",))
    _add_film(db_session, root, "ABC-001", ("甲 甲",))

    result = ArchiveService().refresh(db_session, strm_roots=[str(root)])

    assert result == {"created": 0, "actresses": 1}
    assert jia.film_count == 1


def test_ensure_actresses_returns_in_order_and_creates_missing(db_session):
    jia = _add_actress(db_session, "甲", aliases=("甲甲",))

    actresses = ArchiveService().ensure_actresses(db_session, ["乙", "甲 甲", "乙 "])

    assert [actress.canonical_name for actress in actresses] == ["乙", "甲", "乙"]
    assert actresses[1].id == jia.id
    assert actresses[0].id == actresses[2].id
    assert _count(db_session, Actress) == 2

    with pytest.raises(ActressError):
        ArchiveService().ensure_actresses(db_session, ["丙", "  "])
    assert _by_name(db_session, "丙") is None


def test_set_status_records_mark_only_on_change(db_session):
    jia = _add_actress(db_session, "甲")
    yi = _add_actress(db_session, "乙", status="blacklist")
    item = JellyfinMediaItem(source="strm_115", path="/媒体/甲/ABC-001/ABC-001.strm")
    db_session.add(item)
    db_session.commit()
    service = ArchiveService()

    assert service.set_status(db_session, [jia.id, yi.id], "blacklist", source="web") == 1
    assert service.set_status(db_session, [jia.id, yi.id], "blacklist", source="web") == 0

    marks = db_session.scalars(select(ActressMark)).all()
    assert [(m.actress_id, m.from_status, m.to_status, m.source) for m in marks] == [
        (jia.id, "none", "blacklist", "web")
    ]

    assert service.set_status(db_session, [jia.id], "whitelist", source="player", media_item_id=item.id) == 1
    last = db_session.scalars(select(ActressMark).order_by(ActressMark.id.desc())).first()
    assert (last.from_status, last.to_status, last.source, last.media_item_id) == (
        "blacklist",
        "whitelist",
        "player",
        item.id,
    )
    assert jia.status == "whitelist"

    with pytest.raises(ActressError):
        service.set_status(db_session, [jia.id], "deleted", source="web")
    with pytest.raises(ActressError):
        service.set_status(db_session, [jia.id + 100], "blacklist", source="web")


def test_add_alias_rejects_name_owned_by_other_actress(db_session):
    _add_actress(db_session, "甲", aliases=("甲甲",))
    yi = _add_actress(db_session, "乙")
    service = ArchiveService()

    with pytest.raises(ActressError, match="已属于 甲，请用合并"):
        service.add_alias(db_session, yi.id, "甲")
    with pytest.raises(ActressError, match="已属于 甲，请用合并"):
        service.add_alias(db_session, yi.id, "甲 甲")
    with pytest.raises(ActressError):
        service.add_alias(db_session, yi.id, "乙")
    with pytest.raises(ActressError):
        service.add_alias(db_session, yi.id, " 、 ")
    assert _count(db_session, ActressAlias) == 1


def test_add_and_remove_alias(db_session):
    jia = _add_actress(db_session, "甲")
    yi = _add_actress(db_session, "乙")
    service = ArchiveService()

    alias = service.add_alias(db_session, yi.id, "乙 乙")

    assert (alias.actress_id, alias.alias, alias.alias_normalized) == (yi.id, "乙 乙", "乙乙")
    assert build_name_index(db_session) == {"甲": jia.id, "乙": yi.id, "乙乙": yi.id}

    # 别名不属于这个女优时不能删
    with pytest.raises(ActressError):
        service.remove_alias(db_session, jia.id, alias.id)
    service.remove_alias(db_session, yi.id, alias.id)

    assert _count(db_session, ActressAlias) == 0
    assert build_name_index(db_session) == {"甲": jia.id, "乙": yi.id}


def test_merge_moves_names_and_marks(db_session, tmp_path):
    root = tmp_path / "strm"
    target = _add_actress(db_session, "甲", aliases=("甲甲",))
    source = _add_actress(db_session, "乙", aliases=("乙乙",))
    _add_film(db_session, root, "ABC-001", ("甲",))
    _add_film(db_session, root, "ABC-002", ("乙乙",))
    _add_film(db_session, root, "ABC-003", ("甲", "乙"))
    _add_film(db_session, root, "ABC-004", ("乙",), active=False)
    service = ArchiveService()
    service.set_status(db_session, [source.id], "blacklist", source="web")
    source_id = source.id

    merged = service.merge(db_session, source_id, target.id)

    assert merged.id == target.id
    assert merged.status == "blacklist"
    assert merged.film_count == 3
    assert db_session.get(Actress, source_id) is None
    assert sorted(alias.alias_normalized for alias in merged.aliases) == ["乙", "乙乙", "甲甲"]
    assert build_name_index(db_session) == {"甲": target.id, "甲甲": target.id, "乙": target.id, "乙乙": target.id}
    marks = db_session.scalars(select(ActressMark).order_by(ActressMark.id)).all()
    assert [(m.actress_id, m.from_status, m.to_status, m.source) for m in marks] == [
        (target.id, "none", "blacklist", "web"),
        (target.id, "none", "blacklist", "merge"),
    ]


def test_name_changes_reset_avatar_state(db_session):
    service = ArchiveService()
    first, second = service.ensure_actresses(db_session, ["甲", "乙"])
    db_session.commit()
    for actress in (first, second):
        actress.avatar_state = "uploaded"
    db_session.commit()

    alias = service.add_alias(db_session, first.id, "丙")
    assert first.avatar_state == "pending"

    first.avatar_state = "uploaded"
    db_session.commit()
    service.remove_alias(db_session, first.id, alias.id)
    assert first.avatar_state == "pending"

    first.avatar_state = "not_found"
    db_session.commit()
    target = service.merge(db_session, second.id, first.id)
    assert target.avatar_state == "pending"


def test_merge_rejects_black_and_white(db_session):
    black = _add_actress(db_session, "甲", status="blacklist")
    white = _add_actress(db_session, "乙", status="whitelist")
    service = ArchiveService()

    with pytest.raises(ActressError):
        service.merge(db_session, black.id, white.id)
    with pytest.raises(ActressError):
        service.merge(db_session, white.id, black.id)
    with pytest.raises(ActressError):
        service.merge(db_session, black.id, black.id)

    assert _count(db_session, Actress) == 2
    assert (black.status, white.status) == ("blacklist", "whitelist")
    assert _count(db_session, ActressMark) == 0


def _keyword_snapshot(db_session) -> tuple[list[tuple], list[tuple]]:
    entries = db_session.execute(
        select(KeywordEntry.id, KeywordEntry.canonical_name, KeywordEntry.keyword_type, KeywordEntry.status).order_by(
            KeywordEntry.id
        )
    ).all()
    aliases = db_session.execute(
        select(KeywordAlias.id, KeywordAlias.keyword_entry_id, KeywordAlias.alias).order_by(KeywordAlias.id)
    ).all()
    return [tuple(row) for row in entries], [tuple(row) for row in aliases]


def test_actress_operations_do_not_touch_keyword_entries(db_session, tmp_path):
    root = tmp_path / "strm"
    white = KeywordEntry(canonical_name="甲", canonical_name_normalized="甲", keyword_type="whitelist", status="active")
    white.aliases = [KeywordAlias(alias="甲甲", alias_normalized="甲甲")]
    emby_white = KeywordEntry(
        canonical_name="乙", canonical_name_normalized="乙", keyword_type="emby_whitelist", status="active"
    )
    db_session.add_all([white, emby_white])
    db_session.commit()
    before = _keyword_snapshot(db_session)
    _add_film(db_session, root, "ABC-001", ("甲", "乙", "丙"))
    service = ArchiveService()

    service.refresh(db_session, strm_roots=[str(root)])
    jia, yi, bing = service.ensure_actresses(db_session, ["甲", "乙", "丙"])
    ding = service.ensure_actresses(db_session, ["丁"])[0]
    service.set_status(db_session, [jia.id, yi.id], "whitelist", source="web")
    alias = service.add_alias(db_session, bing.id, "丙丙")
    service.remove_alias(db_session, bing.id, alias.id)
    service.merge(db_session, ding.id, bing.id)

    assert _keyword_snapshot(db_session) == before
    assert _count(db_session, KeywordEntry) == 2
    assert _count(db_session, KeywordAlias) == 1


def test_refresh_refuses_empty_roots(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_film(db_session, root, "ABC-001", ("甲",))
    ArchiveService().refresh(db_session, strm_roots=[str(root)])
    jia = _by_name(db_session, "甲")
    _add_film(db_session, root, "ABC-002", ("乙",))

    # 根目录没配置时一部片都读不到，不能因此把片数清零
    for strm_roots in ([], ["", " "]):
        with pytest.raises(ActressError, match="未配置 115 番号库根目录"):
            ArchiveService().refresh(db_session, strm_roots=strm_roots)

    assert jia.film_count == 1
    assert _by_name(db_session, "乙") is None
    assert _count(db_session, Actress) == 1
