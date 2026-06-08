from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import dedupe as _dedupe_models  # noqa: F401
from app.models import keywords as _keywords_models  # noqa: F401
from app.models import organization as _organization_models  # noqa: F401
from app.models import tasks as _task_models  # noqa: F401
from app.models import tree as _tree_models  # noqa: F401
from app.models import whitelist as _whitelist_models  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth_dedupe.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.core.config import get_settings

    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/dedupe-routes.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api import deps

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    try:
        from app.api.routes import dedupe as _dedupe
    except ImportError:
        _dedupe = None
    if _dedupe is not None:
        _dedupe._jobs.clear()
        if _dedupe._scan_lock.locked():
            _dedupe._scan_lock = asyncio.Lock()

        async def fake_run_scan_job(job_id, payload):
            _dedupe._jobs[job_id].update(stage="完成", done=True)

        monkeypatch.setattr(_dedupe, "_run_scan_job", fake_run_scan_job)

    yield TestClient(_main.app, raise_server_exceptions=False)

    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


def _db_session_from_client(client):
    from app.api import deps

    db_factory = client.app.dependency_overrides[deps.get_db]
    return next(db_factory())


def _seed_group(client) -> tuple[int, int, int]:
    from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeScanRun
    from app.models.tree import NodeFile, TreeImport

    db = _db_session_from_client(client)
    try:
        tree_import = TreeImport(source_filename="sample.txt", status="completed", source_type="file_upload")
        db.add(tree_import)
        db.flush()
        first_file = NodeFile(
            tree_import=tree_import,
            raw_name="Example.mp4",
            normalized_name="Example.mp4",
            raw_path="根目录/已整理/Example.mp4",
            parent_path="根目录/已整理",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint="a",
        )
        second_file = NodeFile(
            tree_import=tree_import,
            raw_name="Example (1).mp4",
            normalized_name="Example (1).mp4",
            raw_path="根目录/重复/Example (1).mp4",
            parent_path="根目录/重复",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint="b",
        )
        db.add_all([first_file, second_file])
        db.flush()
        scan_run = DedupeScanRun(tree_import_id=tree_import.id, status="completed")
        db.add(scan_run)
        db.flush()
        group = DedupeGroup(
            scan_run_id=scan_run.id,
            tree_import_id=tree_import.id,
            group_key="local-filename-test",
            representative_name="Example.mp4",
            normalized_name="example",
            score_max=0.96,
            confidence_level="high_probability",
            status="pending_review",
        )
        db.add(group)
        db.flush()
        keep_candidate = DedupeCandidate(
            group_id=group.id,
            node_file_id=first_file.id,
            raw_name=first_file.raw_name,
            raw_path=first_file.raw_path,
            file_ext=first_file.file_ext,
            normalized_name="example",
            similarity_score=0.96,
            suggested_action="keep",
        )
        delete_candidate = DedupeCandidate(
            group_id=group.id,
            node_file_id=second_file.id,
            raw_name=second_file.raw_name,
            raw_path=second_file.raw_path,
            file_ext=second_file.file_ext,
            normalized_name="example",
            similarity_score=0.96,
            suggested_action="delete",
        )
        db.add_all([keep_candidate, delete_candidate])
        db.flush()
        group.suggested_keep_candidate_id = keep_candidate.id
        db.commit()
        return group.id, keep_candidate.id, delete_candidate.id
    finally:
        db.close()


def test_scan_job_endpoint_returns_uuid(client):
    resp = client.post("/dedupe/scan-jobs", json={"tree_import_id": 1})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    uuid.UUID(body["job_id"])


def test_list_groups_returns_page_shape(client):
    resp = client.get("/dedupe/groups")

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 100}


def test_group_detail_returns_candidates(client):
    group_id, keep_id, delete_id = _seed_group(client)

    resp = client.get(f"/dedupe/groups/{group_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["group"]["id"] == group_id
    assert body["group"]["status"] == "pending_review"
    assert {item["id"] for item in body["candidates"]} == {keep_id, delete_id}


def test_review_group_persists_user_actions(client):
    group_id, keep_id, delete_id = _seed_group(client)

    resp = client.post(
        f"/dedupe/groups/{group_id}/review",
        json={
            "keep_candidate_ids": [keep_id],
            "delete_candidate_ids": [delete_id],
            "note": "人工确认",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"group_id": group_id, "status": "confirmed"}

    detail = client.get(f"/dedupe/groups/{group_id}").json()
    assert detail["group"]["status"] == "confirmed"
    assert detail["group"]["review_note"] == "人工确认"
    actions = {item["id"]: item["user_action"] for item in detail["candidates"]}
    assert actions == {keep_id: "keep", delete_id: "delete"}
