"""统一后台任务启动器 app/services/job_runner.py 的测试。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json

from pydantic import BaseModel
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.models.background_jobs import BackgroundJob
from app.services import job_runner
from app.services.background_job_service import BackgroundJobService


@pytest.fixture
def session_factory(db_session, monkeypatch):
    """让启动器在运行时取到绑定测试库的 SessionLocal。"""
    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    return factory


def _load(factory, job_id: str) -> dict | None:
    """用新会话读库，避免读到 db_session 身份映射里的旧对象。"""
    with factory() as session:
        return BackgroundJobService.get(session, job_id)


def _collect(stream) -> list[dict]:
    """把推送生成器跑完，返回解析后的每一帧。"""

    async def run() -> list[str]:
        return [chunk async for chunk in stream]

    chunks = asyncio.run(run())
    frames = []
    for chunk in chunks:
        assert chunk.startswith("data: ") and chunk.endswith("\n\n")
        frames.append(json.loads(chunk[len("data: "):].strip()))
    return frames


@pytest.fixture
def no_sleep(monkeypatch):
    """推送生成器每秒读库一次，测试里替换掉 asyncio.sleep 避免真等。"""
    calls: list[float] = []

    async def fake_sleep(seconds, *_args, **_kwargs):
        calls.append(seconds)

    monkeypatch.setattr(job_runner.asyncio, "sleep", fake_sleep)
    return calls


# ── run_job ─────────────────────────────────────────────────────────────


def test_run_job_marks_success_with_summary(db_session, session_factory):
    job_id = job_runner.create_job(db_session, "test:ok")

    job_runner.run_job(job_id, lambda _session, _cb: {"n": 3})

    state = _load(session_factory, job_id)
    assert state["done"] is True
    assert state["stage"] == "完成"
    assert state["summary"] == {"n": 3}
    assert state["error"] is None
    assert state["finished_at"] is not None


def test_run_job_progress_callback_persists(db_session, session_factory):
    job_id = job_runner.create_job(db_session, "test:progress")
    seen: dict = {}

    def work(_session, cb):
        cb("扫描", 2, 5)
        seen.update(_load(session_factory, job_id))
        return None

    job_runner.run_job(job_id, work)

    assert seen["stage"] == "扫描"
    assert seen["current"] == 2
    assert seen["total"] == 5
    assert seen["done"] is False
    final = _load(session_factory, job_id)
    assert final["done"] is True
    # 成功收尾不改 current/total
    assert final["current"] == 2
    assert final["total"] == 5


def test_run_job_marks_failure_and_does_not_raise(db_session, session_factory):
    job_id = job_runner.create_job(db_session, "test:fail")

    def work(_session, _cb):
        raise RuntimeError("boom")

    job_runner.run_job(job_id, work)  # 不应抛出

    state = _load(session_factory, job_id)
    assert state["done"] is True
    assert state["stage"] == "失败"
    assert state["error"] == "boom"
    assert state["finished_at"] is not None


def test_run_job_rolls_back_broken_session_before_marking_failure(db_session, session_factory):
    job_id = job_runner.create_job(db_session, "test:broken")

    def work(session, _cb):
        # 主键重复导致 flush 失败，会话进入“必须先回滚”的状态
        session.add(BackgroundJob(job_id=job_id, job_type="test:dup", stage="x", current=0, total=0, done=False))
        session.flush()

    job_runner.run_job(job_id, work)

    state = _load(session_factory, job_id)
    assert state["done"] is True
    assert state["stage"] == "失败"
    assert state["error"]
    assert state["job_type"] == "test:broken"


@pytest.mark.parametrize("result", [None, {"x": object()}])
def test_run_job_none_or_unserializable_summary_still_completes(db_session, session_factory, result):
    job_id = job_runner.create_job(db_session, "test:summary")

    job_runner.run_job(job_id, lambda _session, _cb: result)

    state = _load(session_factory, job_id)
    assert state["done"] is True
    assert state["stage"] == "完成"
    assert state["summary"] is None
    assert state["error"] is None


class _ModelSummary(BaseModel):
    total: int
    label: str


@dataclass
class _DataclassSummary:
    total: int
    items: list[str]


def test_run_job_accepts_pydantic_and_dataclass_summary(db_session, session_factory):
    first = job_runner.create_job(db_session, "test:pydantic")
    job_runner.run_job(first, lambda _s, _cb: _ModelSummary(total=2, label="虚构"))
    second = job_runner.create_job(db_session, "test:dataclass")
    job_runner.run_job(second, lambda _s, _cb: _DataclassSummary(total=1, items=["a"]))

    assert _load(session_factory, first)["summary"] == {"total": 2, "label": "虚构"}
    assert _load(session_factory, second)["summary"] == {"total": 1, "items": ["a"]}


# ── create_job ──────────────────────────────────────────────────────────


def test_create_job_rejects_second_job_of_same_type(db_session, session_factory):
    job_runner.create_job(db_session, "test:single")

    with pytest.raises(job_runner.JobAlreadyRunning):
        job_runner.create_job(db_session, "test:single")

    assert len(BackgroundJobService.list_active(db_session, "test:single")) == 1
    other = job_runner.create_job(db_session, "test:other")
    assert BackgroundJobService.get(db_session, other)["done"] is False


def test_create_job_allows_new_job_after_previous_done(db_session, session_factory):
    first = job_runner.create_job(db_session, "test:again")
    job_runner.run_job(first, lambda _s, _cb: None)
    db_session.expire_all()

    second = job_runner.create_job(db_session, "test:again")

    assert second != first
    assert _load(session_factory, second)["done"] is False


def test_create_job_uses_given_job_id(db_session):
    assert job_runner.create_job(db_session, "test:given", job_id="42") == "42"
    assert BackgroundJobService.get(db_session, "42")["job_type"] == "test:given"


# ── submit_job ──────────────────────────────────────────────────────────


def test_submit_job_runs_in_background_thread(db_session, session_factory):
    job_id = job_runner.create_job(db_session, "test:thread")

    thread = job_runner.submit_job(job_id, lambda _s, _cb: {"ok": True})
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert thread.daemon is True
    state = _load(session_factory, job_id)
    assert state["done"] is True
    assert state["summary"] == {"ok": True}


# ── job_event_stream ────────────────────────────────────────────────────


def test_job_event_stream_unknown_job(session_factory, no_sleep):
    frames = _collect(job_runner.job_event_stream("no-such-job"))

    assert frames == [{"error": "not found"}]


def test_job_event_stream_done_job_emits_then_stops(db_session, session_factory, no_sleep):
    job_id = job_runner.create_job(db_session, "test:stream")
    job_runner.run_job(job_id, lambda _s, _cb: {"n": 1})

    frames = _collect(job_runner.job_event_stream(job_id))

    assert len(frames) == 2
    assert all(frame["done"] is True for frame in frames)
    assert frames[0]["summary"] == {"n": 1}


def test_job_event_stream_applies_transform(db_session, session_factory, no_sleep):
    job_id = job_runner.create_job(db_session, "ns:scan")
    job_runner.run_job(job_id, lambda _s, _cb: None)

    def transform(state: dict) -> dict:
        result = dict(state)
        result["job_type"] = result["job_type"].split(":", 1)[1]
        return result

    frames = _collect(job_runner.job_event_stream(job_id, transform=transform))

    assert frames
    assert all(frame["job_type"] == "scan" for frame in frames)


def test_job_event_stream_row_deleted_midway(db_session, session_factory, monkeypatch):
    job_id = job_runner.create_job(db_session, "test:deleted")

    async def delete_on_sleep(_seconds, *_args, **_kwargs):
        with session_factory() as session:
            session.execute(delete(BackgroundJob).where(BackgroundJob.job_id == job_id))
            session.commit()

    monkeypatch.setattr(job_runner.asyncio, "sleep", delete_on_sleep)

    frames = _collect(job_runner.job_event_stream(job_id))

    assert len(frames) == 2
    assert frames[0]["job_id"] == job_id
    assert frames[0]["done"] is False
    assert frames[1] == {"error": "not found"}
