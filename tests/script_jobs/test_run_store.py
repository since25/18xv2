from __future__ import annotations

from sqlalchemy import select

from app.models.script_runs import ScriptRun, ScriptRunItem
from app.services.script_jobs import run_store


def test_create_run_sets_unique_key_and_status(db_session):
    first = run_store.create_run(db_session, job_name="sehuatang", trigger="manual", dry_run=True, status="queued")
    second = run_store.create_run(db_session, job_name="sehuatang", trigger="manual", dry_run=True, status="queued")
    assert first.run_key != second.run_key
    assert first.run_key.startswith("sehuatang:manual:")
    assert first.status == "queued"
    assert first.dry_run is True
    assert first.finished_at is None


def test_finish_run_truncates_items_and_keeps_counts(db_session):
    run = run_store.create_run(db_session, job_name="sehuatang", trigger="scheduled", dry_run=False, status="running")
    items = [{"kind": "submitted", "path": f"示例标题-{i}", "target_path": None, "keyword": None, "message": None}
             for i in range(5001)]
    run_store.finish_run(
        db_session,
        run,
        exit_code=0,
        status="success",
        counts={"submitted": 5001},
        items=items,
        error_reason=None,
    )
    saved = db_session.scalar(select(ScriptRun).where(ScriptRun.id == run.id))
    assert saved.status == "success"
    assert saved.items_truncated is True
    assert saved.counts["submitted"] == 5001
    assert saved.finished_at is not None
    assert len(db_session.scalars(select(ScriptRunItem).where(ScriptRunItem.run_id == run.id)).all()) == 5000


def test_counts_dict_includes_sehuatang_keys():
    counts = run_store.counts_dict({"submitted": 3, "title_blocked": 2})
    assert counts["submitted"] == 3
    assert counts["title_blocked"] == 2
    assert counts["deleted_files"] == 0
