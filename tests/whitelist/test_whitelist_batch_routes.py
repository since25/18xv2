from __future__ import annotations

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
    # 不走 lifespan，app.state 上没有 115 客户端，注入一个哨兵对象代替全局单例
    _main.app.dependency_overrides[deps.get_115_client] = lambda: _SENTINEL_115_CLIENT
    # 进度推送、active 查询和后台任务都在运行时取 SessionLocal，指向测试库
    monkeypatch.setattr("app.db.session.SessionLocal", Factory)

    # 默认不真正起后台线程，只记录提交的任务；需要执行时由用例自己替换
    submitted: list[tuple[str, object]] = []

    def fake_submit_job(job_id, work):
        submitted.append((job_id, work))

    monkeypatch.setattr(_wb, "submit_job", fake_submit_job)

    test_client = TestClient(_main.app, raise_server_exceptions=False)
    test_client.submitted = submitted
    test_client.session_factory = Factory
    yield test_client
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


_SENTINEL_115_CLIENT = object()


def _seed_job(client, job_id: str, job_type: str, *, done: bool, **fields) -> None:
    """直接往测试库 background_jobs 表插一条任务记录。"""
    from app.models.background_jobs import BackgroundJob

    now = datetime.now(UTC)
    with client.session_factory() as sess:
        sess.add(BackgroundJob(
            job_id=job_id, job_type=job_type,
            stage=fields.pop("stage", "完成" if done else "扫描中"),
            current=fields.pop("current", 0), total=fields.pop("total", 0),
            done=done, started_at=now, updated_at=now,
            finished_at=now if done else None,
            **fields,
        ))
        sess.commit()


def test_scan_jobs_returns_409_when_scan_running(client):
    _seed_job(client, "scan-running", "whitelist:scan", done=False)

    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 409
    assert "扫描" in resp.json()["detail"]
    assert client.submitted == []


def test_submit_jobs_returns_409_when_submit_running(client):
    _seed_job(client, "submit-running", "whitelist:submit", done=False)

    resp = client.post("/whitelist-batch/submit-jobs", json={
        "candidate_ids": [1], "force_submit": False,
    })
    assert resp.status_code == 409
    assert "提交" in resp.json()["detail"]
    assert client.submitted == []


def test_job_id_is_uuid_not_sequential_integer(client):
    """job_id 应是 UUID 字符串。"""
    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    job_id = resp.json()["job_id"]
    uuid.UUID(job_id)  # 不抛即为合法 uuid
    assert [jid for jid, _ in client.submitted] == [job_id]


def test_scan_and_submit_jobs_use_singleton_115_client(client, monkeypatch):
    """后台扫描/提交构造 MagnetDownloadService 时拿到的是全局 115 客户端，而不是新建实例。"""
    from app.api.routes import whitelist_batch as _wb
    from app.schemas.whitelist import ScanSummary, SubmitSummary
    from app.services import magnet_download_service as _mds
    from app.services.job_runner import run_job

    seen_clients: list[object] = []

    class RecordingMagnetService:
        def __init__(self, db, *, article_db=None, client_115=None):
            seen_clients.append(client_115)

    class FakeCandidateService:
        def __init__(self, db, *, magnet_svc):
            self.magnet_svc = magnet_svc

        def scan(self, **_kwargs):
            return ScanSummary(scanned_keywords=0, new=0, updated=0, skipped=0, failed_keywords=0)

        def submit_selected(self, **_kwargs):
            return SubmitSummary(submitted=0, skipped=0, failed=0)

    monkeypatch.setattr(_mds, "MagnetDownloadService", RecordingMagnetService)
    monkeypatch.setattr(_wb, "WhitelistCandidateService", FakeCandidateService)
    # 同步执行，便于断言
    monkeypatch.setattr(_wb, "submit_job", lambda job_id, work: run_job(job_id, work))

    scan = client.post("/whitelist-batch/scan-jobs", json={"tree_import_id": 1, "per_keyword_limit": 5})
    submit = client.post("/whitelist-batch/submit-jobs", json={"candidate_ids": [1], "force_submit": False})

    assert scan.status_code == 200
    assert submit.status_code == 200
    assert seen_clients == [_SENTINEL_115_CLIENT, _SENTINEL_115_CLIENT]
    from app.services.background_job_service import BackgroundJobService
    with client.session_factory() as sess:
        for job_id in (scan.json()["job_id"], submit.json()["job_id"]):
            state = BackgroundJobService.get(sess, job_id)
            assert state["done"] is True
            assert state["stage"] == "完成"
            assert state["error"] is None


def test_sse_progress_streams_done_frame(client):
    jid = "test-job-1"
    _seed_job(
        client, jid, "whitelist:scan", done=True, current=5, total=5,
        summary_json=json.dumps({"scanned_keywords": 1, "new": 5, "updated": 0, "skipped": 0, "failed_keywords": 0}),
    )
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
    # 对外仍展示去掉命名空间前缀的任务类型
    assert frames[0]["job_type"] == "scan"


def test_sse_progress_returns_error_for_unknown_job(client):
    with client.stream("GET", "/whitelist-batch/jobs/no-such-job/progress") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                assert payload.get("error") == "not found"
                break


def test_get_active_jobs_returns_running_jobs(client):
    _seed_job(client, "scan-running", "whitelist:scan", done=False, stage="扫描外部库", current=1, total=10)
    resp = client.get("/whitelist-batch/jobs/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan"] is not None
    assert data["scan"]["job_id"] == "scan-running"
    assert data["scan"]["job_type"] == "scan"
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
