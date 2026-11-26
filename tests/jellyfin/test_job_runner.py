from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.background_jobs import BackgroundJob
from app.services.actresses import job_runner as actress_job_runner
from app.services.actresses.collection_sync import ActressCollectionSyncService
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
        jellyfin_display_names_page_size=5000,
        jellyfin_display_names_timeout_seconds=60,
        media_library_local_roots=["/r/已整理"],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_names_work_uses_its_own_page_size_and_timeout(db_session, monkeypatch):
    job_id = job_runner.start_job(db_session, job_runner.JOB_NAMES)
    created: dict = {}

    class SessionFactory:
        def __call__(self):
            return db_session

    class RecordingClient:
        def __init__(self, base_url, api_key, timeout, page_size, *args, **kwargs):
            created.update(timeout=timeout, page_size=page_size)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner, "get_settings", lambda: _names_settings())
    monkeypatch.setattr(job_runner, "JellyfinClient", RecordingClient)
    monkeypatch.setattr(job_runner.DisplayNameSyncService, "sync", lambda *_args, **_kwargs: {"to_update": 0})

    job_runner.run_names_job(job_id)

    # 显示名用自己的每页条数和超时，合集同步的 JELLYFIN_PAGE_SIZE 不受影响
    assert created == {"timeout": 60, "page_size": 5000}


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


class _StopLoop(BaseException):
    """测试用：每日循环跑完一轮、开始等待时抛出，结束循环。"""


