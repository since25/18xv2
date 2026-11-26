from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import ActressDeleteCandidate, ActressKeptFilm, JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.archive_service import ActressError, ArchiveService
from app.services.actresses.candidates_service import CandidateService, CandidateView
from app.services.actresses.names import normalize_actress_name


def _add_film(db_session, root: Path, number: str, actors: tuple[str, ...], *, actor_dir: str = "甲") -> str:
    """插入一部单段片子（一个 115 STRM 条目和它的 NFO 演员行），返回番号目录。"""
    film_dir = root / actor_dir / number
    item = JellyfinMediaItem(source="strm_115", path=str(film_dir / f"{number}.strm"), active=True)
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
    return str(film_dir)


def _set_status(db_session, name: str, status: str) -> None:
    actress = ArchiveService().ensure_actresses(db_session, [name])[0]
    ArchiveService().set_status(db_session, [actress.id], status, source="web")


def _candidates(db_session) -> dict[str, ActressDeleteCandidate]:
    rows = db_session.scalars(select(ActressDeleteCandidate)).all()
    return {row.film_dir: row for row in rows}


def _setup(db_session, tmp_path) -> tuple[list[str], list[str]]:
    """甲、乙合演 ABC-001，甲单独 ABC-002，乙单独 ABC-003；拉黑甲。"""
    root = tmp_path / "strm"
    dirs = [
        _add_film(db_session, root, "ABC-001", ("甲", "乙")),
        _add_film(db_session, root, "ABC-002", ("甲",)),
        _add_film(db_session, root, "ABC-003", ("乙",), actor_dir="乙"),
    ]
    _set_status(db_session, "甲", "blacklist")
    return [str(root)], dirs


def test_reconcile_adds_selected_and_reports_counts(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()

    assert service.reconcile(db_session, strm_roots=strm_roots, added_by="mark") == (2, 0)

    rows = _candidates(db_session)
    assert sorted(rows) == [dirs[0], dirs[1]]
    for row in rows.values():
        assert row.selected is True
        assert row.added_by == "mark"
        assert row.remote_state == "unchecked"
    # 再算一次没有变化
    assert service.reconcile(db_session, strm_roots=strm_roots, added_by="mark") == (0, 0)


def test_reconcile_keeps_unchecked_state(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")

    assert service.set_selected(db_session, [dirs[0]], False) == 1
    assert service.reconcile(db_session, strm_roots=strm_roots, added_by="daily") == (0, 0)

    rows = _candidates(db_session)
    assert len(rows) == 2
    assert rows[dirs[0]].selected is False
    # 已在清单里的片子保持原来的加入方式
    assert rows[dirs[0]].added_by == "mark"
    assert rows[dirs[1]].selected is True

    assert service.set_selected(db_session, [dirs[0], dirs[1], dirs[2]], True) == 2
    assert all(row.selected for row in _candidates(db_session).values())


def test_reconcile_removes_when_costar_whitelisted(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")

    _set_status(db_session, "乙", "whitelist")

    assert service.reconcile(db_session, strm_roots=strm_roots, added_by="mark") == (0, 1)
    assert sorted(_candidates(db_session)) == [dirs[1]]


def test_keep_removes_and_daily_does_not_readd(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")

    # 末尾多一个斜杠也算同一个番号目录
    assert service.keep(db_session, [dirs[0] + "/"]) == 1

    assert sorted(_candidates(db_session)) == [dirs[1]]
    assert db_session.scalars(select(ActressKeptFilm.film_dir)).all() == [dirs[0]]
    assert service.reconcile(db_session, strm_roots=strm_roots, added_by="daily") == (0, 0)
    assert sorted(_candidates(db_session)) == [dirs[1]]


def test_unkeep_puts_film_back(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")
    service.keep(db_session, [dirs[0]])

    assert service.unkeep(db_session, [dirs[0]], strm_roots=strm_roots) == 1

    assert db_session.scalars(select(ActressKeptFilm)).all() == []
    row = _candidates(db_session)[dirs[0]]
    assert row.selected is True
    assert row.added_by == "mark"


def test_list_shows_reason_and_costars(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    Path(dirs[0]).mkdir(parents=True)
    Path(dirs[0], "ABC-001.nfo").write_text("<movie><title>标题甲</title></movie>", encoding="utf-8")
    later_dir = _add_film(db_session, Path(strm_roots[0]), "ABC-000", ("甲", "丙"))
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")
    rows = _candidates(db_session)
    for film_dir in dirs[:2]:
        rows[film_dir].added_at = datetime(2026, 11, 25, 8, 0, 0)
    rows[later_dir].added_at = datetime(2026, 11, 25, 9, 0, 0)
    rows[later_dir].added_by = "daily"
    db_session.commit()

    views = service.list(db_session, strm_roots=strm_roots)

    # 先按加入时间倒序，同一时间按番号
    assert [view.number for view in views] == ["ABC-000", "ABC-001", "ABC-002"]
    assert views[1] == CandidateView(
        film_dir=dirs[0],
        number="ABC-001",
        title="标题甲",
        selected=True,
        added_by="mark",
        added_at=datetime(2026, 11, 25, 8, 0, 0),
        black_names=["甲"],
        other_actors=[("乙", "none")],
        remote_state="unchecked",
        remote_note=None,
    )
    assert views[2].title is None
    assert views[2].other_actors == []
    # 没有档案的演员按未标显示
    assert views[0].other_actors == [("丙", "none")]


def test_empty_roots_refuse_to_change_candidates(db_session, tmp_path):
    strm_roots, dirs = _setup(db_session, tmp_path)
    service = CandidateService()
    service.reconcile(db_session, strm_roots=strm_roots, added_by="mark")
    service.set_selected(db_session, [dirs[0]], False)
    third = _add_film(db_session, Path(strm_roots[0]), "ABC-004", ("甲",))
    service.keep(db_session, [third])

    # 根目录没配置时一部片都读不到，不能因此清空清单或撤销保留
    for empty_roots in ([], ["", " "]):
        with pytest.raises(ActressError, match="未配置 115 番号库根目录"):
            service.reconcile(db_session, strm_roots=empty_roots, added_by="daily")
        with pytest.raises(ActressError, match="未配置 115 番号库根目录"):
            service.unkeep(db_session, [third], strm_roots=empty_roots)

    rows = _candidates(db_session)
    assert sorted(rows) == [dirs[0], dirs[1]]
    assert rows[dirs[0]].selected is False
    assert rows[dirs[1]].selected is True
    assert db_session.scalars(select(ActressKeptFilm.film_dir)).all() == [third]
