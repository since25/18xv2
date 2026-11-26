from __future__ import annotations

from types import SimpleNamespace

from app.models.background_jobs import BackgroundJob
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin import job_runner
from app.services.jellyfin.scan_service import MediaScanError


def test_start_job_rejects_same_type_active(db_session):
    first = job_runner.start_job(db_session, job_runner.JOB_SCAN)

    try:
        job_runner.start_job(db_session, job_runner.JOB_SCAN)
    except job_runner.JobAlreadyRunning:
        pass
    else:
        raise AssertionError("同类型运行中的任务应被拒绝")

    assert BackgroundJobService.get(db_session, first)["done"] is False


def test_run_scan_job_records_failure(db_session, monkeypatch):
    job_id = job_runner.start_job(db_session, job_runner.JOB_SCAN)

    class SessionFactory:
        def __call__(self):
            return db_session

    def fail_scan(*_args, **_kwargs):
        raise MediaScanError("虚构媒体根目录不可读")

    # 统一启动器在运行时从 app.db.session 取 SessionLocal
    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner.MediaScanService, "scan", fail_scan)
    job_runner.run_scan_job(job_id)

    row = db_session.get(BackgroundJob, job_id)
    assert row is not None
    assert row.done is True
    assert row.stage == "失败"
    assert "虚构媒体根目录不可读" in (row.error or "")


def test_run_cover_job_records_summary(db_session, monkeypatch):
    job_id = job_runner.start_job(db_session, job_runner.JOB_COVERS)

    class SessionFactory:
        def __call__(self):
            return db_session

    settings = SimpleNamespace(
        jellyfin_cover_since="2025-01-01T00:00:00+00:00",
        media_library_local_roots=[],
        jellyfin_cover_deadline_minute=25,
    )
    # 统一启动器在运行时从 app.db.session 取 SessionLocal
    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner, "get_settings", lambda: settings)
    monkeypatch.setattr(
        job_runner.CoverService,
        "run",
        lambda *_args, **_kwargs: {
            "candidates": 1,
            "generated": 1,
            "existing_cover_skipped": 0,
            "existing_video_skipped": 0,
            "fallback_middle_frames": 0,
            "failed": 0,
            "deadline_remaining": 0,
            "filename_too_long_skipped": 0,
        },
    )

    job_runner.run_cover_job(job_id)

    row = db_session.get(BackgroundJob, job_id)
    assert row is not None
    assert row.done is True
    assert row.stage == "完成"
    assert row.summary_json is not None and '"generated": 1' in row.summary_json


def test_display_names_enabled_requires_flag_and_sync_config():
    base = dict(jellyfin_enabled=True, jellyfin_base_url="http://jf", jellyfin_api_key="k")

    assert job_runner.jellyfin_display_names_enabled(SimpleNamespace(**base, jellyfin_display_names_enabled=True)) is True
    assert job_runner.jellyfin_display_names_enabled(SimpleNamespace(**base, jellyfin_display_names_enabled=False)) is False
    assert (
        job_runner.jellyfin_display_names_enabled(
            SimpleNamespace(
                jellyfin_enabled=True,
                jellyfin_base_url=None,
                jellyfin_api_key="k",
                jellyfin_display_names_enabled=True,
            )
        )
        is False
    )


def _names_settings(**overrides):
    values = dict(
        jellyfin_enabled=True,
        jellyfin_base_url="http://jellyfin.test",
        jellyfin_api_key="test-key",
        jellyfin_timeout_seconds=3,
        jellyfin_page_size=50,
        media_library_local_roots=["/r/已整理"],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_run_names_job_records_summary_and_passes_options(db_session, monkeypatch):
    job_id = job_runner.start_job(db_session, job_runner.JOB_NAMES)
    received: dict = {}

    class SessionFactory:
        def __call__(self):
            return db_session

    def fake_sync(_self, _db, _client, **kwargs):
        received.update(kwargs)
        return {"to_update": 1, "updated": 0}

    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner, "get_settings", lambda: _names_settings())
    monkeypatch.setattr(job_runner.DisplayNameSyncService, "sync", fake_sync)

    job_runner.run_names_job(job_id, dry_run=True, keyword="甲")

    row = db_session.get(BackgroundJob, job_id)
    assert row is not None
    assert row.done is True
    assert row.stage == "完成"
    assert row.summary_json is not None and '"to_update": 1' in row.summary_json
    assert received["dry_run"] is True
    assert received["keyword"] == "甲"
    assert received["restore"] is False
    assert received["local_roots"] == ["/r/已整理"]


def test_run_names_job_records_failure_without_config(db_session, monkeypatch):
    job_id = job_runner.start_job(db_session, job_runner.JOB_NAMES)

    class SessionFactory:
        def __call__(self):
            return db_session

    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner, "get_settings", lambda: _names_settings(jellyfin_api_key=None))

    job_runner.run_names_job(job_id)

    row = db_session.get(BackgroundJob, job_id)
    assert row is not None
    assert row.done is True
    assert row.stage == "失败"
    assert "缺少地址/API Key" in (row.error or "")
