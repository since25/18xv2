from __future__ import annotations

import json

import pytest

from app.models.keywords import KeywordAlias, KeywordEntry, KeywordLibraryEntry
from app.services.emby_media_actions.metadata_candidate_service import EmbyMetadataCandidateService
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text


def test_create_candidate_stores_snapshot(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    nfo_xml = "<movie><actor><name>演员A</name></actor></movie>"
    emby_payload = {"Id": "item-1", "Name": "测试电影"}
    actors = [{"name": "演员A", "role": None, "provider_ids": {}}]
    candidate = service.create_candidate(
        target_list="emby_blacklist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml=nfo_xml,
        emby_payload=emby_payload,
        actors=actors,
        source_path="/media/a.nfo",
        mapping_id=42,
    )

    assert candidate.status == "pending"
    assert candidate.snapshot.title == "测试电影"
    assert candidate.snapshot.nfo_xml == nfo_xml
    assert json.loads(candidate.snapshot.emby_json) == emby_payload
    assert json.loads(candidate.snapshot.actors_json) == actors
    assert candidate.snapshot.nfo_path == "/media/a.nfo"
    assert candidate.snapshot.mapping_id == 42


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


def test_apply_actors_does_not_sync_legacy_keyword_library(db_session) -> None:
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

    service.apply_actors(candidate_id=candidate.id, actors=["演员A"], note=None)

    assert db_session.query(KeywordLibraryEntry).count() == 0


def test_apply_actors_conflict_is_atomic(db_session) -> None:
    KeywordRegistryService(db_session).create_entry(
        canonical_name="冲突演员",
        keyword_type="blacklist",
    )
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_whitelist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie><actor><name>新演员</name></actor></movie>",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[{"name": "新演员", "role": None, "provider_ids": {}}],
        source_path="/media/a.nfo",
    )

    with pytest.raises(ValueError, match="冲突演员"):
        service.apply_actors(candidate_id=candidate.id, actors=["新演员", "冲突演员"], note="喜欢")

    db_session.refresh(candidate)
    assert candidate.status == "pending"
    assert candidate.selected_actors_json == "[]"
    assert candidate.applied_keyword_entry_ids_json == "[]"
    assert db_session.query(KeywordEntry).filter_by(canonical_name="新演员").count() == 0
    assert db_session.query(KeywordAlias).filter_by(alias_normalized=normalize_keyword_text("新演员")).count() == 0


def test_apply_actors_rejects_empty_submission(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_whitelist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie />",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[],
        source_path="/media/a.nfo",
    )

    with pytest.raises(ValueError, match="at least one actor"):
        service.apply_actors(candidate_id=candidate.id, actors=[" ", ""], note=None)

    db_session.refresh(candidate)
    assert candidate.status == "pending"
    assert db_session.query(KeywordEntry).count() == 0
