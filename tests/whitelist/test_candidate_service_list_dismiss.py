from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordEntry
from app.models.whitelist import WhitelistCandidate
from app.services.whitelist.candidate_service import WhitelistCandidateService


def _make_entry(db, name="A"):
    e = KeywordEntry(
        canonical_name=name, canonical_name_normalized=name.lower(),
        keyword_type="whitelist", status="active",
    )
    db.add(e)
    db.commit()
    return e


def _make_cand(db, entry, *, tid, lifecycle="pending", dup="clear", score=0.5):
    c = WhitelistCandidate(
        source_tid=tid, source_magnet=f"m{tid}", source_title=f"r{tid}",
        matched_keyword_entry_id=entry.id, matched_keyword=entry.canonical_name,
        match_score=score, duplicate_status=dup, target_path="/x",
        lifecycle_status=lifecycle,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_list_candidates_filters_by_lifecycle(db_session):
    e = _make_entry(db_session)
    _make_cand(db_session, e, tid=1, lifecycle="pending")
    _make_cand(db_session, e, tid=2, lifecycle="submitted")
    _make_cand(db_session, e, tid=3, lifecycle="dismissed")

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status="pending", matched_keyword_entry_id=None,
        duplicate_status=None, search=None, page=1, page_size=100,
    )
    assert total == 1
    assert items[0].source_tid == 1


def test_list_candidates_filters_by_keyword_and_duplicate(db_session):
    e1 = _make_entry(db_session, "A")
    e2 = _make_entry(db_session, "B")
    _make_cand(db_session, e1, tid=1, dup="clear")
    _make_cand(db_session, e1, tid=2, dup="duplicate_found")
    _make_cand(db_session, e2, tid=3, dup="clear")

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=e1.id,
        duplicate_status="clear", search=None, page=1, page_size=100,
    )
    assert total == 1
    assert items[0].source_tid == 1


def test_list_candidates_search_matches_title_or_keyword(db_session):
    e = _make_entry(db_session, "演员A")
    _make_cand(db_session, e, tid=1)  # title r1
    _make_cand(db_session, e, tid=99)  # title r99

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=None,
        duplicate_status=None, search="r99", page=1, page_size=100,
    )
    assert total == 1
    assert items[0].source_tid == 99


def test_list_candidates_paginates(db_session):
    e = _make_entry(db_session)
    for i in range(25):
        _make_cand(db_session, e, tid=i)

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=None,
        duplicate_status=None, search=None, page=2, page_size=10,
    )
    assert total == 25
    assert len(items) == 10


def test_list_candidates_orders_by_score_desc(db_session):
    e = _make_entry(db_session)
    _make_cand(db_session, e, tid=1, score=0.3)
    _make_cand(db_session, e, tid=2, score=0.9)
    _make_cand(db_session, e, tid=3, score=0.6)

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, _ = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=None,
        duplicate_status=None, search=None, page=1, page_size=100,
    )
    scores = [i.match_score for i in items]
    assert scores == sorted(scores, reverse=True)


def test_dismiss_pending_candidate(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="pending")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.dismiss(candidate_id=c.id, reason="误匹配")
    db_session.refresh(c)
    assert c.lifecycle_status == "dismissed"
    assert c.dismissed_at is not None


def test_dismiss_submitted_candidate_raises(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="submitted")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="已提交"):
        svc.dismiss(candidate_id=c.id, reason=None)


def test_dismiss_nonexistent_raises_lookup_error(db_session):
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(LookupError):
        svc.dismiss(candidate_id=9999, reason=None)


def test_restore_dismissed_candidate(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="dismissed")
    c.dismissed_at = datetime.now(UTC)
    db_session.commit()
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.restore(candidate_id=c.id)
    db_session.refresh(c)
    assert c.lifecycle_status == "pending"
    assert c.dismissed_at is None


def test_restore_failed_candidate_clears_failure_reason(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="failed")
    c.failure_reason = "old error"
    db_session.commit()
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.restore(candidate_id=c.id)
    db_session.refresh(c)
    assert c.lifecycle_status == "pending"
    assert c.failure_reason is None


def test_restore_submitted_candidate_raises(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="submitted")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="已提交"):
        svc.restore(candidate_id=c.id)


def test_restore_pending_candidate_raises(db_session):
    """pending -> restore 没意义，应报错。"""
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="pending")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="不能 restore"):
        svc.restore(candidate_id=c.id)