def _daily_settings(**overrides):
    values = dict(
        jellyfin_daily_run_hour=3,
        jellyfin_enabled=True,
        jellyfin_base_url="http://jellyfin.test",
        jellyfin_api_key="test-key",
        jellyfin_display_names_enabled=True,
        actress_enabled=True,
        media_library_strm_roots=["/虚构/番号库"],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _run_daily_loop_once(monkeypatch, db_session, settings, calls: list[str]) -> None:
    """把时间固定在运行小时跑一轮每日循环，各步骤按执行顺序记进 calls。

    扫描、合集同步、显示名只记录调用；女优步骤走真实的建任务和统一启动器。
    """

    class FixedNow:
        @staticmethod
        def now():
            return datetime(2026, 1, 1, 3, 0)

    async def stop_sleep(_seconds):
        raise _StopLoop

    async def direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    class SessionFactory:
        def __call__(self):
            return db_session

    monkeypatch.setattr(job_runner, "datetime", FixedNow)
    monkeypatch.setattr(
        job_runner,
        "asyncio",
        SimpleNamespace(sleep=stop_sleep, to_thread=direct_to_thread, CancelledError=asyncio.CancelledError),
    )
    monkeypatch.setattr(job_runner, "SessionLocal", SessionFactory())
    # 统一启动器在运行时从 app.db.session 取 SessionLocal
    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    monkeypatch.setattr(job_runner, "run_scan_job", lambda _job_id: calls.append("scan"))
    monkeypatch.setattr(job_runner, "run_sync_job", lambda _job_id: calls.append("sync"))
    monkeypatch.setattr(job_runner, "run_names_job", lambda _job_id: calls.append("names"))
    monkeypatch.setattr(actress_job_runner, "get_settings", lambda: settings)

    with pytest.raises(_StopLoop):
        asyncio.run(job_runner.jellyfin_daily_loop(settings))


def _refresh_jobs(db_session) -> list[BackgroundJob]:
    db_session.expire_all()
    return list(
        db_session.scalars(select(BackgroundJob).where(BackgroundJob.job_type == actress_job_runner.JOB_REFRESH))
    )


def _record_refresh(monkeypatch, calls: list[str]) -> None:
    def fake_refresh(_db, _progress):
        calls.append("actress")
        return {"created": 0, "actresses": 0, "candidates_added": 0, "candidates_removed": 0}

    monkeypatch.setattr(actress_job_runner, "refresh_work", fake_refresh)


def test_daily_loop_runs_actress_refresh_between_scan_and_sync(db_session, monkeypatch):
    calls: list[str] = []
    _record_refresh(monkeypatch, calls)

    _run_daily_loop_once(monkeypatch, db_session, _daily_settings(), calls)

    assert calls == ["scan", "actress", "sync", "names"]
    jobs = _refresh_jobs(db_session)
    assert [(job.done, job.stage) for job in jobs] == [(True, "完成")]


def test_daily_loop_skips_actress_when_disabled(db_session, monkeypatch):
    calls: list[str] = []
    _record_refresh(monkeypatch, calls)

    _run_daily_loop_once(monkeypatch, db_session, _daily_settings(actress_enabled=False), calls)

    assert calls == ["scan", "sync", "names"]
    assert _refresh_jobs(db_session) == []


def test_daily_loop_continues_to_sync_when_actress_refresh_fails(db_session, monkeypatch):
    calls: list[str] = []

    # 没配 115 番号库根目录：女优步骤报错，后面的合集同步照常跑
    _run_daily_loop_once(monkeypatch, db_session, _daily_settings(media_library_strm_roots=[]), calls)

    assert calls == ["scan", "sync", "names"]
    jobs = _refresh_jobs(db_session)
    assert [(job.done, job.stage) for job in jobs] == [(True, "失败")]
    assert "未配置 115 番号库根目录" in (jobs[0].error or "")


def test_daily_loop_skips_actress_when_refresh_already_running(db_session, monkeypatch):
    calls: list[str] = []
    _record_refresh(monkeypatch, calls)
    running = job_runner.start_job(db_session, actress_job_runner.JOB_REFRESH)

    _run_daily_loop_once(monkeypatch, db_session, _daily_settings(), calls)

    assert calls == ["scan", "sync", "names"]
    assert [job.job_id for job in _refresh_jobs(db_session)] == [running]


class _RecordingClient:
    def __init__(self, base_url, api_key, timeout, page_size, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


def _sync_settings(**overrides):
    values = dict(actress_enabled=True, media_library_strm_roots=["/虚构/番号库"])
    values.update(overrides)
    return _names_settings(**values)


def test_sync_work_includes_actress_collections_when_enabled(db_session, monkeypatch):
    received: dict = {}

    def fake_actress_sync(_self, _db, client, *, strm_roots):
        received.update(client=client, strm_roots=strm_roots)
        return {"collections_created": 2, "conflicts": 1}

    monkeypatch.setattr(job_runner, "get_settings", lambda: _sync_settings())
    monkeypatch.setattr(job_runner, "JellyfinClient", _RecordingClient)
    monkeypatch.setattr(
        job_runner.CollectionSyncService, "sync", lambda *_args: {"collections_created": 1, "errors": 0}
    )
    monkeypatch.setattr(ActressCollectionSyncService, "sync", fake_actress_sync)

    summary = job_runner.sync_work(db_session, lambda *_args: None)

    assert summary == {
        "collections_created": 1,
        "errors": 0,
        "actress_collections_created": 2,
        "actress_conflicts": 1,
    }
    # 和关键词合集用同一个客户端
    assert isinstance(received["client"], _RecordingClient)
    assert received["strm_roots"] == ["/虚构/番号库"]


def test_sync_work_skips_actress_collections_when_disabled(db_session, monkeypatch):
    def fail_actress_sync(*_args, **_kwargs):
        raise AssertionError("女优功能关闭时不应同步女优合集")

    monkeypatch.setattr(job_runner, "get_settings", lambda: _sync_settings(actress_enabled=False))
    monkeypatch.setattr(job_runner, "JellyfinClient", _RecordingClient)
    monkeypatch.setattr(job_runner.CollectionSyncService, "sync", lambda *_args: {"collections_created": 1})
    monkeypatch.setattr(ActressCollectionSyncService, "sync", fail_actress_sync)

    assert job_runner.sync_work(db_session, lambda *_args: None) == {"collections_created": 1}
