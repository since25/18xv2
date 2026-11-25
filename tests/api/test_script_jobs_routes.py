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


@pytest.fixture
def fake_runner(client: TestClient, db_session: Session, tmp_path):
    from tests.script_jobs.runner_fakes import build_runner, make_definition

    definitions = {
        "sehuatang": make_definition("sehuatang", "sehuatang"),
        "MOVE_SSD_CACHE_TO_DISK2": make_definition("MOVE_SSD_CACHE_TO_DISK2", "media"),
        "DEL_SOMETHING": make_definition("DEL_SOMETHING", "media"),
    }
    runner, popen, killpg, clock = build_runner(db_session, tmp_path, definitions=definitions)
    previous = getattr(app.state, "script_job_runner", None)
    app.state.script_job_runner = runner
    try:
        yield runner, popen
    finally:
        app.state.script_job_runner = previous


def test_manual_run_returns_201_then_409_when_busy(client: TestClient, fake_runner) -> None:
    first = client.post("/script-jobs/sehuatang/runs", json={"dry_run": False})
    assert first.status_code == 201
    assert first.json()["status"] == "running"
    second = client.post("/script-jobs/sehuatang/runs", json={"dry_run": True})
    assert second.status_code == 409


def test_manual_run_unknown_job_404(client: TestClient, fake_runner) -> None:
    assert client.post("/script-jobs/NOPE/runs", json={"dry_run": True}).status_code == 404


def test_stop_then_stop_again_conflicts(client: TestClient, fake_runner) -> None:
    runner, popen = fake_runner
    run_id = client.post("/script-jobs/sehuatang/runs", json={"dry_run": False}).json()["run_id"]
    assert client.post(f"/script-runs/{run_id}/stop").status_code == 200
    popen.procs[0].returncode = -15
    runner.poll()
    assert client.post(f"/script-runs/{run_id}/stop").status_code == 409


def test_log_endpoint_reads_incrementally(client: TestClient, fake_runner, db_session: Session) -> None:
    from pathlib import Path

    from app.models.script_runs import ScriptRun

    runner, popen = fake_runner
    run_id = client.post("/script-jobs/sehuatang/runs", json={"dry_run": False}).json()["run_id"]
    db_session.expire_all()
    log_path = Path(db_session.get(ScriptRun, run_id).log_path)
    log_path.write_bytes("第一页完成\n第二页".encode())

    first = client.get(f"/script-runs/{run_id}/log?offset=0").json()
    assert first == {"text": "第一页完成\n", "next_offset": len("第一页完成\n".encode()), "finished": False}

    popen.procs[0].returncode = 0
    runner.poll()
    rest = client.get(f"/script-runs/{run_id}/log?offset={first['next_offset']}").json()
    assert rest["text"] == "第二页"
    assert rest["finished"] is True


def test_log_endpoint_finished_run_over_64kb_is_read_in_chunks(
    client: TestClient, fake_runner, db_session: Session
) -> None:
    from pathlib import Path

    from app.models.script_runs import ScriptRun

    runner, popen = fake_runner
    run_id = client.post("/script-jobs/sehuatang/runs", json={"dry_run": False}).json()["run_id"]
    db_session.expire_all()
    log_path = Path(db_session.get(ScriptRun, run_id).log_path)
    content = ("第" * 40 + "\n") * 2000  # 约 242KB
    log_path.write_bytes(content.encode())
    popen.procs[0].returncode = 0
    runner.poll()

    collected = ""
    offset = 0
    for _ in range(20):
        chunk = client.get(f"/script-runs/{run_id}/log?offset={offset}").json()
        collected += chunk["text"]
        offset = chunk["next_offset"]
        if chunk["finished"]:
            break
    assert collected == content


def test_log_endpoint_404_without_log(client: TestClient) -> None:
    created = client.post(
        "/script-runs",
        json={
            "run_key": "report-no-log",
            "script_name": "DEL_SOMETHING",
            "started_at": "2026-11-02T04:09:00Z",
            "finished_at": "2026-11-02T04:10:00Z",
            "exit_code": 0,
            "counts": {},
            "items": [],
        },
    )
    assert client.get(f"/script-runs/{created.json()['id']}/log").status_code == 404


def test_job_view_alert_from_latest_failed_run(client: TestClient, db_session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.script_runs import ScriptRun

    now = datetime.now(UTC)
    db_session.add_all(
        [
            ScriptRun(run_key="ok", script_name="sehuatang", started_at=now - timedelta(days=1),
                      finished_at=now - timedelta(days=1), exit_code=0, status="success", counts={},
                      trigger="scheduled"),
            ScriptRun(run_key="bad", script_name="sehuatang", started_at=now - timedelta(hours=1),
                      finished_at=now - timedelta(hours=1), exit_code=0, status="failed", counts={},
                      trigger="scheduled", error_reason="站点 cookie 可能失效：列表页全部失败"),
            ScriptRun(run_key="live", script_name="sehuatang", started_at=now, status="running", counts={},
                      trigger="manual"),
        ]
    )
    db_session.commit()
    sehuatang = client.get("/script-jobs").json()["items"][0]
    assert sehuatang["alert"] == "站点 cookie 可能失效：列表页全部失败"
    assert sehuatang["latest_run"]["run_key"] == "bad"
    assert sehuatang["active_run"]["run_key"] == "live"
    move = client.get("/script-jobs").json()["items"][1]
    assert move["alert"] is None
    assert move["active_run"] is None
    assert move["latest_run"] is None


def test_put_site_session_then_get_shows_configured_without_cookie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SEHUATANG_SESSION_PATH", str(tmp_path / "site_session.json"))
    get_settings.cache_clear()
    before = client.get("/script-jobs").json()["items"][0]["site_session"]
    assert before == {"configured": False, "updated_at": None}

    response = client.put(
        "/script-jobs/sehuatang/site-session",
        json={"cookie": "cf_clearance=SECRET-COOKIE-123; a=1", "user_agent": "Mozilla/5.0 Test Agent"},
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    listing = client.get("/script-jobs")
    assert listing.json()["items"][0]["site_session"]["configured"] is True
    assert listing.json()["items"][1]["site_session"] is None
    assert "SECRET-COOKIE-123" not in listing.text
    assert "SECRET-COOKIE-123" not in response.text


def test_put_site_session_rejects_garbage_cookie(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SEHUATANG_SESSION_PATH", str(tmp_path / "site_session.json"))
    get_settings.cache_clear()
    response = client.put(
        "/script-jobs/sehuatang/site-session", json={"cookie": "garbage", "user_agent": "Mozilla/5.0 Test Agent"}
    )
    assert response.status_code == 400


def test_changes_endpoint_lists_latest_first(client: TestClient) -> None:
    client.put("/script-jobs/sehuatang", json={"run_time": "02:00"})
    client.put("/script-jobs/sehuatang", json={"run_time": "03:00"})
    response = client.get("/script-jobs/sehuatang/changes?limit=20")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["after"]["run_time"] for item in items] == ["03:00", "02:00"]
