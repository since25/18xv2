from __future__ import annotations

import asyncio
from datetime import date, datetime
import logging

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services.jellyfin.client import JellyfinClient
from app.services.jellyfin.collection_sync_service import CollectionSyncService
from app.services.jellyfin.cover_service import CoverService
from app.services.jellyfin.display_name_sync_service import DisplayNameSyncService
from app.services.jellyfin.scan_service import MediaScanService
# JobAlreadyRunning 从统一启动器重新导出，保证路由和每日循环捕获的是同一个类
from app.services.job_runner import JobAlreadyRunning, JobWork, create_job, run_job  # noqa: F401


logger = logging.getLogger(__name__)

JOB_SCAN = "jellyfin:scan"
JOB_SYNC = "jellyfin:sync"
JOB_COVERS = "jellyfin:covers"
JOB_NAMES = "jellyfin:names"


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


def jellyfin_display_names_enabled(settings: Settings) -> bool:
    """返回每日显示名同步是否开启（需同步可用且开关打开）。"""
    return bool(jellyfin_sync_enabled(settings) and getattr(settings, "jellyfin_display_names_enabled", False))


def jellyfin_cover_enabled(settings: Settings) -> bool:
    """返回本地视频封面任务是否开启。"""
    return bool(getattr(settings, "jellyfin_cover_since", None))


def start_job(db, job_type: str) -> str:
    """检查同类型运行任务后创建一个新的后台任务（判重由统一启动器负责）。"""
    return create_job(db, job_type)


def scan_work(job_id: str) -> JobWork:
    """返回扫描任务的干活函数；扫描服务需要任务编号标记本轮见到的条目。"""

    def work(db, progress):
        progress("扫描中", 0, 0)
        settings = get_settings()
        summary = MediaScanService().scan(
            db,
            local_roots=list(getattr(settings, "media_library_local_roots", []) or []),
            strm_roots=list(getattr(settings, "media_library_strm_roots", []) or []),
            job_id=job_id,
        )
        progress("完成", 1, 1)
        return summary

    return work


def sync_work(db, progress) -> dict:
    """合集同步任务的干活函数；女优功能开启时，关键词合集之后再同步白名单女优合集。"""
    # 函数内导入：女优任务模块会从本模块导入开关函数，顶层导入会循环
    from app.services.actresses.collection_sync import ActressCollectionSyncService
    from app.services.actresses.job_runner import actress_enabled

    progress("同步中", 0, 0)
    settings = get_settings()
    if not jellyfin_sync_enabled(settings):
        raise RuntimeError("Jellyfin 同步未启用或缺少地址/API Key")
    client = JellyfinClient(
        settings.jellyfin_base_url,
        settings.jellyfin_api_key,
        settings.jellyfin_timeout_seconds,
        settings.jellyfin_page_size,
    )
    # with 块保证成功或失败都会关闭客户端
    with client:
        summary = CollectionSyncService().sync(db, client)
        # 女优合集的成员取关键词同步写入的 Jellyfin 条目 ID，必须排在它之后
        if actress_enabled(settings):
            actress_summary = ActressCollectionSyncService().sync(
                db,
                client,
                strm_roots=list(getattr(settings, "media_library_strm_roots", []) or []),
            )
            summary.update({f"actress_{key}": value for key, value in actress_summary.items()})
    progress("完成", 1, 1)
    return summary


def names_work(*, dry_run: bool = False, keyword: str | None = None, restore: bool = False) -> JobWork:
    """返回显示名同步任务的干活函数；只预览、单关键词、回滚三种选项透传给服务。"""

    def work(db, progress):
        progress("改名中", 0, 0)
        settings = get_settings()
        if not jellyfin_sync_enabled(settings):
            raise RuntimeError("Jellyfin 同步未启用或缺少地址/API Key")
        # 显示名用自己的每页条数和超时，不影响合集同步的 JELLYFIN_PAGE_SIZE
        client = JellyfinClient(
            settings.jellyfin_base_url,
            settings.jellyfin_api_key,
            settings.jellyfin_display_names_timeout_seconds,
            settings.jellyfin_display_names_page_size,
        )
        with client:
            summary = DisplayNameSyncService().sync(
                db,
                client,
                local_roots=list(getattr(settings, "media_library_local_roots", []) or []),
                dry_run=dry_run,
                keyword=keyword,
                restore=restore,
                progress=progress,
            )
        progress("完成", 1, 1)
        return summary

    return work


