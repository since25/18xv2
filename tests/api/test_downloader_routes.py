from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.keywords import KeywordEntry
from app.services.downloader import sync_service


class FakeClient:
    def list_packages(self, *, cursor=None, page_size=200):
        return {
            "items": [{"id": 9, "library_id": 1, "title": "Foo package", "boundary_status": "stable", "current_download_status": "never", "index_revision": 1}],
            "next_cursor": None,
        }

    def submit_package(self, package_id, idempotency_key):
        return {"batch": {"id": 3, "task_id": "task-3"}, "created": True}

    def health(self):
        return {"status": "ok"}


@pytest.fixture
def client(db_session: Session, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("DOWNLOADER_ENABLED", "true")
    monkeypatch.setenv("DOWNLOADER_BASE_URL", "http://rn.test")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr("app.api.routes.downloader._client", lambda: FakeClient())
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_sync_then_select_and_submit_candidate(client, db_session):
    db_session.add(
        KeywordEntry(
            canonical_name="Foo",
            canonical_name_normalized="foo",
            keyword_type="whitelist",
            status="active",
        )
    )
    db_session.commit()
    response = client.post("/downloader/sync")
    assert response.status_code == 200
    assert response.json()["candidates_created"] == 1

    candidates = client.get("/downloader/packages").json()["items"]
    assert len(candidates) == 1
    candidate_id = candidates[0]["candidate_id"]
    assert client.post(f"/downloader/packages/{candidate_id}/select", json={"selected": True}).status_code == 200

    submitted = client.post("/downloader/download-batches", json={"candidate_ids": [candidate_id]})
    assert submitted.status_code == 200
    assert submitted.json()["submitted"] == 1


def test_status_reports_disabled_without_remote_call(db_session, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("DOWNLOADER_ENABLED", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/downloader/status")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["remote_ready"] is False
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
