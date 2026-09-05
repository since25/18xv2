from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordHit
from app.models.review_intake import ReviewIntakeItem
from app.services.keywords.registry_service import KeywordRegistryService
from app.services.review_intake_service import ReviewIntakeService, parse_keyword_candidates

DEFAULT_PATTERN = r"[【「『［\[]([^】」』］\]]+)[】」』］\]]"


def _submit(service: ReviewIntakeService, raw_path: str, bucket: str = "whitelist"):
    return service.create_or_update(
        bucket=bucket,
        raw_path=raw_path,
        source="test",
        note=None,
        pattern=DEFAULT_PATTERN,
        flags="",
        group_index=1,
        limit=20,
    )


def test_create_or_update_deduplicates_same_bucket_and_path(db_session):
    service = ReviewIntakeService(db_session)
    raw_path = "/Volumes/finish/作品【姝姬娘娘】.mp4"

    first = _submit(service, raw_path)
    second = _submit(service, f"  {raw_path}  ")

    assert first.id == second.id
    rows = db_session.scalars(select(ReviewIntakeItem)).all()
    assert len(rows) == 1
    assert rows[0].status == "pending"
    candidates = parse_keyword_candidates(rows[0].extracted_keywords_json)
    # 新提取规则会额外切出父目录名与括号外的片段；括号命中仍排第一
    assert candidates[0].keyword == "姝姬娘娘"
    assert candidates[0].source == "bracket"
    assert candidates[0].match_status == "new"
    assert "作品" in [item.keyword for item in candidates]


def test_approve_creates_keyword_entry_and_hit(db_session):
    service = ReviewIntakeService(db_session)
    item = _submit(service, "/Volumes/finish/作品【姝姬娘娘】.mp4", bucket="blacklist")

    approved = service.approve(item_id=item.id, keyword="姝姬娘娘", note="快捷键审核")

    assert approved.status == "approved"
    entry = KeywordRegistryService(db_session).find_entry_by_keyword("姝姬娘娘")
    assert entry is not None
    assert entry.keyword_type == "blacklist"
    hits = db_session.scalars(select(KeywordHit)).all()
    assert len(hits) == 1
    assert hits[0].source_path == "/Volumes/finish/作品【姝姬娘娘】.mp4"
    assert hits[0].match_source == "review_intake"


def test_approve_blocks_keyword_type_conflict(db_session):
    KeywordRegistryService(db_session).create_entry(
        canonical_name="姝姬娘娘",
        keyword_type="whitelist",
    )
    service = ReviewIntakeService(db_session)
    item = _submit(service, "/Volumes/finish/作品【姝姬娘娘】.mp4", bucket="blacklist")

    with pytest.raises(ValueError, match="已存在于 whitelist"):
        service.approve(item_id=item.id, keyword="姝姬娘娘", note=None)

    db_session.refresh(item)
    assert item.status == "pending"


def test_dismissed_item_is_restored_when_submitted_again(db_session):
    service = ReviewIntakeService(db_session)
    item = _submit(service, "/Volumes/finish/作品【姝姬娘娘】.mp4")
    service.dismiss(item_id=item.id, note="先忽略")

    restored = _submit(service, "/Volumes/finish/作品【姝姬娘娘】.mp4")

    assert restored.id == item.id
    assert restored.status == "pending"
    assert restored.reviewed_at is None
