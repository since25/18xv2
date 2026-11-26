from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem, JellyfinMediaKeyword
from app.models.keywords import KeywordEntry
from app.services.jellyfin.scan_service import MediaScanError, MediaScanService
from app.services.keywords.registry_service import normalize_keyword_text


def _add_entry(db_session, canonical_name: str, *, status: str = "active") -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=canonical_name,
        canonical_name_normalized=normalize_keyword_text(canonical_name),
        keyword_type="whitelist",
        status=status,
    )
    db_session.add(entry)
    db_session.flush()
    return entry


def _write_media(path: Path, content: str = "media") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _nfo_with_actors(*names: str) -> str:
    actors = "".join(f"<actor><name>{name}</name></actor>" for name in names)
    return f"<movie>{actors}</movie>"


def _actor_rows(db_session, item_id: int) -> list[tuple[int, str, str]]:
    rows = db_session.scalars(
        select(JellyfinMediaActor)
        .where(JellyfinMediaActor.media_item_id == item_id)
        .order_by(JellyfinMediaActor.position)
    ).all()
    return [(row.position, row.raw_name, row.name_normalized) for row in rows]


def test_scan_local_combo_and_video_filter(db_session, tmp_path):
    root = tmp_path / "local"
    _write_media(root / "演员甲__演员乙" / "包1" / "a.mp4")
    _write_media(root / "演员甲__演员乙" / "包1" / "cover.jpg")
    _write_media(root / "演员甲__演员乙" / "包1" / "a.nfo")
    first = _add_entry(db_session, "演员甲")
    second = _add_entry(db_session, "演员乙")

    result = MediaScanService().scan(db_session, local_roots=[str(root)], strm_roots=[])

    assert result["local_files"] == 1
    assert result["strm_files"] == 0
    assert result["matched"] == 1
    assert result["unmatched"] == 0
    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(root / "演员甲__演员乙" / "包1" / "a.mp4")))
    assert item is not None
    assert {link.keyword_entry_id for link in item.keyword_links} == {first.id, second.id}
    assert {link.match_source for link in item.keyword_links} == {"folder_segment"}


def test_scan_strm_with_nfo_actor(db_session, tmp_path):
    root = tmp_path / "strm"
    strm_path = root / "演员乙" / "ABC-001" / "ABC-001.strm"
    _write_media(strm_path, "http://jellyfin.test/ABC-001")
    _write_media(strm_path.with_suffix(".nfo"), "<movie><actor><name>演员甲</name></actor></movie>")
    actor = _add_entry(db_session, "演员甲")
    _add_entry(db_session, "演员乙")

    result = MediaScanService().scan(db_session, local_roots=[], strm_roots=[str(root)])

    assert result["strm_files"] == 1
    assert result["matched"] == 1
    assert result["nfo_error"] == 0
    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(strm_path)))
    assert item is not None
    assert [(link.keyword_entry_id, link.match_source) for link in item.keyword_links] == [(actor.id, "nfo_actor")]


def test_scan_strm_bad_nfo_marks_error(db_session, tmp_path):
    root = tmp_path / "strm"
    strm_path = root / "演员乙" / "ABC-001" / "ABC-001.strm"
    _write_media(strm_path, "http://jellyfin.test/ABC-001")
    _write_media(strm_path.with_suffix(".nfo"), "<movie><actor>")
    folder_entry = _add_entry(db_session, "演员乙")

    result = MediaScanService().scan(db_session, local_roots=[], strm_roots=[str(root)])

    assert result["nfo_error"] == 1
    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(strm_path)))
    assert item is not None
    assert item.match_state == "nfo_error"
    assert [(link.keyword_entry_id, link.match_source) for link in item.keyword_links] == [
        (folder_entry.id, "folder_fallback")
    ]


def test_scan_unmatched_recorded(db_session, tmp_path):
    root = tmp_path / "local"
    media_path = root / "未收录目录" / "a.mp4"
    _write_media(media_path)
    _add_entry(db_session, "演员甲")

    result = MediaScanService().scan(db_session, local_roots=[str(root)], strm_roots=[])

    assert result["unmatched"] == 1
    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(media_path)))
    assert item is not None
    assert item.match_state == "unmatched"
    assert item.keyword_links == []


def test_rescan_deactivates_missing_and_rematches(db_session, tmp_path):
    root = tmp_path / "local"
    first_path = root / "演员甲" / "a.mp4"
    removed_path = root / "演员甲" / "b.mp4"
    _write_media(first_path)
    _write_media(removed_path)
    entry = _add_entry(db_session, "演员甲")

    MediaScanService().scan(db_session, local_roots=[str(root)], strm_roots=[], job_id="scan-1")
    removed_path.unlink()
    entry.status = "inactive"
    db_session.commit()

    result = MediaScanService().scan(db_session, local_roots=[str(root)], strm_roots=[], job_id="scan-2")

    removed_item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(removed_path)))
    remaining_item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(first_path)))
    assert removed_item is not None and removed_item.active is False
    assert remaining_item is not None and remaining_item.active is True
    assert remaining_item.match_state == "unmatched"
    assert remaining_item.keyword_links == []
    assert result["deactivated"] == 1


