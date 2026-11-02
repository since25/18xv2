from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.background_jobs import BackgroundJob
from app.models.jellyfin import JellyfinMediaItem


@pytest.fixture
def client(db_session: Session, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("JELLYFIN_ENABLED", "false")
    monkeypatch.setenv("JELLYFIN_BASE_URL", "http://jellyfin.test")
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_status_when_disabled(client):
    response = client.get("/jellyfin/status")

    assert response.status_code == 200
    assert response.json()["scan_enabled"] is False
    assert response.json()["sync_enabled"] is False


def test_scan_returns_409_when_disabled(client):
    response = client.post("/jellyfin/scan")

    assert response.status_code == 409


def test_scan_rejects_concurrent(client, db_session, monkeypatch):
    monkeypatch.setenv("JELLYFIN_ENABLED", "true")
    get_settings.cache_clear()
    db_session.add(BackgroundJob(job_id="running-scan", job_type="jellyfin:scan", done=False, stage="扫描中"))
    db_session.commit()

    response = client.post("/jellyfin/scan")

    assert response.status_code == 409


def test_sync_409_without_api_key(client, monkeypatch):
    monkeypatch.setenv("JELLYFIN_ENABLED", "true")
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    get_settings.cache_clear()

    response = client.post("/jellyfin/sync")

    assert response.status_code == 409


def test_unmatched_lists_only_active_filtered(client, db_session):
    db_session.add_all(
        [
            JellyfinMediaItem(source="local", path="/虚构/active.mp4", active=True, match_state="unmatched"),
            JellyfinMediaItem(source="strm_115", path="/虚构/error.strm", active=True, match_state="nfo_error"),
            JellyfinMediaItem(source="local", path="/虚构/inactive.mp4", active=False, match_state="unmatched"),
        ]
    )
    db_session.commit()

    response = client.get("/jellyfin/unmatched?source=local&state=unmatched")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["path"] == "/虚构/active.mp4"


def test_daily_loop_not_started_when_disabled(client):
    assert not hasattr(client.app.state, "jellyfin_daily_task")
