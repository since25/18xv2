"""WhitelistCandidateService.scan() 的单测。

设计要点：
- 同 (tid, magnet) 不同 keyword 各占一行
- 低成本状态（submitted/dismissed/task_exists）跳过，只刷 last_scanned_at
- 高成本状态（clear/duplicate_found）重新评估
- 每关键词一 commit；单关键词失败不阻断 job
"""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordEntry
from app.models.tree import TreeImport
from app.models.whitelist import WhitelistCandidate
from app.schemas.magnet_tasks import ArticleCandidateResponse
from app.services.magnet_download_service import DuplicateCheckResult
from app.services.whitelist.candidate_service import WhitelistCandidateService


def _to_naive(dt):
    """SQLite 读 DateTime(timezone=True) 列时返回 naive UTC；比较前统一去掉 tzinfo 以兼容两种数据库。"""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _make_entry(db, name="演员A"):
    e = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type="whitelist",
        status="active",
    )
    db.add(e)
    db.commit()
    return e


def _make_tree(db):
    t = TreeImport(source_filename="t", source_type="manual", status="completed")
    db.add(t)
    db.commit()
    return t


def _fake_article(tid, title="t", magnet=None, keyword="演员A"):
    return ArticleCandidateResponse(
        source_tid=tid,
        source_title=title,
        source_magnet=magnet or f"magnet:?xt=urn:btih:{tid}",
        source_detail_url=f"https://x/{tid}",
        source_section="release",
        source_category=None,
        source_sub_type=None,
        source_size=None,
        matched_keyword=keyword,
        matched_alias=None,
        match_score=0.9,
    )


def _dup_clear():
    return DuplicateCheckResult(
        status="clear", reason=None,
        search_terms=[], matched_terms=[],
        matched_import_id=None, matched_import_label=None,
        matched_nodes=[],
    )


def _dup_found(import_id=1, label="#1"):
    return DuplicateCheckResult(
        status="duplicate_found", reason="本地命中",
        search_terms=[], matched_terms=[],
        matched_import_id=import_id, matched_import_label=label,
        matched_nodes=[],
    )


def _make_service(db, *, candidates_per_entry: dict[int, list], dup_result):
    magnet_svc = MagicMock()
    def fake_build(*, keyword_entry, limit):
        return candidates_per_entry.get(keyword_entry.id, [])
    magnet_svc.build_candidates_for_keyword_entry.side_effect = fake_build
    magnet_svc._check_single_duplicate.return_value = dup_result
    magnet_svc._build_target_path.side_effect = (
        lambda *, keyword_dir, source_title: f"/已整理/{keyword_dir}/{source_title}"
    )
    return WhitelistCandidateService(db, magnet_svc=magnet_svc), magnet_svc


def test_scan_first_run_inserts_new_candidates(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    svc, _ = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(1), _fake_article(2)]},
        dup_result=_dup_clear(),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.new == 2
    assert summary.updated == 0
    rows = db_session.scalars(select(WhitelistCandidate)).all()
    assert len(rows) == 2
    assert all(r.lifecycle_status == "pending" for r in rows)
    assert all(r.duplicate_status == "clear" for r in rows)
    assert all(r.last_scanned_tree_import_id == tree.id for r in rows)


def test_scan_two_keywords_match_same_magnet_produces_two_rows(db_session):
    entry_a = _make_entry(db_session, "演员A")
    entry_b = _make_entry(db_session, "演员B")
    tree = _make_tree(db_session)
    svc, _ = _make_service(
        db_session,
        candidates_per_entry={
            entry_a.id: [_fake_article(7, keyword="演员A")],
            entry_b.id: [_fake_article(7, keyword="演员B")],
        },
        dup_result=_dup_clear(),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry_a.id, entry_b.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.new == 2
    rows = db_session.scalars(select(WhitelistCandidate)).all()
    assert len(rows) == 2
    assert {r.matched_keyword_entry_id for r in rows} == {entry_a.id, entry_b.id}


def test_scan_second_run_skips_submitted_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    earlier = datetime.now(UTC) - timedelta(days=1)
    db_session.add(WhitelistCandidate(
        source_tid=42, source_magnet="magnet:?xt=urn:btih:42",
        source_title="老资源", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="submitted",
        last_scanned_at=_to_naive(earlier),
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(42)]},
        dup_result=_dup_clear(),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    assert summary.new == 0
    assert summary.updated == 0
    magnet_svc._check_single_duplicate.assert_not_called()

    row = db_session.scalar(select(WhitelistCandidate))
    assert row.lifecycle_status == "submitted"
    assert _to_naive(row.last_scanned_at) > _to_naive(earlier)


def test_scan_second_run_skips_dismissed_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    earlier = datetime.now(UTC) - timedelta(days=1)
    db_session.add(WhitelistCandidate(
        source_tid=99, source_magnet="magnet:?xt=urn:btih:99",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="dismissed",
        last_scanned_at=_to_naive(earlier),
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(99)]},
        dup_result=_dup_clear(),
    )
    summary = svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    magnet_svc._check_single_duplicate.assert_not_called()
    row = db_session.scalar(select(WhitelistCandidate))
    assert _to_naive(row.last_scanned_at) > _to_naive(earlier)


