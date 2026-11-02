from __future__ import annotations

from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.jellyfin.matcher import (
    build_keyword_index,
    match_local_folder,
    match_strm_item,
    split_folder_terms,
)
from app.services.keywords.registry_service import normalize_keyword_text


def _add_entry(
    db_session,
    canonical_name: str,
    *,
    keyword_type: str = "whitelist",
    status: str = "active",
    alias: str | None = None,
    alias_normalized: str | None = None,
):
    entry = KeywordEntry(
        canonical_name=canonical_name,
        canonical_name_normalized=normalize_keyword_text(canonical_name),
        keyword_type=keyword_type,
        status=status,
    )
    db_session.add(entry)
    db_session.flush()
    if alias is not None:
        db_session.add(
            KeywordAlias(
                keyword_entry_id=entry.id,
                alias=alias,
                alias_normalized=alias_normalized or normalize_keyword_text(alias),
            )
        )
        db_session.flush()
    return entry


def test_split_double_underscore_only():
    assert split_folder_terms("演员甲__演员乙") == ["演员甲", "演员乙"]
    assert split_folder_terms("演员甲_演员乙") == ["演员甲_演员乙"]
    assert "" not in split_folder_terms("演员甲____演员乙")


def test_index_only_active_whitelist(db_session):
    allowed = _add_entry(db_session, "演员甲", alias="关键词乙")
    _add_entry(db_session, "演员丙", keyword_type="blacklist", alias="关键词丙")
    _add_entry(db_session, "演员丁", status="inactive", alias="关键词丁")

    assert build_keyword_index(db_session) == {
        "演员甲": allowed.id,
        "关键词乙": allowed.id,
    }


def test_index_drops_ambiguous_text(db_session):
    _add_entry(db_session, "演员甲", alias="共享词")
    _add_entry(db_session, "演员乙", alias="共享词", alias_normalized="共享词-2")

    index = build_keyword_index(db_session)

    assert "共享词" not in index


def test_match_local_combo():
    index = {"演员甲": 1, "演员乙": 2}

    assert match_local_folder("演员甲__演员乙", index) == [(1, "演员甲"), (2, "演员乙")]


def test_strm_actor_hit_no_fallback():
    index = {"演员甲": 1, "演员乙": 2}

    matches, state = match_strm_item(["演员甲", "未知"], "演员乙", index)

    assert matches == [(1, "演员甲", "nfo_actor")]
    assert state == "matched"


def test_strm_fallback_when_no_actor_hit():
    matches, state = match_strm_item(["未知"], "演员乙", {"演员乙": 2})

    assert matches == [(2, "演员乙", "folder_fallback")]
    assert state == "matched"


def test_strm_nfo_error_still_fallback():
    index = {"演员乙": 2}

    matches, state = match_strm_item(None, "演员乙", index)
    assert matches == [(2, "演员乙", "folder_fallback")]
    assert state == "nfo_error"

    matches, state = match_strm_item(None, "未知", index)
    assert matches == []
    assert state == "nfo_error"


def test_strm_unmatched():
    assert match_strm_item(["未知"], "未收录", {}) == ([], "unmatched")
