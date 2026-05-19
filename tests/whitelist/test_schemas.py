from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.whitelist import (
    ActiveJobsResponse,
    CandidateListResponse,
    CandidateResponse,
    DismissRequest,
    JobFrame,
    ScanJobRequest,
    ScanSummary,
    SubmitJobRequest,
    SubmitSummary,
)


def test_scan_job_request_defaults():
    req = ScanJobRequest(tree_import_id=42)
    assert req.tree_import_id == 42
    assert req.keyword_entry_ids is None
    assert req.per_keyword_limit == 10


def test_scan_job_request_per_keyword_limit_bounds():
    with pytest.raises(ValidationError):
        ScanJobRequest(tree_import_id=1, per_keyword_limit=0)
    with pytest.raises(ValidationError):
        ScanJobRequest(tree_import_id=1, per_keyword_limit=999)


def test_submit_job_request_requires_ids():
    with pytest.raises(ValidationError):
        SubmitJobRequest(candidate_ids=[])


def test_submit_job_request_force_submit_default_false():
    req = SubmitJobRequest(candidate_ids=[1, 2])
    assert req.force_submit is False


def test_dismiss_request_reason_optional():
    assert DismissRequest().reason is None
    assert DismissRequest(reason="误匹配").reason == "误匹配"


def test_dismiss_request_reason_max_length():
    with pytest.raises(ValidationError):
        DismissRequest(reason="x" * 256)


def test_scan_summary_fields():
    s = ScanSummary(scanned_keywords=3, new=10, updated=2, skipped=1, failed_keywords=0)
    dumped = s.model_dump()
    assert dumped == {
        "scanned_keywords": 3, "new": 10, "updated": 2, "skipped": 1, "failed_keywords": 0,
    }


def test_submit_summary_fields():
    s = SubmitSummary(submitted=5, failed=1, skipped=2)
    assert s.model_dump() == {"submitted": 5, "failed": 1, "skipped": 2}


def test_job_frame_shape():
    frame = JobFrame(
        job_id="abc-123", job_type="scan", stage="扫描外部库",
        current=10, total=50, done=False, error=None, summary=None,
        started_at="2026-05-19T00:00:00+00:00", finished_at=None,
    )
    assert frame.job_id == "abc-123"
    assert frame.job_type == "scan"


def test_job_frame_job_type_restricted_to_scan_or_submit():
    with pytest.raises(ValidationError):
        JobFrame(
            job_id="x", job_type="invalid", stage="", current=0, total=0,
            done=True, error=None, summary=None,
            started_at="2026-05-19T00:00:00+00:00", finished_at=None,
        )


def test_active_jobs_response_defaults_to_all_none():
    r = ActiveJobsResponse()
    assert r.model_dump() == {"scan": None, "submit": None}


def test_candidate_response_from_orm(db_session):
    """CandidateResponse 必须支持从 ORM 对象构造（from_attributes=True）。"""
    from app.models.keywords import KeywordEntry
    from app.models.whitelist import WhitelistCandidate

    e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                     keyword_type="whitelist", status="active")
    db_session.add(e)
    db_session.commit()
    c = WhitelistCandidate(
        source_tid=1, source_magnet="m", source_title="t",
        matched_keyword_entry_id=e.id, matched_keyword="A",
        duplicate_status="clear", target_path="/x",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)

    resp = CandidateResponse.model_validate(c)
    assert resp.id == c.id
    assert resp.source_tid == 1
    assert resp.lifecycle_status == "pending"


def test_candidate_list_response_shape():
    cl = CandidateListResponse(items=[], total=0, page=1, page_size=100)
    assert cl.total == 0
    assert cl.items == []


def test_candidate_list_response_with_items(db_session):
    from app.models.keywords import KeywordEntry
    from app.models.whitelist import WhitelistCandidate

    e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                     keyword_type="whitelist", status="active")
    db_session.add(e)
    db_session.commit()
    c = WhitelistCandidate(
        source_tid=99, source_magnet="m", source_title="t",
        matched_keyword_entry_id=e.id, matched_keyword="A",
        duplicate_status="clear", target_path="/x",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)

    cl = CandidateListResponse(
        items=[CandidateResponse.model_validate(c)],
        total=1, page=1, page_size=100,
    )
    assert cl.total == 1
    assert len(cl.items) == 1
    assert cl.items[0].source_tid == 99
