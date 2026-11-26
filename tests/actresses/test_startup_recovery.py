"""18x 重启时把停在「执行中」/「待开始」的女优删除批次标为中断。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.actresses import ActressDeleteBatch
from app.services.actresses.delete_batch_service import recover_interrupted_batches


def _add_batches(db_session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for status in ("pending", "running", "failed", "completed", "interrupted"):
        batch = ActressDeleteBatch(status=status, note="原备注" if status == "failed" else None)
        db_session.add(batch)
        db_session.flush()
        ids[status] = batch.id
    db_session.commit()
    return ids


def _statuses(db_session, ids: dict[str, int]) -> dict[str, tuple[str, str | None, bool]]:
    db_session.expire_all()
    result = {}
    for original, batch_id in ids.items():
        batch = db_session.get(ActressDeleteBatch, batch_id)
        result[original] = (batch.status, batch.note, batch.finished_at is not None)
    return result


def test_recover_marks_running_and_pending_batches_interrupted(db_session):
    ids = _add_batches(db_session)

    assert recover_interrupted_batches(db_session) == 2
    db_session.commit()

    statuses = _statuses(db_session, ids)
    assert statuses["pending"] == ("interrupted", "服务重启时中断", True)
    assert statuses["running"] == ("interrupted", "服务重启时中断", True)
    assert statuses["failed"] == ("failed", "原备注", False)
    assert statuses["completed"] == ("completed", None, False)
    assert statuses["interrupted"] == ("interrupted", None, False)


def test_lifespan_recovers_delete_batches(db_session, monkeypatch):
    """走一遍真实的启动流程：启动恢复段落会把删除批次标为中断。"""
    from app.db import session as session_module
    from app.main import app

    ids = _add_batches(db_session)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("JELLYFIN_ENABLED", "false")
    get_settings.cache_clear()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    try:
        with TestClient(app):
            pass
    finally:
        get_settings.cache_clear()

    statuses = _statuses(db_session, ids)
    assert statuses["pending"][0] == "interrupted"
    assert statuses["running"][0] == "interrupted"
    assert statuses["failed"][0] == "failed"
