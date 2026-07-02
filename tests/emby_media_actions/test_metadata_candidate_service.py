from __future__ import annotations

from app.models.keywords import KeywordEntry
from app.services.emby_media_actions.metadata_candidate_service import EmbyMetadataCandidateService


def test_create_candidate_stores_snapshot(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_blacklist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie><actor><name>演员A</name></actor></movie>",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[{"name": "演员A", "role": None, "provider_ids": {}}],
        source_path="/media/a.nfo",
    )

    assert candidate.status == "pending"
    assert candidate.snapshot.title == "测试电影"
    assert "演员A" in candidate.snapshot.actors_json


def test_apply_actors_creates_emby_keyword_entries(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_whitelist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie><actor><name>演员A</name></actor></movie>",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[{"name": "演员A", "role": None, "provider_ids": {}}],
        source_path="/media/a.nfo",
    )

    applied = service.apply_actors(candidate_id=candidate.id, actors=["演员A"], note="喜欢")

    assert applied.status == "applied"
    entry = db_session.query(KeywordEntry).filter_by(canonical_name="演员A").one()
    assert entry.keyword_type == "emby_whitelist"
