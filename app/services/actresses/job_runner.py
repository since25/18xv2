"""女优功能的后台任务：刷新档案与待删清单、执行删除批次。

任务的判重、进度和成败收尾都由统一启动器 app/services/job_runner.py 负责，这里只写具体干什么。
本模块可以从 Jellyfin 任务模块导入开关函数；反过来 Jellyfin 任务模块只在函数内部导入本模块，避免循环导入。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
import logging

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.actresses import ActressDeleteBatch
from app.services.actresses.archive_service import ArchiveService
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses.delete_batch_service import BatchSummary, DeleteBatchService
from app.services.actresses.delete_guard import FilmDeleteGuard, PathMapper, parse_path_map
from app.services.client_115.client import Fake115Client, Real115Client
from app.services.jellyfin.client import JellyfinClient
from app.services.jellyfin.job_runner import jellyfin_scan_enabled, jellyfin_sync_enabled
from app.services.job_runner import JobWork, ProgressCallback


logger = logging.getLogger(__name__)

JOB_REFRESH = "actress:refresh"
JOB_DELETE = "actress:delete"


def actress_enabled(settings: Settings) -> bool:
    """女优功能是否开启：总开关打开，且 Jellyfin 扫描开启（演员名来自扫描结果）。"""
    return bool(getattr(settings, "actress_enabled", False) and jellyfin_scan_enabled(settings))


def actress_delete_ready(settings: Settings) -> bool:
    """删片是否就绪：女优功能开启，且 porn_tv1、302porn_tv1 两个可写根目录都已配置。"""
    return bool(
        actress_enabled(settings)
        and getattr(settings, "actress_source_root", None)
        and getattr(settings, "actress_organized_root", None)
    )


def _strm_roots(settings: Settings) -> list[str]:
    return list(getattr(settings, "media_library_strm_roots", []) or [])


def refresh_work(db: Session, progress: ProgressCallback) -> dict:
    """刷新女优档案（新名字建档、重算片数），再按删片规则重算待删清单。

    根目录没配置时由档案服务抛 ActressError，不改任何数据。
    """
    progress("刷新女优档案", 0, 0)
    strm_roots = _strm_roots(get_settings())
    archive = ArchiveService().refresh(db, strm_roots=strm_roots)
    progress("重算待删清单", 0, 0)
    added, removed = CandidateService().reconcile(db, strm_roots=strm_roots, added_by="daily")
    progress("完成", 1, 1)
    return {
        "created": archive["created"],
        "actresses": archive["actresses"],
        "candidates_added": added,
        "candidates_removed": removed,
    }


def delete_work(batch_id: int, client_115: Real115Client | Fake115Client) -> JobWork:
    """返回执行（或续跑）一个删除批次的干活函数。

    删除中途出了意外（不是某部片失败，而是整个执行被打断）时把批次标为中断，
    再把异常抛给统一启动器记任务失败；之后可以续跑。
    删掉了片子时让 Jellyfin 扫一遍 115 番号库，扫库失败不影响批次结果。
    """

    def work(db: Session, progress: ProgressCallback) -> dict:
        settings = get_settings()
        strm_roots = _strm_roots(settings)
        try:
            guard = FilmDeleteGuard(settings.actress_source_root, settings.actress_organized_root)
            mapper = PathMapper(parse_path_map(settings.actress_path_map))
            summary = DeleteBatchService().run(
                db,
                batch_id,
                client_115=client_115,
                guard=guard,
                mapper=mapper,
                strm_roots=strm_roots,
                progress=progress,
            )
        except Exception as exc:
            _mark_interrupted(db, batch_id, exc)
            raise
        _refresh_jellyfin(db, batch_id, summary, settings, strm_roots)
        progress("完成", 1, 1)
        return dataclasses.asdict(summary)

    return work


def _mark_interrupted(db: Session, batch_id: int, exc: Exception) -> None:
    """先回滚没提交的半截改动，再把批次标为中断；标记本身出错只记日志，原异常照常向外抛。"""
    try:
        db.rollback()
        batch = db.get(ActressDeleteBatch, batch_id)
        if batch is not None:
            batch.status = "interrupted"
            batch.note = f"删除中断：{exc}"
            batch.finished_at = datetime.now(UTC)
            db.commit()
    except Exception:  # noqa: BLE001 - 原异常要交给统一启动器记失败
        logger.exception("删除批次 %s 标记中断失败", batch_id)


def _refresh_jellyfin(
    db: Session, batch_id: int, summary: BatchSummary, settings: Settings, strm_roots: list[str]
) -> None:
    """删掉了片子且 Jellyfin 同步可用时，触发 115 番号库的普通扫描，结果记在批次的 jellyfin_refresh 上。

    done：已触发；error：找不到库或任何异常（不改批次状态）；skipped：没删片子或 Jellyfin 未配置。
    """
    if summary.deleted > 0 and jellyfin_sync_enabled(settings):
        try:
            with JellyfinClient(
                settings.jellyfin_base_url,
                settings.jellyfin_api_key,
                settings.jellyfin_timeout_seconds,
                settings.jellyfin_page_size,
            ) as client:
                library_id = client.find_library_id(strm_roots)
                if library_id is None:
                    logger.warning("删除批次 %s 之后扫库：Jellyfin 里找不到位置为 %s 的媒体库", batch_id, strm_roots)
                    result = "error"
                else:
                    client.refresh_library(library_id)
                    result = "done"
        except Exception:  # noqa: BLE001 - 扫库失败不能影响删除批次的结果
            logger.warning("删除批次 %s 之后触发 Jellyfin 扫库失败", batch_id, exc_info=True)
            result = "error"
    else:
        result = "skipped"
    batch = db.get(ActressDeleteBatch, batch_id)
    batch.jellyfin_refresh = result
    db.commit()
