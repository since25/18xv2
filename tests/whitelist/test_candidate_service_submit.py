from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, text

from app.models.keywords import KeywordEntry
from app.models.tasks import MagnetDownloadTask
from app.models.whitelist import WhitelistCandidate
from app.services.whitelist.candidate_service import WhitelistCandidateService


def _make_entry(db, name="演员A"):
    e = KeywordEntry(
        canonical_name=name, canonical_name_normalized=name.lower(),
        keyword_type="whitelist", status="active",
    )
    db.add(e)
    db.commit()
    return e


def _make_candidate(db, entry, *, lifecycle="pending", tid=1, score=0.9):
    c = WhitelistCandidate(
        source_tid=tid, source_magnet=f"magnet:?xt=urn:btih:{tid}",
        source_title=f"r{tid}", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, match_score=score,
        duplicate_status="clear", target_path=f"/已整理/{entry.canonical_name}/r{tid}",
        lifecycle_status=lifecycle,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_task(tid, status, *, task_id=None, failure_reason=None):
    """构造一个 MagnetDownloadTask 实例（不入 DB），模拟 create_and_submit_tasks 返回。"""
    t = MagnetDownloadTask(
        source_tid=tid, source_title=f"r{tid}", source_magnet=f"magnet:?xt=urn:btih:{tid}",
        duplicate_status="clear", status=status,
    )
    if task_id is not None:
        t.id = task_id
    if failure_reason is not None:
        t.failure_reason = failure_reason
    return t


def test_submit_creates_magnet_task_and_links(db_session):
    entry = _make_entry(db_session)
    cand = _make_candidate(db_session, entry)

    magnet_svc = MagicMock()
    magnet_svc.create_and_submit_tasks.return_value = [_make_task(1, "submitted", task_id=999)]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[cand.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    assert summary.submitted == 1
    assert summary.failed == 0
    assert summary.skipped == 0

    db_session.refresh(cand)
    assert cand.lifecycle_status == "submitted"
    assert cand.magnet_task_id == 999
    assert cand.submitted_at is not None


def test_submit_handles_single_failure_continues(db_session):
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    failed = _make_task(1, "failed", task_id=11, failure_reason="boom")
    submitted = _make_task(2, "submitted", task_id=22)
    magnet_svc.create_and_submit_tasks.side_effect = [[failed], [submitted]]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    assert summary.submitted == 1
    assert summary.failed == 1
    db_session.refresh(c1)
    db_session.refresh(c2)
    assert c1.lifecycle_status == "failed"
    assert c1.failure_reason == "boom"
    assert c2.lifecycle_status == "submitted"


def test_submit_rolls_back_on_create_and_submit_failure(db_session):
    """模拟 create_and_submit_tasks 内部抛异常（session 已 failed 状态）"""
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    success = _make_task(2, "submitted", task_id=22)

    call_count = {"n": 0}
    def fake_create(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 模拟内部 flush/commit 把 session 标 failed
            db_session.execute(text("SELECT * FROM nonexistent_xyz"))
        return [success]
    magnet_svc.create_and_submit_tasks.side_effect = fake_create
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    # c1 失败但 c2 必须能继续 → 验证 rollback 路径生效
    assert summary.submitted == 1
    assert summary.failed == 1


def test_submit_skips_non_pending_candidates(db_session):
    entry = _make_entry(db_session)
    c_dis = _make_candidate(db_session, entry, tid=1, lifecycle="dismissed")
    c_sub = _make_candidate(db_session, entry, tid=2, lifecycle="submitted")

    magnet_svc = MagicMock()
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)
    summary = svc.submit_selected(
        candidate_ids=[c_dis.id, c_sub.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    assert summary.skipped == 2
    assert summary.submitted == 0
    magnet_svc.create_and_submit_tasks.assert_not_called()


def test_submit_uses_none_tree_import_id_when_candidate_never_scanned(db_session):
    """last_scanned_tree_import_id 为 None 时 create_and_submit_tasks 收到 None。"""
    entry = _make_entry(db_session)
    cand = _make_candidate(db_session, entry)
    cand.last_scanned_tree_import_id = None
    db_session.commit()

    magnet_svc = MagicMock()
    magnet_svc.create_and_submit_tasks.return_value = [_make_task(1, "submitted", task_id=1)]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)
    svc.submit_selected(
        candidate_ids=[cand.id], force_submit=False, progress_cb=lambda *a: None,
    )
    call = magnet_svc.create_and_submit_tasks.call_args
    assert call.kwargs["tree_import_id"] is None


def test_submit_refreshes_cand_before_acting(db_session):
    """循环开始后 cand 在外部被改成 dismissed，submit 应跳过。"""
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    magnet_svc.create_and_submit_tasks.return_value = [_make_task(1, "submitted", task_id=11)]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    # 模拟并发：第二轮 progress_cb 触发后，把 c2 改 dismissed
    def progress(stage, current, total):
        if stage == "提交到 115" and current == 1:
            from sqlalchemy import update
            db_session.execute(
                update(WhitelistCandidate)
                .where(WhitelistCandidate.id == c2.id)
                .values(lifecycle_status="dismissed")
            )
            db_session.commit()

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False, progress_cb=progress,
    )
    # c1 提交成功，c2 被并发改成 dismissed，skipped 计数 +1
    assert summary.submitted == 1
    assert summary.skipped == 1


def test_submit_duplicate_skipped_counts_as_skipped(db_session):
    """115 返回 duplicate_skipped 应计 skipped 但 lifecycle 标 submitted。"""
    entry = _make_entry(db_session)
    cand = _make_candidate(db_session, entry)

    magnet_svc = MagicMock()
    magnet_svc.create_and_submit_tasks.return_value = [_make_task(1, "duplicate_skipped", task_id=33)]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)
    summary = svc.submit_selected(
        candidate_ids=[cand.id], force_submit=False, progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    assert summary.submitted == 0
    db_session.refresh(cand)
    assert cand.lifecycle_status == "submitted"
    assert cand.submitted_at is not None


def test_submit_empty_candidate_ids_raises(db_session):
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="未选择"):
        svc.submit_selected(candidate_ids=[], force_submit=False, progress_cb=lambda *a: None)


def test_submit_no_existing_candidates_raises(db_session):
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="未选择"):
        svc.submit_selected(candidate_ids=[9999], force_submit=False, progress_cb=lambda *a: None)