def test_scan_skips_task_exists_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=11, source_magnet="magnet:?xt=urn:btih:11",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name,
        duplicate_status="task_exists", target_path="/x",
        lifecycle_status="pending",
    ))
    db_session.commit()
    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(11)]},
        dup_result=_dup_clear(),
    )
    summary = svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    magnet_svc._check_single_duplicate.assert_not_called()


def test_scan_re_evaluates_clear_status(db_session):
    """已存在 clear 候选，重扫应重新调 _check_single_duplicate。"""
    entry = _make_entry(db_session, "演员A")
    tree_a = _make_tree(db_session)
    tree_b = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=5, source_magnet="magnet:?xt=urn:btih:5",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="pending",
        last_scanned_tree_import_id=tree_a.id,
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(5)]},
        dup_result=_dup_found(import_id=tree_b.id, label=f"#{tree_b.id}"),
    )
    summary = svc.scan(
        tree_import_id=tree_b.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.updated == 1
    magnet_svc._check_single_duplicate.assert_called_once()
    row = db_session.scalar(select(WhitelistCandidate))
    assert row.duplicate_status == "duplicate_found"
    assert row.last_scanned_tree_import_id == tree_b.id


def test_scan_keyword_failure_does_not_abort_job(db_session):
    entry_ok = _make_entry(db_session, "OK")
    entry_bad = _make_entry(db_session, "BAD")
    tree = _make_tree(db_session)

    magnet_svc = MagicMock()
    def fake_build(*, keyword_entry, limit):
        if keyword_entry.id == entry_bad.id:
            raise RuntimeError("外部库挂了")
        return [_fake_article(1)]
    magnet_svc.build_candidates_for_keyword_entry.side_effect = fake_build
    magnet_svc._check_single_duplicate.return_value = _dup_clear()
    magnet_svc._build_target_path.side_effect = (
        lambda *, keyword_dir, source_title: "/x"
    )
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry_ok.id, entry_bad.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.new == 1
    assert summary.failed_keywords == 1
    assert summary.scanned_keywords == 2


def test_target_path_recomputed_when_keyword_renamed_between_scans(db_session):
    entry = _make_entry(db_session, "原名")
    tree = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=3, source_magnet="magnet:?xt=urn:btih:3",
        source_title="r", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/已整理/原名/r", lifecycle_status="pending",
    ))
    db_session.commit()

    entry.canonical_name = "新名"
    db_session.commit()

    svc, _ = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(3, title="r")]},
        dup_result=_dup_clear(),
    )
    svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    row = db_session.scalar(select(WhitelistCandidate))
    assert "新名" in row.target_path


def test_scan_progress_cb_called_per_keyword(db_session):
    e1 = _make_entry(db_session, "A")
    e2 = _make_entry(db_session, "B")
    tree = _make_tree(db_session)
    calls = []
    svc, _ = _make_service(
        db_session,
        candidates_per_entry={e1.id: [_fake_article(1)], e2.id: [_fake_article(2)]},
        dup_result=_dup_clear(),
    )
    svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[e1.id, e2.id],
        per_keyword_limit=10,
        progress_cb=lambda stage, c, t: calls.append((stage, c, t)),
    )
    # 1 个加载 + 2 个扫描
    scan_calls = [c for c in calls if c[0] == "扫描外部库"]
    assert len(scan_calls) == 2
    assert scan_calls[0] == ("扫描外部库", 1, 2)
    assert scan_calls[1] == ("扫描外部库", 2, 2)