def test_scan_missing_root_fails_without_deactivating(db_session, tmp_path):
    root = tmp_path / "local"
    media_path = root / "演员甲" / "a.mp4"
    _write_media(media_path)
    _add_entry(db_session, "演员甲")
    service = MediaScanService()
    service.scan(db_session, local_roots=[str(root)], strm_roots=[], job_id="scan-1")

    missing_root = tmp_path / "missing"
    with pytest.raises(MediaScanError):
        service.scan(db_session, local_roots=[str(missing_root)], strm_roots=[], job_id="scan-2")

    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(media_path)))
    assert item is not None and item.active is True


def test_scan_batches_commit(db_session, tmp_path):
    root = tmp_path / "local"
    for index in range(5):
        _write_media(root / "演员甲" / f"{index}.mp4")
    _add_entry(db_session, "演员甲")

    result = MediaScanService().scan(db_session, local_roots=[str(root)], strm_roots=[], batch_size=2)

    assert result["local_files"] == 5
    assert result["matched"] == 5
    assert db_session.query(JellyfinMediaItem).count() == 5


def test_scan_saves_nfo_actors_in_order(db_session, tmp_path):
    root = tmp_path / "strm"
    strm_path = root / "甲" / "ABC-001" / "ABC-001.strm"
    _write_media(strm_path, "http://jellyfin.test/ABC-001")
    _write_media(strm_path.with_suffix(".nfo"), _nfo_with_actors("甲", "乙　Ａ"))

    MediaScanService().scan(db_session, local_roots=[], strm_roots=[str(root)])

    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(strm_path)))
    assert item is not None
    assert _actor_rows(db_session, item.id) == [
        (0, "甲", "甲"),
        (1, "乙　Ａ", "乙A"),
    ]


def test_scan_replaces_actor_rows_on_rescan(db_session, tmp_path):
    root = tmp_path / "strm"
    strm_path = root / "甲" / "ABC-001" / "ABC-001.strm"
    _write_media(strm_path, "http://jellyfin.test/ABC-001")
    _write_media(strm_path.with_suffix(".nfo"), _nfo_with_actors("甲", "乙"))
    service = MediaScanService()
    service.scan(db_session, local_roots=[], strm_roots=[str(root)], job_id="scan-1")

    _write_media(strm_path.with_suffix(".nfo"), _nfo_with_actors("乙"))
    service.scan(db_session, local_roots=[], strm_roots=[str(root)], job_id="scan-2")

    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(strm_path)))
    assert item is not None
    assert _actor_rows(db_session, item.id) == [(0, "乙", "乙")]
    assert db_session.query(JellyfinMediaActor).count() == 1


def test_scan_keeps_first_of_duplicate_actor_names(db_session, tmp_path):
    root = tmp_path / "strm"
    strm_path = root / "甲" / "ABC-001" / "ABC-001.strm"
    _write_media(strm_path, "http://jellyfin.test/ABC-001")
    _write_media(strm_path.with_suffix(".nfo"), _nfo_with_actors("甲 甲", "乙", "甲甲"))

    MediaScanService().scan(db_session, local_roots=[], strm_roots=[str(root)])

    item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(strm_path)))
    assert item is not None
    assert _actor_rows(db_session, item.id) == [
        (0, "甲 甲", "甲甲"),
        (1, "乙", "乙"),
    ]


def test_scan_no_actor_rows_when_nfo_missing_or_broken(db_session, tmp_path):
    strm_root = tmp_path / "strm"
    missing_path = strm_root / "甲" / "ABC-001" / "ABC-001.strm"
    broken_path = strm_root / "甲" / "ABC-002" / "ABC-002.strm"
    _write_media(missing_path, "http://jellyfin.test/ABC-001")
    _write_media(broken_path, "http://jellyfin.test/ABC-002")
    _write_media(broken_path.with_suffix(".nfo"), "<movie><actor>")
    local_root = tmp_path / "local"
    local_path = local_root / "甲" / "ABC-003" / "ABC-003.mp4"
    _write_media(local_path)
    _write_media(local_path.with_suffix(".nfo"), _nfo_with_actors("甲"))

    result = MediaScanService().scan(db_session, local_roots=[str(local_root)], strm_roots=[str(strm_root)])

    assert result["strm_files"] == 2
    assert result["local_files"] == 1
    assert result["nfo_error"] == 1
    missing_item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(missing_path)))
    broken_item = db_session.scalar(select(JellyfinMediaItem).where(JellyfinMediaItem.path == str(broken_path)))
    assert missing_item is not None and missing_item.match_state == "unmatched"
    assert broken_item is not None and broken_item.match_state == "nfo_error"
    assert db_session.query(JellyfinMediaActor).count() == 0
