"""按显示名规则维护 Jellyfin 本地视频的名字，并让 18x 合集按名字排序。

设计见 docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md。
只改 Jellyfin 数据库里的名字和锁定字段，不写媒体目录，不调用任何刷新接口。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.jellyfin.display_names import DisplayName, compute_display_names
from app.services.keywords.registry_service import normalize_keyword_text


PROGRESS_EVERY = 500
# Jellyfin 挂掉时每条都要重试十几秒到一分钟，连续失败这么多条就停，避免一轮拖上几天
MAX_CONSECUTIVE_FAILURES = 20


class UnknownKeyword(ValueError):
    """按关键词试跑时找不到对应的白名单关键词。"""


class DisplayNameSyncAborted(RuntimeError):
    """连续写入失败太多，判断 Jellyfin 不可用，停止本轮。"""


class DisplayNameSyncService:
    """比对应有名字和 Jellyfin 当前名字，只写回不一致或没锁定的条目。"""

    def sync(
        self,
        db: Session,
        client: Any,
        *,
        local_roots: Sequence[str],
        dry_run: bool = False,
        keyword: str | None = None,
        restore: bool = False,
        sample_size: int = 20,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "dry_run": dry_run,
            "restore": restore,
            "to_update": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "not_in_jellyfin": 0,
            "skipped": 0,
            "collections_ordered": 0,
            "samples": [],
        }
        # 配置或关键词有误时在访问 Jellyfin 之前就报错，不让任务显示"完成"
        if not [root for root in local_roots if root and root.rstrip("/")]:
            raise ValueError("未配置本地根目录（MEDIA_LIBRARY_LOCAL_ROOTS）")
        keyword_entry_id = self._resolve_keyword(db, keyword) if keyword else None

        media_items = db.scalars(
            select(JellyfinMediaItem)
            .where(JellyfinMediaItem.source == "local", JellyfinMediaItem.active.is_(True))
            .order_by(JellyfinMediaItem.id)
            .options(selectinload(JellyfinMediaItem.keyword_links))
        ).all()
        # 拿不到完整列表时直接抛出：一条都不改，任务按失败收尾
        remote = {item["path"]: item for item in client.iter_media_items()}

        present = [item for item in media_items if item.path in remote]
        result["not_in_jellyfin"] = len(media_items) - len(present)
        # 编号按全部已入库的本地视频算，按关键词试跑时也不影响序号
        names = compute_display_names([item.path for item in present], local_roots)
        targets = present
        if keyword_entry_id is not None:
            targets = [
                item for item in present if any(link.keyword_entry_id == keyword_entry_id for link in item.keyword_links)
            ]

        total = len(targets)
        consecutive_failures = 0
        for index, item in enumerate(targets, start=1):
            outcome = self._sync_item(
                client, item.path, names.get(item.path), remote[item.path], result, dry_run, restore, sample_size
            )
            if outcome == "updated":
                consecutive_failures = 0
            elif outcome == "failed":
                consecutive_failures += 1
                self._abort_if_too_many(consecutive_failures, result)
            if progress is not None and index % PROGRESS_EVERY == 0:
                progress("改名中", index, total)

        if not dry_run and not restore:
            self._order_collections(db, client, keyword_entry_id, result)
        return result

    @staticmethod
    def _sync_item(
        client: Any,
        path: str,
        display_name: DisplayName | None,
        remote_item: dict[str, Any],
        result: dict[str, Any],
        dry_run: bool,
        restore: bool,
        sample_size: int,
    ) -> str:
        """处理一条，返回 skipped / unchanged / planned（只预览）/ updated / failed。"""
        if display_name is None:
            result["skipped"] += 1
            return "skipped"
        locked = remote_item.get("locked_fields")
        current = remote_item.get("name")
        current_sort = remote_item.get("sort_name")
        if restore:
            # 回滚：名字改回文件名（去掉扩展名）、清掉强制排序名并解锁
            desired = PurePosixPath(path).stem
            desired_sort = None
            needs_write = (
                current != desired or current_sort is not None or (locked is not None and "Name" in locked)
            )
        else:
            desired = display_name.name
            desired_sort = display_name.sort_name
            # 名字对但锁被去掉、或排序名不对时也要写：前者重扫会改回文件名，后者合集里各包会交错
            needs_write = (
                current != desired
                or current_sort != desired_sort
                or (locked is not None and "Name" not in locked)
            )
        if not needs_write:
            result["unchanged"] += 1
            return "unchanged"

        result["to_update"] += 1
        if len(result["samples"]) < sample_size:
            result["samples"].append({"path": path, "old": current, "new": desired})
        if dry_run:
            return "planned"
        try:
            client.set_item_name(remote_item["id"], desired, sort_name=desired_sort, lock=not restore)
        except Exception:  # noqa: BLE001 - 单条失败只计数，连续失败由调用方判断是否停止
            result["failed"] += 1
            return "failed"
        result["updated"] += 1
        return "updated"

    @staticmethod
    def _abort_if_too_many(consecutive_failures: int, result: dict[str, Any]) -> None:
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise DisplayNameSyncAborted(
                f"连续 {consecutive_failures} 次写入 Jellyfin 失败，已停止本轮"
                f"（已改名 {result['updated']} 条，合集排序 {result['collections_ordered']} 个，"
                f"失败 {result['failed']} 次），请检查 Jellyfin 是否正常"
            )

    def _order_collections(self, db: Session, client: Any, keyword_entry_id: int | None, result: dict[str, Any]) -> None:
        query = select(JellyfinKeywordCollection).where(
            JellyfinKeywordCollection.status == "active",
            JellyfinKeywordCollection.jellyfin_collection_id.is_not(None),
        )
        if keyword_entry_id is not None:
            query = query.where(JellyfinKeywordCollection.keyword_entry_id == keyword_entry_id)
        consecutive_failures = 0
        for mapping in db.scalars(query.order_by(JellyfinKeywordCollection.id)).all():
            try:
                changed = client.ensure_sort_name_order(mapping.jellyfin_collection_id)
            except Exception:  # noqa: BLE001 - 单个合集失败只计数，连续失败就停
                result["failed"] += 1
                consecutive_failures += 1
                self._abort_if_too_many(consecutive_failures, result)
                continue
            consecutive_failures = 0
            if changed:
                result["collections_ordered"] += 1

    @staticmethod
    def _resolve_keyword(db: Session, keyword: str) -> int:
        """按规范名或别名找白名单关键词，返回其 ID。"""
        normalized = normalize_keyword_text(keyword)
        entry = db.scalars(
            select(KeywordEntry).where(
                KeywordEntry.canonical_name_normalized == normalized,
                KeywordEntry.keyword_type == "whitelist",
            )
        ).first()
        if entry is not None:
            return entry.id
        alias = db.scalars(
            select(KeywordAlias)
            .join(KeywordEntry, KeywordAlias.keyword_entry_id == KeywordEntry.id)
            .where(KeywordAlias.alias_normalized == normalized, KeywordEntry.keyword_type == "whitelist")
        ).first()
        if alias is None:
            raise UnknownKeyword(f"关键词不存在：{keyword}")
        return alias.keyword_entry_id
