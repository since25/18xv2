from __future__ import annotations

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
    # 不走 lifespan，app.state 上没有 115 客户端，注入一个哨兵对象代替全局单例
    _main.app.dependency_overrides[deps.get_115_client] = lambda: _SENTINEL_115_CLIENT
    # 进度推送、active 查询和后台任务都在运行时取 SessionLocal，指向测试库
    monkeypatch.setattr("app.db.session.SessionLocal", factory)

    from app.api.routes import dedupe as _dedupe

    # 默认不真正起后台线程，只记录提交的任务；需要执行时由用例自己替换
    submitted: list[tuple[str, object]] = []

    def fake_submit_job(job_id, work):
        submitted.append((job_id, work))

    monkeypatch.setattr(_dedupe, "submit_job", fake_submit_job)

    test_client = TestClient(_main.app, raise_server_exceptions=False)
    test_client.submitted = submitted
    test_client.session_factory = factory
    yield test_client

    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()
    engine.dispose()


_SENTINEL_115_CLIENT = object()


def _seed_running_job(client, job_id: str, job_type: str) -> None:
    """往测试库 background_jobs 表插一条未完成的任务记录。"""
    from datetime import UTC, datetime

    from app.models.background_jobs import BackgroundJob

    now = datetime.now(UTC)
    with client.session_factory() as db:
        db.add(BackgroundJob(
            job_id=job_id, job_type=job_type, stage="运行中", current=0, total=0,
            done=False, started_at=now, updated_at=now,
        ))
        db.commit()


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


def _seed_delete_candidate(client) -> int:
    from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeRemoteConfirmation, DedupeScanRun
    from app.models.tree import NodeFile, TreeImport

    db = _db_session_from_client(client)
    try:
        tree_import = TreeImport(source_filename="sample.txt", status="completed", source_type="file_upload")
        db.add(tree_import)
        db.flush()
        node = NodeFile(
            tree_import=tree_import,
            raw_name="Example (1).mp4",
            normalized_name="Example (1).mp4",
            raw_path="根目录/重复/Example (1).mp4",
            parent_path="根目录/重复",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint="delete",
        )
        db.add(node)
        db.flush()
        scan_run = DedupeScanRun(tree_import_id=tree_import.id, status="completed")
        db.add(scan_run)
        db.flush()
        group = DedupeGroup(
            scan_run_id=scan_run.id,
            tree_import_id=tree_import.id,
            group_key="delete-group",
            representative_name="Example.mp4",
            normalized_name="example",
            score_max=1.0,
            confidence_level="verified_duplicate",
            status="confirmed",
        )
        db.add(group)
        db.flush()
        candidate = DedupeCandidate(
            group_id=group.id,
            node_file_id=node.id,
            raw_name=node.raw_name,
            raw_path=node.raw_path,
            file_ext=node.file_ext,
            normalized_name="example",
            similarity_score=1.0,
            suggested_action="delete",
            user_action="delete",
        )
        db.add(candidate)
        db.flush()
        db.add(
            DedupeRemoteConfirmation(
                candidate_id=candidate.id,
                status="resolved",
                remote_file_id="file-1",
                remote_path="重复/Example (1).mp4",
                sha1="sha",
                size_bytes=1000,
            )
        )
        db.commit()
        return candidate.id
    finally:
        db.close()


def test_scan_job_endpoint_returns_uuid(client):
    resp = client.post("/dedupe/scan-jobs", json={"tree_import_id": 1})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    uuid.UUID(body["job_id"])
    assert [job_id for job_id, _ in client.submitted] == [body["job_id"]]