def cover_work(db, progress) -> dict:
    """本地视频封面任务的干活函数。"""
    progress("生成封面中", 0, 0)
    settings = get_settings()
    if not jellyfin_cover_enabled(settings):
        raise RuntimeError("Jellyfin 封面任务未启用或缺少上线时间")
    summary = CoverService().run(
        db,
        local_roots=list(getattr(settings, "media_library_local_roots", []) or []),
        since=settings.jellyfin_cover_since,
        deadline_minute=int(getattr(settings, "jellyfin_cover_deadline_minute", 25)),
    )
    progress("完成", 1, 1)
    return summary


def run_scan_job(job_id: str) -> None:
    """在独立数据库会话中运行一次扫描并记录结果。"""
    run_job(job_id, scan_work(job_id))


def run_sync_job(job_id: str) -> None:
    """在独立数据库会话中运行一次合集同步并记录结果。"""
    run_job(job_id, sync_work)


def run_names_job(job_id: str, *, dry_run: bool = False, keyword: str | None = None, restore: bool = False) -> None:
    """在独立数据库会话中运行一次显示名同步并记录结果。"""
    run_job(job_id, names_work(dry_run=dry_run, keyword=keyword, restore=restore))


def run_cover_job(job_id: str) -> None:
    """在独立数据库会话中生成本地视频封面并记录结果。"""
    run_job(job_id, cover_work)


async def jellyfin_daily_loop(settings: Settings) -> None:
    """按本地时间每天运行一次扫描，女优功能开启时接着刷新女优档案和待删清单，再在可用时运行合集同步。"""
    # 函数内导入：女优任务模块会从本模块导入开关函数，顶层导入会循环
    from app.services.actresses import job_runner as actress_jobs

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

                # 扫描之后、合集同步之前：用本次扫描的演员名单刷新档案和待删清单（总开关默认关闭）
                # 这一步失败只记在它自己的任务上，不影响后面的合集同步
                if actress_jobs.actress_enabled(settings):
                    refresh_job_id = None
                    with SessionLocal() as db:
                        try:
                            refresh_job_id = start_job(db, actress_jobs.JOB_REFRESH)
                        except JobAlreadyRunning:
                            logger.info("女优档案刷新已在运行，跳过本次创建")
                    if refresh_job_id is not None:
                        await asyncio.to_thread(run_job, refresh_job_id, actress_jobs.refresh_work)

                # 女优刷新之后补头像（头像开关默认关闭）；失败只记在自己的任务上
                if actress_jobs.actress_avatars_enabled(settings):
                    avatars_job_id = None
                    with SessionLocal() as db:
                        try:
                            avatars_job_id = start_job(db, actress_jobs.JOB_AVATARS)
                        except JobAlreadyRunning:
                            logger.info("女优头像任务已在运行，跳过本次创建")
                    if avatars_job_id is not None:
                        await asyncio.to_thread(run_job, avatars_job_id, actress_jobs.avatars_work())

                if jellyfin_sync_enabled(settings):
                    sync_job_id = None
                    with SessionLocal() as db:
                        try:
                            sync_job_id = start_job(db, JOB_SYNC)
                        except JobAlreadyRunning:
                            logger.info("Jellyfin 每日同步已在运行，跳过本次创建")
                    if sync_job_id is not None:
                        await asyncio.to_thread(run_sync_job, sync_job_id)

                # 合集同步之后维护本地视频显示名（开关默认关闭）
                if jellyfin_display_names_enabled(settings):
                    names_job_id = None
                    with SessionLocal() as db:
                        try:
                            names_job_id = start_job(db, JOB_NAMES)
                        except JobAlreadyRunning:
                            logger.info("Jellyfin 每日显示名同步已在运行，跳过本次创建")
                    if names_job_id is not None:
                        await asyncio.to_thread(run_names_job, names_job_id)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 定时循环不能因一次任务异常退出
            logger.exception("Jellyfin 每日任务循环异常")
            await asyncio.sleep(60)


async def jellyfin_cover_daily_loop(settings: Settings) -> None:
    """按本地时间每天独立运行一次封面生成任务。"""
    run_hour = int(getattr(settings, "jellyfin_cover_run_hour", -1))
    if run_hour == -1 or not jellyfin_cover_enabled(settings):
        return

    last_run: date | None = None
    while True:
        try:
            now = datetime.now().astimezone()
            if now.hour == run_hour and last_run != now.date():
                last_run = now.date()
                cover_job_id = None
                with SessionLocal() as db:
                    try:
                        cover_job_id = start_job(db, JOB_COVERS)
                    except JobAlreadyRunning:
                        logger.info("Jellyfin 每日封面任务已在运行，跳过本次创建")
                if cover_job_id is not None:
                    await asyncio.to_thread(run_cover_job, cover_job_id)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 定时循环不能因一次任务异常退出
            logger.exception("Jellyfin 每日封面循环异常")
            await asyncio.sleep(60)
