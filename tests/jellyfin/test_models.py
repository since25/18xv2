from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem, JellyfinMediaKeyword
from app.models.keywords import KeywordEntry
from app.services.keywords.registry_service import normalize_keyword_text


def _enable_foreign_keys(db_session):
    db_session.commit()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")


def _entry(db_session):
    entry = KeywordEntry(
        canonical_name="演员甲",
        canonical_name_normalized=normalize_keyword_text("演员甲"),
        keyword_type="whitelist",
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    return entry


def test_media_item_unique_source_path(db_session):
    db_session.add_all(
        [
            JellyfinMediaItem(source="local", path="/媒体/演员甲/a.mp4"),
            JellyfinMediaItem(source="local", path="/媒体/演员甲/a.mp4"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_keyword_delete_cascades_links_and_nulls_collection(db_session):
    _enable_foreign_keys(db_session)
    entry = _entry(db_session)
    item = JellyfinMediaItem(source="local", path="/媒体/演员甲/a.mp4")
    db_session.add(item)
    db_session.flush()
    db_session.add(
        JellyfinMediaKeyword(
            media_item_id=item.id,
            keyword_entry_id=entry.id,
            match_source="folder_segment",
            raw_term="演员甲",
        )
    )
    collection = JellyfinKeywordCollection(
        keyword_entry_id=entry.id,
        jellyfin_collection_id="collection-1",
        canonical_name_snapshot="演员甲",
        status="active",
    )
    db_session.add(collection)
    db_session.commit()

    db_session.delete(entry)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(JellyfinMediaKeyword)) == 0
    db_session.expire(collection)
    assert db_session.get(JellyfinKeywordCollection, collection.id).keyword_entry_id is None