def test_confirm_job_endpoint_returns_uuid(client):
    resp = client.post("/dedupe/confirm-jobs", json={"candidate_ids": [1]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    uuid.UUID(body["job_id"])
    assert [job_id for job_id, _ in client.submitted] == [body["job_id"]]


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


def test_create_delete_plan_and_fetch_detail(client):
    candidate_id = _seed_delete_candidate(client)

    resp = client.post(
        "/dedupe/delete-plans",
        json={"name": "delete duplicates", "candidate_ids": [candidate_id], "rate_limit_seconds": 0},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft"
    assert body["total_items"] == 1

    detail = client.get(f"/dedupe/delete-plans/{body['plan_id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["plan"]["id"] == body["plan_id"]
    assert detail_body["items"][0]["candidate_id"] == candidate_id
    assert detail_body["items"][0]["remote_file_id"] == "file-1"


def test_execute_delete_plan_job_requires_confirm(client):
    candidate_id = _seed_delete_candidate(client)
    plan = client.post(
        "/dedupe/delete-plans",
        json={"name": "delete duplicates", "candidate_ids": [candidate_id], "rate_limit_seconds": 0},
    ).json()

    resp = client.post(f"/dedupe/delete-plans/{plan['plan_id']}/execute-jobs", json={"confirm": False})

    assert resp.status_code == 400
    assert client.submitted == []


def test_execute_delete_plan_job_endpoint_returns_uuid(client):
    candidate_id = _seed_delete_candidate(client)
    plan = client.post(
        "/dedupe/delete-plans",
        json={"name": "delete duplicates", "candidate_ids": [candidate_id], "rate_limit_seconds": 0},
    ).json()

    resp = client.post(f"/dedupe/delete-plans/{plan['plan_id']}/execute-jobs", json={"confirm": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    uuid.UUID(body["job_id"])
    assert [job_id for job_id, _ in client.submitted] == [body["job_id"]]


def test_start_jobs_return_409_when_same_type_running(client):
    """库里已有同类型未完成任务时，三个启动接口都返回 409 且不提交新任务。"""
    _seed_running_job(client, "scan-running", "dedupe:scan")
    _seed_running_job(client, "confirm-running", "dedupe:confirm")
    _seed_running_job(client, "delete-running", "dedupe:delete")

    scan = client.post("/dedupe/scan-jobs", json={"tree_import_id": 1})
    confirm = client.post("/dedupe/confirm-jobs", json={"candidate_ids": [1]})
    delete = client.post("/dedupe/delete-plans/1/execute-jobs", json={"confirm": True})

    assert (scan.status_code, scan.json()["detail"]) == (409, "已有去重扫描任务在运行")
    assert (confirm.status_code, confirm.json()["detail"]) == (409, "已有去重确认任务在运行")
    assert (delete.status_code, delete.json()["detail"]) == (409, "已有去重删除任务在运行")
    assert client.submitted == []


def test_confirm_and_delete_jobs_use_singleton_115_client(client, monkeypatch):
    """后台确认/删除任务拿到的是全局 115 客户端，而不是新建实例；进度和摘要照旧落库。"""
    from app.api.routes import dedupe as _dedupe
    from app.services.background_job_service import BackgroundJobService
    from app.services.dedupe.confirmation_service import DedupeConfirmationSummary
    from app.services.dedupe.delete_plan_service import DedupeDeletePlanSummary
    from app.services.job_runner import run_job

    seen_clients: dict[str, object] = {}

    class FakeConfirmationService:
        def __init__(self, db, client):
            seen_clients["confirm"] = client

        def confirm_candidates(self, candidate_ids):
            return DedupeConfirmationSummary(requested=len(candidate_ids), resolved=len(candidate_ids), failed=0)

    class FakeDeletePlanService:
        def __init__(self, db, client):
            seen_clients["delete"] = client

        def execute_plan(self, plan_id, *, confirm):
            assert confirm is True
            return DedupeDeletePlanSummary(plan_id=plan_id, total=3, deleted=3, failed=0, skipped=0)

    monkeypatch.setattr(_dedupe, "DedupeConfirmationService", FakeConfirmationService)
    monkeypatch.setattr(_dedupe, "DedupeDeletePlanService", FakeDeletePlanService)
    # 同步执行，便于断言
    monkeypatch.setattr(_dedupe, "submit_job", lambda job_id, work: run_job(job_id, work))

    confirm = client.post("/dedupe/confirm-jobs", json={"candidate_ids": [1, 2]})
    delete = client.post("/dedupe/delete-plans/7/execute-jobs", json={"confirm": True})

    assert confirm.status_code == 200
    assert delete.status_code == 200
    assert seen_clients == {"confirm": _SENTINEL_115_CLIENT, "delete": _SENTINEL_115_CLIENT}
    with client.session_factory() as db:
        confirm_state = BackgroundJobService.get(db, confirm.json()["job_id"])
        delete_state = BackgroundJobService.get(db, delete.json()["job_id"])
    assert confirm_state["done"] is True
    assert confirm_state["stage"] == "完成"
    assert (confirm_state["current"], confirm_state["total"]) == (2, 2)
    assert confirm_state["summary"] == {"requested": 2, "resolved": 2, "failed": 0}
    assert delete_state["done"] is True
    assert (delete_state["current"], delete_state["total"]) == (3, 3)
    assert delete_state["summary"]["plan_id"] == 7


def test_active_jobs_and_progress_read_background_jobs(client):
    """active 和进度推送只查 background_jobs 表，对外任务类型去掉 dedupe: 前缀。"""
    import json

    _seed_running_job(client, "confirm-running", "dedupe:confirm")

    active = client.get("/dedupe/jobs/active")
    assert active.status_code == 200
    body = active.json()
    assert body["scan"] is None
    assert body["delete"] is None
    assert body["confirm"]["job_id"] == "confirm-running"
    assert body["confirm"]["job_type"] == "confirm"

    # 进度推送对未完成任务不会自行结束，这里用已完成任务验证（推完两帧后断开）
    from app.services.background_job_service import BackgroundJobService

    with client.session_factory() as db:
        BackgroundJobService.update(db, "confirm-running", stage="完成", done=True)
    with client.stream("GET", "/dedupe/jobs/confirm-running/progress") as resp:
        assert resp.status_code == 200
        frames = [
            json.loads(line[len("data:"):].strip())
            for line in resp.iter_lines()
            if line.startswith("data:")
        ]
    assert len(frames) == 2
    assert all(frame["job_id"] == "confirm-running" for frame in frames)
    assert all(frame["job_type"] == "confirm" for frame in frames)
    assert all(frame["done"] is True for frame in frames)

    with client.stream("GET", "/dedupe/jobs/no-such-job/progress") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                assert json.loads(line[len("data:"):].strip()) == {"error": "not found"}
                break
