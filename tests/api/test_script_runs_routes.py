from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.script_runs import ScriptRun, ScriptRunItem


def _payload(*, run_key: str, started_at: str, script_name: str = "DEL_SOMETHING", exit_code: int = 0) -> dict:
    return {
        "run_key": run_key,
        "script_name": script_name,
        "started_at": started_at,
        "finished_at": started_at,
        "exit_code": exit_code,
        "counts": {
            "deleted_dirs": 2,
            "deleted_files": 3,
            "empty_dirs": 1,
            "moved_new": 4,
            "moved_rescan": 0,
            "ambiguous": 0,
            "skipped": 0,
            "errors": 0,
            "warnings": 0,
            "unparsed_lines": 0,
            "moved": 0,
            "duplicates_removed": 0,
            "failed": 0,
        },
        "items": [
            {
                "kind": "deleted_file",
                "path": "/data/finish/示例文件A.mkv",
                "target_path": None,
                "keyword": None,
                "message": None,
            }
        ],
    }


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


def test_post_is_idempotent_and_truncates_items(client: TestClient) -> None:
    payload = _payload(run_key="run-1", started_at="2026-11-02T04:09:00Z")
    payload["items"] = [dict(payload["items"][0], path=f"/data/finish/示例文件-{i}.mkv") for i in range(5001)]

    first = client.post("/script-runs", json=payload)
    second = client.post("/script-runs", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["items_truncated"] is True
    assert first.json()["counts"]["deleted_files"] == 3


def test_items_search_escapes_like_wildcards_and_returns_unfiltered_kind_counts(client: TestClient) -> None:
    payload = _payload(run_key="run-search", started_at="2026-11-02T04:09:00Z")
    payload["items"] = [
        dict(payload["items"][0], kind="deleted_file", path="/data/a_100%/one.mkv"),
        dict(payload["items"][0], kind="warning", path="/data/warning.mkv", message="示例警告"),
    ]
    created = client.post("/script-runs", json=payload)
    run_id = created.json()["id"]

    result = client.get(f"/script-runs/{run_id}/items?kind=deleted_file&q=a_100%")

    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["kind_counts"] == {"deleted_file": 1, "warning": 1}


def test_expired_items_are_cleaned_but_runs_are_retained(client: TestClient, db_session: Session) -> None:
    old_run = ScriptRun(
        run_key="old-run",
        script_name="DEL_SOMETHING",
        started_at=datetime.now(UTC) - timedelta(days=91),
        finished_at=datetime.now(UTC) - timedelta(days=91),
        exit_code=0,
        status="success",
        counts={},
        items_truncated=False,
        received_at=datetime.now(UTC) - timedelta(days=91),
    )
    old_run.items.append(ScriptRunItem(kind="deleted_file", path="/data/old/示例文件.mkv"))
    db_session.add(old_run)
    db_session.commit()

    response = client.post("/script-runs", json=_payload(run_key="new-run", started_at="2026-11-02T04:09:00Z"))

    assert response.status_code == 200
    assert db_session.scalar(select(ScriptRun).where(ScriptRun.run_key == "old-run")) is not None
    assert db_session.scalars(select(ScriptRunItem).where(ScriptRunItem.run_id == old_run.id)).all() == []


def test_protected_route_rejects_anonymous_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()

    assert client.get("/script-runs").status_code == 401


def test_summary_returns_days_and_latest_status(client: TestClient) -> None:
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    response = client.post("/script-runs", json=_payload(run_key="summary-run", started_at=started_at))
    assert response.status_code == 200

    summary = client.get("/script-runs/summary?days=3")

    assert summary.status_code == 200
    assert summary.json()["timezone"] == "Asia/Shanghai"
    assert len(summary.json()["days"]) == 3
    del_script = next(item for item in summary.json()["scripts"] if item["script_name"] == "DEL_SOMETHING")
    assert del_script["latest_run"]["run_key"] == "summary-run"
    assert del_script["today_status"] == "success"


def test_failed_and_warning_status_are_computed_server_side(client: TestClient) -> None:
    warning_payload = _payload(run_key="warning-run", started_at="2026-11-02T04:09:00Z")
    warning_payload["counts"]["ambiguous"] = 1
    failed_payload = _payload(run_key="failed-run", started_at="2026-11-02T04:10:00Z", exit_code=7)

    warning = client.post("/script-runs", json=warning_payload)
    failed = client.post("/script-runs", json=failed_payload)

    assert warning.json()["status"] == "warning"
    assert failed.json()["status"] == "failed"

