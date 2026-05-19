from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.whitelist import WhitelistCandidate
from app.models.keywords import KeywordEntry


def _make_keyword(db, name="演员A"):
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type="whitelist",
        status="active",
    )
    db.add(entry)
    db.commit()
    return entry


def test_whitelist_candidate_can_be_created(db_session):
    entry = _make_keyword(db_session)
    cand = WhitelistCandidate(
        source_tid=12345,
        source_magnet="magnet:?xt=urn:btih:abc",
        source_title="测试资源",
        matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name,
        match_score=0.95,
        duplicate_status="clear",
        target_path="/已整理/演员A/测试资源",
        lifecycle_status="pending",
    )
    db_session.add(cand)
    db_session.commit()
    assert cand.id is not None
    assert cand.first_seen_at is not None
    assert cand.last_scanned_at is not None


def test_whitelist_candidate_unique_per_tid_magnet_keyword(db_session):
    """同一 (tid, magnet, keyword_id) 不能存两行；换 keyword 可以。"""
    entry_a = _make_keyword(db_session, "演员A")
    entry_b = _make_keyword(db_session, "演员B")

    def _new(entry):
        return WhitelistCandidate(
            source_tid=999,
            source_magnet="magnet:?xt=urn:btih:same",
            source_title="t",
            matched_keyword_entry_id=entry.id,
            matched_keyword=entry.canonical_name,
            duplicate_status="clear",
            target_path="/x",
        )

    db_session.add(_new(entry_a))
    db_session.commit()

    # 同 (tid, magnet, keyword) → IntegrityError
    db_session.add(_new(entry_a))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 换 keyword → OK
    db_session.add(_new(entry_b))
    db_session.commit()
