from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.actresses import ActressDeleteBatch, ActressDeleteCandidate, JellyfinMediaActor
from app.models.background_jobs import BackgroundJob
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses import job_runner
from app.services.actresses.archive_service import ArchiveService
from app.services.actresses.delete_batch_service import BatchSummary
from app.services.actresses.names import normalize_actress_name
from app.services.jellyfin.client import JellyfinError
from app.services.job_runner import create_job, run_job

_ACTRESS_ENV = ("ACTRESS_ENABLED", "ACTRESS_SOURCE_ROOT", "ACTRESS_ORGANIZED_ROOT", "ACTRESS_PATH_MAP")


def _settings(tmp_path: Path, **overrides) -> SimpleNamespace:
    """女优功能全部就绪的配置；路径都在临时目录里（删除服务被替换，不会真的访问）。"""
    values = dict(
        jellyfin_enabled=True,
        jellyfin_base_url="http://jellyfin.test",
        jellyfin_api_key="test-key",
        jellyfin_timeout_seconds=3,
        jellyfin_page_size=50,
        media_library_strm_roots=[str(tmp_path / "scan")],
        actress_enabled=True,
        actress_source_root=str(tmp_path / "source"),
        actress_organized_root=str(tmp_path / "organized"),
        actress_path_map=f"{tmp_path / 'scan'}=>{tmp_path / 'organized'}",
        openlist_url=None,
        openlist_token=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _add_film(db_session, root: Path, number: str, actors: tuple[str, ...], *, actor_dir: str = "甲") -> str:
    """插入一部单段片子（一个 115 STRM 条目和它的 NFO 演员行），返回番号目录。"""
    film_dir = root / actor_dir / number
    item = JellyfinMediaItem(source="strm_115", path=str(film_dir / f"{number}.strm"), active=True)
    db_session.add(item)
    db_session.flush()
    for position, name in enumerate(actors):
        db_session.add(
            JellyfinMediaActor(
                media_item_id=item.id,
                position=position,
                raw_name=name,
                name_normalized=normalize_actress_name(name),
            )
        )
    db_session.commit()
    return str(film_dir)


def _new_batch(db_session) -> int:
    batch = ActressDeleteBatch(status="pending")
    db_session.add(batch)
    db_session.commit()
    return batch.id


def _batch(db_session, batch_id: int) -> ActressDeleteBatch:
    db_session.expire_all()
    return db_session.get(ActressDeleteBatch, batch_id)


def _fake_run(monkeypatch, *, deleted: int, received: dict | None = None) -> None:
    """替换删除服务：把批次记为完成并返回给定的删除部数，记录收到的参数。"""

    def fake_run(_self, db, batch_id, **kwargs):
        if received is not None:
            received.update(kwargs)
        batch = db.get(ActressDeleteBatch, batch_id)
        batch.status = "completed"
        batch.deleted_films = deleted
        db.commit()
        return BatchSummary(batch_id=batch_id, deleted=deleted, failed=0, skipped=0)

    monkeypatch.setattr(job_runner.DeleteBatchService, "run", fake_run)


def _fake_jellyfin(monkeypatch, *, library_id: str | None = "lib-115", refresh_error: Exception | None = None) -> list:
    """替换 Jellyfin 客户端，返回调用记录。"""
    calls: list = []

    class FakeClient:
        def __init__(self, base_url, api_key, timeout, page_size):
            calls.append(("init", base_url, api_key))

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            calls.append(("close",))
            return None

        def find_library_id(self, locations):
            calls.append(("find", list(locations)))
            return library_id

        def refresh_library(self, found_id):
            calls.append(("refresh", found_id))
            if refresh_error is not None:
                raise refresh_error

    monkeypatch.setattr(job_runner, "JellyfinClient", FakeClient)
    return calls


def test_refresh_work_builds_archive_and_candidates(db_session, tmp_path, monkeypatch):
    root = tmp_path / "scan"
    first = _add_film(db_session, root, "ABC-001", ("甲", "乙"))
    second = _add_film(db_session, root, "ABC-002", ("甲",))
    _add_film(db_session, root, "ABC-003", ("乙",), actor_dir="乙")
    actress = ArchiveService().ensure_actresses(db_session, ["甲"])[0]
    ArchiveService().set_status(db_session, [actress.id], "blacklist", source="web")
    monkeypatch.setattr(job_runner, "get_settings", lambda: _settings(tmp_path))
    progress_calls: list[tuple] = []

    summary = job_runner.refresh_work(db_session, lambda *args: progress_calls.append(args))

    # 甲已建档，乙是这次新建的；甲的两部片进清单，由每日任务加入、默认勾选
    assert summary == {"created": 1, "actresses": 2, "candidates_added": 2, "candidates_removed": 0}
    rows = db_session.scalars(select(ActressDeleteCandidate).order_by(ActressDeleteCandidate.film_dir)).all()
    assert [(row.film_dir, row.added_by, row.selected) for row in rows] == [
        (first, "daily", True),
        (second, "daily", True),
    ]
    assert progress_calls[-1] == ("完成", 1, 1)


def test_delete_ready_requires_both_roots(monkeypatch):
    for name in _ACTRESS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JELLYFIN_ENABLED", "true")

    defaults = Settings(_env_file=None)
    assert defaults.actress_enabled is False
    assert defaults.actress_source_root is None
    assert defaults.actress_organized_root is None
    assert defaults.actress_path_map == ""
    assert job_runner.actress_enabled(defaults) is False

    monkeypatch.setenv("ACTRESS_ENABLED", "true")
    monkeypatch.setenv("ACTRESS_SOURCE_ROOT", "/虚构/porn_tv1")
    monkeypatch.setenv("ACTRESS_PATH_MAP", "/虚构/只读=>/虚构/可写")
    only_source = Settings(_env_file=None)
    assert only_source.actress_path_map == "/虚构/只读=>/虚构/可写"
    assert job_runner.actress_enabled(only_source) is True
    assert job_runner.actress_delete_ready(only_source) is False

    monkeypatch.setenv("ACTRESS_ORGANIZED_ROOT", "/虚构/302porn_tv1")
    assert job_runner.actress_delete_ready(Settings(_env_file=None)) is True

    # 只配了番号目录根也不行
    monkeypatch.delenv("ACTRESS_SOURCE_ROOT")
    assert job_runner.actress_delete_ready(Settings(_env_file=None)) is False

    # 总开关打开但 Jellyfin 扫描没开：女优功能整体不启用
    monkeypatch.setenv("ACTRESS_SOURCE_ROOT", "/虚构/porn_tv1")
    monkeypatch.setenv("JELLYFIN_ENABLED", "false")
    disabled = Settings(_env_file=None)
    assert job_runner.actress_enabled(disabled) is False
    assert job_runner.actress_delete_ready(disabled) is False


@pytest.mark.parametrize(
    ("deleted", "api_key", "expected"),
    [(0, "test-key", "skipped"), (1, "test-key", "done"), (1, None, "skipped")],
    ids=["nothing-deleted", "deleted", "jellyfin-not-configured"],
)
def test_delete_work_refreshes_jellyfin_only_when_something_deleted(
    db_session, tmp_path, monkeypatch, fake_client, deleted, api_key, expected
):
    settings = _settings(tmp_path, jellyfin_api_key=api_key)
    monkeypatch.setattr(job_runner, "get_settings", lambda: settings)
    received: dict = {}
    _fake_run(monkeypatch, deleted=deleted, received=received)
    calls = _fake_jellyfin(monkeypatch)
    batch_id = _new_batch(db_session)

    def progress(*_args):
        return None

    summary = job_runner.delete_work(batch_id, fake_client)(db_session, progress)

    assert summary == {"batch_id": batch_id, "deleted": deleted, "failed": 0, "skipped": 0}
    batch = _batch(db_session, batch_id)
    assert batch.status == "completed"
    assert batch.jellyfin_refresh == expected
    if expected == "done":
        assert calls == [
            ("init", "http://jellyfin.test", "test-key"),
            ("find", [str(tmp_path / "scan")]),
            ("refresh", "lib-115"),
            ("close",),
        ]
    else:
        assert calls == []

    # 删除服务收到的守卫、路径换算、根目录都来自配置
    assert received["client_115"] is fake_client
    assert received["guard"].source_root == str(tmp_path / "source")
    assert received["guard"].organized_root == str(tmp_path / "organized")
    scan_dir = str(tmp_path / "scan" / "甲" / "ABC-001")
    assert received["mapper"].map(scan_dir) == str(tmp_path / "organized" / "甲" / "ABC-001")
    assert received["strm_roots"] == [str(tmp_path / "scan")]


@pytest.mark.parametrize(
    ("url", "token", "expected"),
    [
        ("http://openlist.test:5244", "test-token", True),
        ("http://openlist.test:5244", None, False),
        (None, "test-token", False),
    ],
    ids=["configured", "no-token", "no-url"],
)
def test_delete_work_passes_openlist_only_when_configured(
    db_session, tmp_path, monkeypatch, fake_client, url, token, expected
):
    settings = _settings(tmp_path, openlist_url=url, openlist_token=token)
    monkeypatch.setattr(job_runner, "get_settings", lambda: settings)
    received: dict = {}
    _fake_run(monkeypatch, deleted=0, received=received)
    batch_id = _new_batch(db_session)

    job_runner.delete_work(batch_id, fake_client)(db_session, lambda *_args: None)

    openlist = received["openlist"]
    if expected:
        assert openlist is not None
        assert openlist.base_url == "http://openlist.test:5244"
    else:
        assert openlist is None


@pytest.mark.parametrize(
    ("library_id", "refresh_error"),
    [
        ("lib-115", JellyfinError("虚构：Jellyfin 连不上")),
        ("lib-115", RuntimeError("虚构：意外错误")),
        (None, None),
    ],
    ids=["jellyfin-error", "unexpected-error", "library-not-found"],
)
def test_delete_work_succeeds_when_jellyfin_refresh_fails(
    db_session, tmp_path, monkeypatch, fake_client, library_id, refresh_error
):
    monkeypatch.setattr(job_runner, "get_settings", lambda: _settings(tmp_path))
    _fake_run(monkeypatch, deleted=1)
    _fake_jellyfin(monkeypatch, library_id=library_id, refresh_error=refresh_error)
    batch_id = _new_batch(db_session)

    summary = job_runner.delete_work(batch_id, fake_client)(db_session, lambda *_args: None)

    # 扫库失败不影响删除结果
    assert summary == {"batch_id": batch_id, "deleted": 1, "failed": 0, "skipped": 0}
    batch = _batch(db_session, batch_id)
    assert batch.status == "completed"
    assert batch.deleted_films == 1
    assert batch.jellyfin_refresh == "error"


def test_delete_work_marks_batch_interrupted_on_unexpected_error(db_session, tmp_path, monkeypatch, fake_client):
    monkeypatch.setattr(job_runner, "get_settings", lambda: _settings(tmp_path))
    calls = _fake_jellyfin(monkeypatch)
    batch_id = _new_batch(db_session)

    def crashing_run(_self, db, run_batch_id, **_kwargs):
        batch = db.get(ActressDeleteBatch, run_batch_id)
        batch.status = "running"
        db.commit()
        # 没提交的半截改动，标中断前必须先回滚掉
        batch.deleted_films = 99
        raise RuntimeError("虚构：数据库连接断开")

    monkeypatch.setattr(job_runner.DeleteBatchService, "run", crashing_run)

    class SessionFactory:
        def __call__(self):
            return db_session

    # 统一启动器在运行时从 app.db.session 取 SessionLocal
    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    job_id = create_job(db_session, job_runner.JOB_DELETE)

    run_job(job_id, job_runner.delete_work(batch_id, fake_client))

    batch = _batch(db_session, batch_id)
    assert batch.status == "interrupted"
    assert batch.deleted_films == 0
    assert batch.jellyfin_refresh is None
    assert calls == []
    # 异常继续抛给任务机制，任务记失败
    job = db_session.get(BackgroundJob, job_id)
    assert job.done is True
    assert job.stage == "失败"
    assert "虚构：数据库连接断开" in (job.error or "")


def test_job_types():
    assert job_runner.JOB_REFRESH == "actress:refresh"
    assert job_runner.JOB_DELETE == "actress:delete"
