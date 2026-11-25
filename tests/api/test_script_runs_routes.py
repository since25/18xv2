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


FIXED_NOW = datetime(2026, 11, 25, 5, 0, tzinfo=UTC)  # 上海时间 13:00


def _freeze_now(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.script_jobs import run_store

    monkeypatch.setattr(run_store, "now_utc", lambda: FIXED_NOW)


def _script(summary: dict, name: str) -> dict:
    return next(item for item in summary["scripts"] if item["script_name"] == name)


def test_summary_lists_three_jobs_with_executor(client: TestClient) -> None:
    summary = client.get("/script-runs/summary").json()
    assert [item["script_name"] for item in summary["scripts"]] == [
        "sehuatang",
        "MOVE_SSD_CACHE_TO_DISK2",
        "DEL_SOMETHING",
    ]
    assert {item["executor"] for item in summary["scripts"]} == {"unraid"}


def test_summary_uses_config_run_time(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_now(monkeypatch)
    # 13:00 时：12:09 未超两小时宽限 → pending；改成 10:00 → missing；改成 23:59 → pending
    assert _script(client.get("/script-runs/summary").json(), "DEL_SOMETHING")["today_status"] == "pending"
    client.put("/script-jobs/DEL_SOMETHING", json={"run_time": "10:00"})
    assert _script(client.get("/script-runs/summary").json(), "DEL_SOMETHING")["today_status"] == "missing"
    client.put("/script-jobs/DEL_SOMETHING", json={"run_time": "23:59"})
    del_script = _script(client.get("/script-runs/summary").json(), "DEL_SOMETHING")
    assert del_script["today_status"] == "pending"
    assert del_script["expected_time"] == "23:59"


def test_summary_dry_runs_excluded_from_trend_and_today(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_now(monkeypatch)
    db_session.add(
        ScriptRun(
            run_key="dry-1",
            script_name="DEL_SOMETHING",
            started_at=FIXED_NOW - timedelta(hours=1),
            finished_at=FIXED_NOW - timedelta(minutes=50),
            exit_code=0,
            status="success",
            counts={"deleted_files": 9},
            trigger="manual",
            dry_run=True,
        )
    )
    db_session.commit()
    summary = client.get("/script-runs/summary?days=1").json()
    assert summary["days"][0]["has_run"] is False
    assert summary["days"][0]["cleaned"] == 0
    assert _script(summary, "DEL_SOMETHING")["today_status"] == "pending"


def test_summary_disabled_18x_job_shows_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_now(monkeypatch)
    client.put("/script-jobs/sehuatang", json={"executor": "18x", "enabled": False})
    assert _script(client.get("/script-runs/summary").json(), "sehuatang")["today_status"] == "disabled"


def test_summary_sehuatang_under_unraid_is_not_tracked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_now(monkeypatch)
    assert _script(client.get("/script-runs/summary").json(), "sehuatang")["today_status"] == "not_tracked"


def test_unraid_report_post_still_accepted_with_trigger_report(client: TestClient) -> None:
    response = client.post("/script-runs", json=_payload(run_key="report-1", started_at="2026-11-02T04:09:00Z"))
    assert response.status_code == 200
    body = response.json()
    assert body["trigger"] == "report"
    assert body["dry_run"] is False
    assert body["has_log"] is False
    assert body["error_reason"] is None


def test_running_run_without_finish_is_listed(client: TestClient, db_session: Session) -> None:
    db_session.add(
        ScriptRun(
            run_key="running-1",
            script_name="sehuatang",
            started_at=datetime.now(UTC),
            status="running",
            counts={},
            trigger="manual",
        )
    )
    db_session.commit()
    items = client.get("/script-runs").json()["items"]
    running = next(item for item in items if item["run_key"] == "running-1")
    assert running["finished_at"] is None
    assert running["exit_code"] is None
    assert running["status"] == "running"

