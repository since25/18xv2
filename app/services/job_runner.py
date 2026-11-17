"""后台长任务统一启动器。

所有后台长任务（目录导入、白名单批处理、文件去重、Jellyfin）都走这里：
判重 → 建 background_jobs 记录 → 独立会话执行“干活函数” → 写进度 → 成败统一收尾 →
SSE 推送进度 → 过期清理。任务进度只认数据库 background_jobs 表一份。

新增一个长任务的做法：
1. 路由里 ``job_id = create_job(db, "<命名空间>:<类型>")``，捕获 ``JobAlreadyRunning`` 转成 409；
2. ``submit_job(job_id, work)``，``work(session, progress_cb)`` 只写具体干什么，返回摘要；
3. 进度接口返回 ``StreamingResponse(job_event_stream(job_id), media_type="text/event-stream")``。

注意：SessionLocal 必须在运行时从 app.db.session 取，不能在模块顶层绑定（测试会替换它）。
前提是单进程运行（生产 uvicorn --workers 1），判重靠进程内锁 + 查库同类型未完成任务。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import dataclasses
from datetime import UTC, datetime
import json
import logging
import threading
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.services.background_job_service import BackgroundJobService


logger = logging.getLogger(__name__)

# (stage, current, total)
ProgressCallback = Callable[[str, int, int], None]
# 干活函数：拿到独立会话和进度回调，返回摘要（dict / pydantic 模型 / dataclass / None）
JobWork = Callable[[Session, ProgressCallback], Any]

# 进程内锁：保证“查库判重 + 建记录”之间不会被另一个请求插入
_create_lock = threading.Lock()


class JobAlreadyRunning(Exception):
    """同类型后台任务已经在运行。"""


def create_job(db: Session, job_type: str, *, job_id: str | None = None) -> str:
    """同类型没有未完成任务时建一条任务记录并返回编号，否则抛 JobAlreadyRunning。"""
    with _create_lock:
        if BackgroundJobService.list_active(db, job_type):
            raise JobAlreadyRunning(job_type)
        new_id = job_id or str(uuid.uuid4())
        BackgroundJobService.create(db, new_id, job_type)
        return new_id


def _normalize_summary(result: Any) -> Any:
    """把干活函数的返回值转成可写入 JSON 的摘要；转不了时返回 None。"""
    if result is None:
        return None
    try:
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif dataclasses.is_dataclass(result) and not isinstance(result, type):
            data = dataclasses.asdict(result)
        else:
            data = result
        json.dumps(data, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - 摘要异常不影响任务按成功收尾
        logger.warning("后台任务摘要无法序列化，按空摘要记录", exc_info=True)
        return None
    return data


def _mark_failure(session: Session, job_id: str, exc: BaseException) -> None:
    """先回滚失败的会话，再把任务记为失败；收尾本身出错只记日志。"""
    try:
        session.rollback()
        BackgroundJobService.update(
            session,
            job_id,
            stage="失败",
            error=str(exc),
            done=True,
            finished_at=datetime.now(UTC),
        )
    except Exception:  # noqa: BLE001 - 后台线程不能抛出
        logger.exception("后台任务 %s 写失败记录出错", job_id)


def run_job(job_id: str, work: JobWork) -> None:
    """在当前线程同步执行一个已建好的任务，成败都收尾，任何情况下不向外抛异常。"""
    try:
        from app.db.session import SessionLocal

        session = SessionLocal()
    except Exception:  # noqa: BLE001 - 后台线程不能抛出
        logger.exception("后台任务 %s 无法打开数据库会话", job_id)
        return

    try:
        def progress(stage: str, current: int, total: int) -> None:
            BackgroundJobService.update(session, job_id, stage=stage, current=current, total=total)

        try:
            result = work(session, progress)
        except Exception as exc:  # noqa: BLE001 - 失败写入任务，不让后台线程抛出
            logger.exception("后台任务 %s 失败", job_id)
            _mark_failure(session, job_id, exc)
            return

        try:
            BackgroundJobService.update(
                session,
                job_id,
                stage="完成",
                done=True,
                error=None,
                summary=_normalize_summary(result),
                finished_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001 - 成功收尾失败时退回失败记录，不留“运行中”
            logger.exception("后台任务 %s 写完成记录出错", job_id)
            _mark_failure(session, job_id, exc)
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            logger.exception("后台任务 %s 关闭数据库会话出错", job_id)


def submit_job(job_id: str, work: JobWork) -> threading.Thread:
    """起一个守护线程执行 run_job，返回该线程（测试可 join 等待）。"""
    thread = threading.Thread(
        target=run_job,
        args=(job_id, work),
        name=f"background-job-{job_id}",
        daemon=True,
    )
    thread.start()
    return thread


async def job_event_stream(
    job_id: str,
    *,
    transform: Callable[[dict], dict] | None = None,
) -> AsyncIterator[str]:
    """SSE 推送：每秒读库推一帧；done 后再推一帧后断开；记录不存在时推 not found 后结束。

    不需要独立 keepalive — 每秒必发 data 已经穿透 nginx 等代理的 idle timeout。
    记录由清理循环在保留期后删除，推送中途被删同样按 not found 结束。
    """
    sent_done_once = False
    while True:
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            state = BackgroundJobService.get(session, job_id)
        if state is None:
            yield f"data: {json.dumps({'error': 'not found'})}\n\n"
            return
        frame = transform(state) if transform is not None else state
        yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
        if state["done"]:
            if sent_done_once:
                return
            sent_done_once = True
        await asyncio.sleep(1)


async def sweep_expired_jobs(*, interval_seconds: int = 60, retention_seconds: int = 600) -> None:
    """每 interval_seconds 清理一次完成超过 retention_seconds 的任务记录。"""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            from app.db.session import SessionLocal

            with SessionLocal() as session:
                removed = BackgroundJobService.purge_expired(session, retention_seconds)
            if removed:
                logger.info("后台任务清理：回收 %d 条已完成记录", removed)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - 一次清理失败不能让循环退出
            logger.exception("后台任务清理循环出错")
