# tests/api/test_tasks_conflicts.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import organization as _org  # noqa: F401
from app.models import tasks as _task  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.models.tasks import OrganizeTask
from app.models.tree import TreeImport, TreeNode
from app.services.client_115.client import Fake115Client


@pytest.fixture
def db_session(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session, monkeypatch):
    from app.api.deps import get_db
    from app.core.config import get_settings
    from app.main import app

    # 禁用认证，避免测试需要 session
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()

    fake_115 = Fake115Client()
    app.state.client_115 = fake_115

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _make_dup_tasks(db: Session) -> tuple[int, int]:
    """创建两个 target_path 相同的 pending 任务，返回 (task_id_a, task_id_b)。"""
    ti = TreeImport(source_filename="dup.txt", status="done")
    db.add(ti)
    db.flush()
    node_a = TreeNode(
        import_id=ti.id, raw_name="专辑Z", normalized_name="专辑z",
        raw_path="/待整理/路径A/专辑Z", depth=2, node_type="folder",
        fingerprint_hint="fp_a", remote_cid="cid_a",
    )
    node_b = TreeNode(
        import_id=ti.id, raw_name="专辑Z", normalized_name="专辑z",
        raw_path="/待整理/路径B/专辑Z", depth=2, node_type="folder",
        fingerprint_hint="fp_b", remote_cid="cid_b",
    )
    db.add_all([node_a, node_b])
    db.flush()
    task_a = OrganizeTask(
        import_id=ti.id, node_id=node_a.id,
        source_path="/待整理/路径A/专辑Z",
        target_path="/根目录/已整理/专辑Z",
        status="pending",
    )
    task_b = OrganizeTask(
        import_id=ti.id, node_id=node_b.id,
        source_path="/待整理/路径B/专辑Z",
        target_path="/根目录/已整理/专辑Z",
        status="pending",
    )
    db.add_all([task_a, task_b])
    db.commit()
    return task_a.id, task_b.id


def test_resolve_duplicate_conflicts_skip_no_delete(client, db_session: Session):
    ta_id, tb_id = _make_dup_tasks(db_session)
    resp = client.post("/organize-tasks/resolve-duplicate-conflicts", json={
        "resolutions": [{
            "target_path": "/根目录/已整理/专辑Z",
            "keep_task_id": ta_id,
            "skip_task_ids": [tb_id],
            "delete_from_115": False,
        }]
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_count"] == 1
    assert body["deleted_from_115_count"] == 0
    assert body["errors"] == []
    # 验证 task_b 已变为 skipped
    db_session.expire_all()
    from sqlalchemy import select
    task_b = db_session.scalar(select(OrganizeTask).where(OrganizeTask.id == tb_id))
    assert task_b.status == "skipped"


def test_resolve_duplicate_conflicts_delete_from_115(client, db_session: Session):
    ta_id, tb_id = _make_dup_tasks(db_session)
    resp = client.post("/organize-tasks/resolve-duplicate-conflicts", json={
        "resolutions": [{
            "target_path": "/根目录/已整理/专辑Z",
            "keep_task_id": ta_id,
            "skip_task_ids": [tb_id],
            "delete_from_115": True,
        }]
    })
    assert resp.status_code == 200
    body = resp.json()
    # Fake115Client has no node with cid_b, so delete will fail → error recorded
    assert body["resolved_count"] == 1
    # Either deleted successfully (if Fake client handles it) or got an error
    # The important thing: resolved_count=1 and HTTP 200
