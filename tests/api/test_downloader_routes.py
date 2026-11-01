from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.keywords import KeywordEntry
from app.models.downloader import DownloaderTaskHistory, DownloaderTaskSnapshot
from app.services.downloader import sync_service


class FakeClient:
    def list_packages(self, *, cursor=None, page_size=200):
        return {
            "items": [{"id": 9, "library_id": 1, "title": "Foo package", "boundary_status": "stable", "current_download_status": "never", "index_revision": 1}],
            "next_cursor": None,
        }

    def submit_package(self, package_id, idempotency_key, *, mode="incremental"):
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


def test_task_history_route_reads_persisted_snapshots(client, db_session):
    db_session.add(
        DownloaderTaskHistory(
            node_key="rn",
            remote_task_id="task-history",
            payload_hash="hash-route",
            status="completed_with_errors",
            total_count=20,
            success_count=18,
            failed_count=2,
            raw_payload_json="{}",
        )
    )
    db_session.commit()

    response = client.get("/downloader/tasks/task-history/history")

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "completed_with_errors"


def test_packages_view_candidates_returns_counts(client, db_session):
    db_session.add(
        KeywordEntry(
            canonical_name="Foo",
            canonical_name_normalized="foo",
            keyword_type="whitelist",
            status="active",
        )
    )
    db_session.commit()
    assert client.post("/downloader/sync").status_code == 200

    response = client.get("/downloader/packages?view=candidates")

    assert response.status_code == 200
    assert response.json()["counts"] == {"candidates": 1, "ignored": 0}
    assert response.json()["total"] == 1


def test_ignore_requires_candidate_or_package_ids(client):
    response = client.post("/downloader/packages/ignore", json={})

    assert response.status_code == 422


def test_tasks_default_returns_structured_ui_fields(client, db_session):
    db_session.add(
        DownloaderTaskSnapshot(
            node_key="rn",
            remote_task_id="task-default",
            status="downloading",
            title="默认任务",
            total_bytes=1000,
            downloaded_bytes=400,
            remote_created_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
            channel_title="频道 A",
        )
    )
    db_session.commit()

    response = client.get("/downloader/tasks?page=1&page_size=20")

    assert response.status_code == 200
    row = next(item for item in response.json()["items"] if item["remote_task_id"] == "task-default")
    assert row["total_bytes"] == 1000
    assert row["downloaded_bytes"] == 400
    assert row["remote_created_at"] is not None
    assert row["channel_title"] == "频道 A"
    assert "duration_seconds" in row
    assert "download_speed_bytes" in row


def test_tasks_limit_keeps_legacy_response_shape(client):
    response = client.get("/downloader/tasks?limit=5")

    assert response.status_code == 200
    assert set(response.json()) == {"items", "total"}


def test_missing_task_detail_returns_404(client):
    response = client.get("/downloader/tasks/missing/detail")

    assert response.status_code == 404


def test_summary_route_returns_six_keys(client):
    response = client.get("/downloader/summary")

    assert response.status_code == 200
    assert set(response.json()) == {
        "today_count",
        "today_bytes",
        "week_count",
        "week_bytes",
        "active_count",
        "week_failed_files",
    }
