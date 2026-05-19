from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, UTC

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import organization as _org  # noqa: F401
from app.models import tasks as _task  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.models import whitelist as _wl  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth_wb.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api.routes import whitelist_batch as _wb
    from app.api import deps

    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    # 重置模块级状态，防止测试间污染
    _wb._jobs.clear()
    if _wb._scan_lock.locked():
        _wb._scan_lock = asyncio.Lock()
    if _wb._submit_lock.locked():
        _wb._submit_lock = asyncio.Lock()

    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_scan_jobs_returns_409_when_scan_locked(client, monkeypatch):
    from app.api.routes import whitelist_batch as _wb
    monkeypatch.setattr(_wb._scan_lock, "locked", lambda: True)

    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 409
    assert "扫描" in resp.json()["detail"]


def test_submit_jobs_returns_409_when_submit_locked(client, monkeypatch):
    from app.api.routes import whitelist_batch as _wb
    monkeypatch.setattr(_wb._submit_lock, "locked", lambda: True)

    resp = client.post("/whitelist-batch/submit-jobs", json={
        "candidate_ids": [1], "force_submit": False,
    })
    assert resp.status_code == 409
    assert "提交" in resp.json()["detail"]


def test_job_id_is_uuid_not_sequential_integer(client, monkeypatch):
    """job_id 应是 UUID 字符串。"""
    from app.api.routes import whitelist_batch as _wb

    async def fake_run(job_id, payload):
        _wb._jobs[job_id]["done"] = True
        _wb._jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()

    monkeypatch.setattr(_wb, "_run_scan_job", fake_run)
    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    uuid.UUID(job_id)  # 不抛即为合法 uuid


def test_sse_progress_streams_done_frame(client):
    from app.api.routes import whitelist_batch as _wb

    jid = "test-job-1"
    _wb._jobs[jid] = {
        "job_id": jid, "job_type": "scan",
        "stage": "完成", "current": 5, "total": 5,
        "done": True, "error": None,
        "summary": {"scanned_keywords": 1, "new": 5, "updated": 0, "skipped": 0, "failed_keywords": 0},
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    with client.stream("GET", f"/whitelist-batch/jobs/{jid}/progress") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                if len(frames) >= 1:
                    break
    assert frames[0]["done"] is True


def test_sse_progress_returns_error_for_unknown_job(client):
    with client.stream("GET", "/whitelist-batch/jobs/no-such-job/progress") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                assert payload.get("error") == "not found"
                break


def test_get_active_jobs_returns_running_jobs(client):
    from app.api.routes import whitelist_batch as _wb

    _wb._jobs["scan-running"] = {
        "job_id": "scan-running", "job_type": "scan", "stage": "扫描外部库",
        "current": 1, "total": 10, "done": False, "error": None, "summary": None,
        "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
    }
    resp = client.get("/whitelist-batch/jobs/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan"] is not None
    assert data["scan"]["job_id"] == "scan-running"
    assert data["submit"] is None


def _seed_candidate(client, lifecycle="pending"):
    """直接通过 deps.get_db override 插一行候选，返回 cid。"""
    from app.api import deps
    db_factory = client.app.dependency_overrides[deps.get_db]
    sess = next(db_factory())
    try:
        from app.models.keywords import KeywordEntry
        from app.models.whitelist import WhitelistCandidate
        e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                         keyword_type="whitelist", status="active")
        sess.add(e)
        sess.commit()
        c = WhitelistCandidate(
            source_tid=1, source_magnet="m", source_title="t",
            matched_keyword_entry_id=e.id, matched_keyword="A",
            duplicate_status="clear", target_path="/x", lifecycle_status=lifecycle,
        )
        sess.add(c)
        sess.commit()
        return c.id
    finally:
        sess.close()


def test_dismiss_then_restore_round_trip(client):
    cid = _seed_candidate(client, lifecycle="pending")

    resp = client.post(f"/whitelist-batch/candidates/{cid}/dismiss", json={"reason": "误匹配"})
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "dismissed"

    resp = client.post(f"/whitelist-batch/candidates/{cid}/restore")
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "pending"


def test_dismiss_submitted_candidate_returns_400(client):
    cid = _seed_candidate(client, lifecycle="submitted")
    resp = client.post(f"/whitelist-batch/candidates/{cid}/dismiss", json={})
    assert resp.status_code == 400


def test_dismiss_nonexistent_returns_404(client):
    resp = client.post("/whitelist-batch/candidates/99999/dismiss", json={})
    assert resp.status_code == 404


def test_list_candidates_filters_by_lifecycle(client):
    from app.api import deps
    db_factory = client.app.dependency_overrides[deps.get_db]
    sess = next(db_factory())
    try:
        from app.models.keywords import KeywordEntry
        from app.models.whitelist import WhitelistCandidate
        e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                         keyword_type="whitelist", status="active")
        sess.add(e)
        sess.commit()
        for tid, lc in [(1, "pending"), (2, "submitted"), (3, "dismissed")]:
            sess.add(WhitelistCandidate(
                source_tid=tid, source_magnet=f"m{tid}", source_title=f"t{tid}",
                matched_keyword_entry_id=e.id, matched_keyword="A",
                duplicate_status="clear", target_path="/x", lifecycle_status=lc,
            ))
        sess.commit()
    finally:
        sess.close()

    resp = client.get("/whitelist-batch/candidates?lifecycle_status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["source_tid"] == 1


def test_delete_candidate_removes_row(client):
    cid = _seed_candidate(client)
    resp = client.delete(f"/whitelist-batch/candidates/{cid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # 第二次删 → 404
    resp = client.delete(f"/whitelist-batch/candidates/{cid}")
    assert resp.status_code == 404
