from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import organization as _org  # noqa: F401
from app.models import tasks as _task  # noqa: F401
from app.models import tree as _tree  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个测试独立 SQLite + TestClient。"""
    # 禁用认证，避免测试需要 session
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)

    from app import main as _main
    from app.api.routes import imports as _imports
    from app.api import deps

    # 覆盖 DB 依赖，使用测试库
    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    # 进度推送和后台任务在运行时取 SessionLocal，指向测试库
    monkeypatch.setattr("app.db.session.SessionLocal", Factory)

    # 默认不真正起后台线程（避免真实 115 调用），只记录提交的任务
    submitted: list[tuple[str, object]] = []

    def fake_submit_job(job_id, work):
        submitted.append((job_id, work))

    monkeypatch.setattr(_imports, "submit_job", fake_submit_job)

    test_client = TestClient(_main.app, raise_server_exceptions=False)
    test_client.submitted = submitted
    test_client.session_factory = Factory
    yield test_client
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def _seed_job(client, job_id: str, *, done: bool, stage: str, current: int = 0, total: int = 0) -> None:
    """往测试库 background_jobs 表插一条目录导入任务记录。"""
    from datetime import UTC, datetime

    from app.models.background_jobs import BackgroundJob

    now = datetime.now(UTC)
    with client.session_factory() as db:
        db.add(BackgroundJob(
            job_id=job_id, job_type="remote_import", stage=stage, current=current, total=total,
            done=done, started_at=now, updated_at=now, finished_at=now if done else None,
        ))
        db.commit()


def _count_imports(client) -> int:
    from sqlalchemy import func, select

    from app.models.tree import TreeImport

    with client.session_factory() as db:
        return int(db.scalar(select(func.count()).select_from(TreeImport)) or 0)


_PAYLOAD = {"cid": "12345", "path_label": "测试目录", "depth_limit": 2, "folders_only": True}


def test_remote_fetch_returns_import_id_immediately(client):
    """POST /imports/remote-fetch 应立即返回 {import_id, status: pending}，不阻塞。"""
    resp = client.post("/imports/remote-fetch", json=_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "import_id" in data
    assert data["status"] == "pending"
    # 任务编号沿用导入批次编号，已交给后台执行
    assert [job_id for job_id, _ in client.submitted] == [str(data["import_id"])]
    from app.models.tree import TreeImport
    from app.services.background_job_service import BackgroundJobService

    with client.session_factory() as db:
        assert db.get(TreeImport, data["import_id"]).status == "pending"
        state = BackgroundJobService.get(db, str(data["import_id"]))
    assert state["job_type"] == "remote_import"
    assert state["done"] is False


def test_remote_fetch_returns_409_when_lock_held(client):
    """已有导入任务在运行时，第二次 POST 应返回 409。"""
    _seed_job(client, "running-import", done=False, stage="下载目录树")

    resp = client.post("/imports/remote-fetch", json={
        "cid": "99",
        "path_label": "测试",
        "depth_limit": 2,
        "folders_only": True,
    })
    assert resp.status_code == 409
    assert resp.json()["detail"] == "已有导入任务在运行，请稍后再试"


def test_remote_fetch_conflict_leaves_no_pending_import(client):
    """判重失败时不留下状态为 pending 的导入批次记录，也不提交后台任务。"""
    _seed_job(client, "running-import", done=False, stage="下载目录树")
    before = _count_imports(client)

    resp = client.post("/imports/remote-fetch", json=_PAYLOAD)

    assert resp.status_code == 409
    assert _count_imports(client) == before
    assert client.submitted == []


def test_remote_fetch_failure_marks_import_failed(client, monkeypatch):
    """后台抓取失败时导入批次置为 failed，任务记录为失败且已结束。"""
    from app.api.routes import imports as _imports
    from app.models.tree import TreeImport
    from app.services.background_job_service import BackgroundJobService
    from app.services.job_runner import run_job

    def fail_fetch(self, **_kwargs):
        raise RuntimeError("虚构抓取失败")

    monkeypatch.setattr(_imports.RemoteTreeFetchService, "fetch_subtree", fail_fetch)
    monkeypatch.setattr(_imports, "submit_job", lambda job_id, work: run_job(job_id, work))

    resp = client.post("/imports/remote-fetch", json=_PAYLOAD)

    assert resp.status_code == 200
    import_id = resp.json()["import_id"]
    with client.session_factory() as db:
        assert db.get(TreeImport, import_id).status == "failed"
        state = BackgroundJobService.get(db, str(import_id))
    assert state["done"] is True
    assert state["stage"] == "失败"
    assert state["error"] == "虚构抓取失败"


def test_sse_progress_endpoint_streams_done(client):
    """GET /imports/{id}/progress 应推送至少一帧，done=True 后结束。"""
    # 预置进度为已完成状态
    import_id = 999
    _seed_job(client, str(import_id), done=True, stage="完成", current=5, total=5)

    with client.stream("GET", f"/imports/{import_id}/progress") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                break  # 拿到第一帧就够了

    assert len(frames) >= 1
    assert frames[0]["done"] is True
    assert frames[0]["stage"] == "完成"


def test_sse_progress_returns_error_for_unknown_import_id(client):
    """未知 import_id 应推送 error: not found 并结束。"""
    with client.stream("GET", "/imports/88888/progress") as resp:
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                break

    assert frames[0].get("error") == "not found"
