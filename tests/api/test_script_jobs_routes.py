from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_list_jobs_returns_three_in_order(client: TestClient) -> None:
    response = client.get("/script-jobs")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["job_name"] for item in items] == ["sehuatang", "MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING"]
    sehuatang = items[0]
    assert sehuatang["label"] == "色花堂抓取"
    assert sehuatang["runnable"] is True
    assert sehuatang["executor"] == "unraid"
    assert sehuatang["next_run_at"] is None


def test_put_invalid_params_returns_400_with_chinese_detail(client: TestClient) -> None:
    response = client.put(
        "/script-jobs/MOVE_SSD_CACHE_TO_DISK2",
        json={"params": {"source_dir": "/etc", "target_dir": "/mnt/disk2/qbbtdn/已整理"}},
    )
    assert response.status_code == 400
    assert "挂载" in response.json()["detail"]


def test_put_unknown_job_returns_404(client: TestClient) -> None:
    assert client.put("/script-jobs/NOPE", json={"enabled": True}).status_code == 404


def test_switch_to_18x_and_enable_sets_next_run_at(client: TestClient) -> None:
    response = client.put("/script-jobs/sehuatang", json={"executor": "18x", "enabled": True})
    assert response.status_code == 200
    body = response.json()
    assert body["executor"] == "18x"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None


def test_changes_endpoint_lists_latest_first(client: TestClient) -> None:
    client.put("/script-jobs/sehuatang", json={"run_time": "02:00"})
    client.put("/script-jobs/sehuatang", json={"run_time": "03:00"})
    response = client.get("/script-jobs/sehuatang/changes?limit=20")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["after"]["run_time"] for item in items] == ["03:00", "02:00"]
