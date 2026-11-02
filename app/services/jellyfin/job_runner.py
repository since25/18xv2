from __future__ import annotations

import asyncio
from datetime import date, datetime
import logging
import threading
import uuid

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin.client import JellyfinClient
from app.services.jellyfin.collection_sync_service import CollectionSyncService
from app.services.jellyfin.scan_service import MediaScanService


logger = logging.getLogger(__name__)

JOB_SCAN = "jellyfin:scan"
JOB_SYNC = "jellyfin:sync"

_job_start_lock = threading.Lock()


class JobAlreadyRunning(Exception):
    """同类型 Jellyfin 任务已经在运行。"""


def jellyfin_scan_enabled(settings: Settings) -> bool:
    """返回扫描功能是否开启。"""
    return bool(getattr(settings, "jellyfin_enabled", False))


def jellyfin_sync_enabled(settings: Settings) -> bool:
    """返回同步功能是否开启且具备 Jellyfin 连接配置。"""
    return bool(
        jellyfin_scan_enabled(settings)
        and getattr(settings, "jellyfin_base_url", None)
        and getattr(settings, "jellyfin_api_key", None)
    )


def start_job(db, job_type: str) -> str:
    """检查同类型运行任务后创建一个新的后台任务。"""
    with _job_start_lock:
        if BackgroundJobService.list_active(db, job_type):
            raise JobAlreadyRunning(job_type)
        job_id = str(uuid.uuid4())
        BackgroundJobService.create(db, job_id, job_type)
        return job_id


def _mark_success(db, job_id: str, summary: dict) -> None:
    BackgroundJobService.update(
        db,
        job_id,
        stage="完成",
        current=1,
        total=1,
        done=True,
        error=None,
        summary=summary,
        finished_at=datetime.now().astimezone(),
    )


def _mark_failure(db, job_id: str, error: Exception) -> None:
    BackgroundJobService.update(
        db,
        job_id,
        stage="失败",
        done=True,
        error=str(error),
        finished_at=datetime.now().astimezone(),
    )


def run_scan_job(job_id: str) -> None:
    """在独立数据库会话中运行一次扫描并记录结果。"""
    with SessionLocal() as db:
        BackgroundJobService.update(db, job_id, stage="扫描中")
        try:
            settings = get_settings()
            summary = MediaScanService().scan(
                db,
                local_roots=list(getattr(settings, "media_library_local_roots", []) or []),
                strm_roots=list(getattr(settings, "media_library_strm_roots", []) or []),
                job_id=job_id,
            )
            _mark_success(db, job_id, summary)
        except Exception as exc:  # noqa: BLE001 - 失败写入任务，不让后台线程抛出
            db.rollback()
            _mark_failure(db, job_id, exc)
            logger.exception("Jellyfin 扫描任务失败: %s", job_id)


def run_sync_job(job_id: str) -> None:
    """在独立数据库会话中运行一次合集同步并记录结果。"""
    with SessionLocal() as db:
        BackgroundJobService.update(db, job_id, stage="同步中")
        client = None
        try:
            settings = get_settings()
            if not jellyfin_sync_enabled(settings):
                raise RuntimeError("Jellyfin 同步未启用或缺少地址/API Key")
            client = JellyfinClient(
                settings.jellyfin_base_url,
                settings.jellyfin_api_key,
                settings.jellyfin_timeout_seconds,
                settings.jellyfin_page_size,
            )
            with client:
                summary = CollectionSyncService().sync(db, client)
            _mark_success(db, job_id, summary)
        except Exception as exc:  # noqa: BLE001 - 失败写入任务，不让后台线程抛出
            db.rollback()
            if client is not None:
                client.close()
            _mark_failure(db, job_id, exc)
            logger.exception("Jellyfin 同步任务失败: %s", job_id)


async def jellyfin_daily_loop(settings: Settings) -> None:
    """按本地时间每天运行一次扫描，并在可用时运行合集同步。"""
    run_hour = int(getattr(settings, "jellyfin_daily_run_hour", -1))
    if run_hour == -1 or not jellyfin_sync_enabled(settings):
        return

    last_run: date | None = None
    while True:
        try:
            now = datetime.now().astimezone()
            if now.hour == run_hour and last_run != now.date():
                last_run = now.date()
                scan_job_id = None
                with SessionLocal() as db:
                    try:
                        scan_job_id = start_job(db, JOB_SCAN)
                    except JobAlreadyRunning:
                        logger.info("Jellyfin 每日扫描已在运行，跳过本次创建")
                if scan_job_id is not None:
                    await asyncio.to_thread(run_scan_job, scan_job_id)

                if jellyfin_sync_enabled(settings):
                    sync_job_id = None
                    with SessionLocal() as db:
                        try:
                            sync_job_id = start_job(db, JOB_SYNC)
                        except JobAlreadyRunning:
                            logger.info("Jellyfin 每日同步已在运行，跳过本次创建")
                    if sync_job_id is not None:
                        await asyncio.to_thread(run_sync_job, sync_job_id)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 定时循环不能因一次任务异常退出
            logger.exception("Jellyfin 每日任务循环异常")
            await asyncio.sleep(60)
