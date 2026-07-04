from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.api.routes.keywords import scan_duplicate_keywords
from app.models.whitelist import WhitelistCandidate
from app.schemas.keywords import KeywordDuplicateScanRequest
from app.services.keywords.registry_service import KeywordRegistryService

KEYWORDS_BASE = "/keywords"


@pytest.fixture
def client(db_session: Session, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth_keywords.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_duplicate_scan_response_includes_reference_counts(db_session: Session):
    svc = KeywordRegistryService(db_session)
    first = svc.create_entry(canonical_name="Alpha", keyword_type="whitelist", aliases=["ABP31"])
    second = svc.create_entry(canonical_name="ABP-31", keyword_type="whitelist")
    db_session.add_all(
        [
            WhitelistCandidate(
                source_tid=4001,
                source_magnet="magnet:?xt=urn:btih:route-a",
                source_title="引用 A",
                matched_keyword_entry_id=first.id,
                matched_keyword=first.canonical_name,
                duplicate_status="clear",
                target_path="/target/a",
            ),
            WhitelistCandidate(
                source_tid=4002,
                source_magnet="magnet:?xt=urn:btih:route-b",
                source_title="引用 B",
                matched_keyword_entry_id=second.id,
                matched_keyword=second.canonical_name,
                duplicate_status="clear",
                target_path="/target/b",
            ),
            WhitelistCandidate(
                source_tid=4003,
                source_magnet="magnet:?xt=urn:btih:route-c",
                source_title="引用 C",
                matched_keyword_entry_id=second.id,
                matched_keyword=second.canonical_name,
                duplicate_status="clear",
                target_path="/target/c",
            ),
        ]
    )
    db_session.commit()

    response = scan_duplicate_keywords(
        KeywordDuplicateScanRequest(keyword_type="whitelist", threshold=0.85),
        db_session,
    )

    assert len(response.pairs) == 1
    pair = response.pairs[0]
    counts_by_id = {
        pair.keyword_1.id: pair.keyword_1_reference_count,
        pair.keyword_2.id: pair.keyword_2_reference_count,
    }
    assert counts_by_id == {first.id: 1, second.id: 2}


def test_create_keyword_accepts_merge_policy(client):
    response = client.post(
        KEYWORDS_BASE,
        json={
            "canonical_name": "露脸_泄密_反差_电报",
            "keyword_type": "whitelist",
            "merge_policy": "fallback_only",
            "aliases": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["merge_policy"] == "fallback_only"


def test_update_keyword_accepts_merge_policy(client):
    created = client.post(
        KEYWORDS_BASE,
        json={"canonical_name": "口巾SANG", "keyword_type": "whitelist", "aliases": []},
    ).json()

    response = client.patch(
        f"{KEYWORDS_BASE}/{created['id']}",
        json={"merge_policy": "fallback_only"},
    )

    assert response.status_code == 200
    assert response.json()["merge_policy"] == "fallback_only"


def test_keyword_merge_policy_rejects_unknown_value(client):
    response = client.post(
        KEYWORDS_BASE,
        json={
            "canonical_name": "泛化词",
            "keyword_type": "whitelist",
            "merge_policy": "low",
            "aliases": [],
        },
    )

    assert response.status_code == 422
