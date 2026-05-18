from __future__ import annotations

import asyncio
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

    # 重置模块级状态，防止测试间污染（不 reload，直接清理状态避免模块引用分裂）
    _imports._progress.clear()
    # 若上一个测试留下锁定状态，强制重置
    if _imports._import_lock.locked():
        _imports._import_lock = asyncio.Lock()

    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_remote_fetch_returns_import_id_immediately(client, monkeypatch):
    """POST /imports/remote-fetch 应立即返回 {import_id, status: pending}，不阻塞。"""
    from app.api.routes import imports as _imports

    # 让后台任务立即完成，避免真实 115 调用
    async def fake_run_import(import_id, payload):
        _imports._progress[import_id] = {
            "stage": "完成", "current": 1, "total": 1, "done": True, "error": None
        }

    monkeypatch.setattr(_imports, "_run_import", fake_run_import)

    resp = client.post("/imports/remote-fetch", json={
        "cid": "12345",
        "path_label": "测试目录",
        "depth_limit": 2,
        "folders_only": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "import_id" in data
    assert data["status"] == "pending"


def test_remote_fetch_returns_409_when_lock_held(client, monkeypatch):
    """并发第二次 POST 应返回 409。"""
    from app.api.routes import imports as _imports

    # monkeypatch locked() 方法返回 True，避免 event loop 跨越问题
    monkeypatch.setattr(_imports._import_lock, "locked", lambda: True)

    resp = client.post("/imports/remote-fetch", json={
        "cid": "99",
        "path_label": "测试",
        "depth_limit": 2,
        "folders_only": True,
    })
    assert resp.status_code == 409


def test_sse_progress_endpoint_streams_done(client, monkeypatch):
    """GET /imports/{id}/progress 应推送至少一帧，done=True 后结束。"""
    from app.api.routes import imports as _imports

    # 预置进度为已完成状态
    import_id = 999
    _imports._progress[import_id] = {
        "stage": "完成", "current": 5, "total": 5, "done": True, "error": None
    }

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
    from app.api.routes import imports as _imports
    _imports._progress.clear()

    with client.stream("GET", "/imports/88888/progress") as resp:
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                break

    assert frames[0].get("error") == "not found"
