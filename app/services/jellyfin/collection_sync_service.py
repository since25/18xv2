from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem
from app.models.keywords import KeywordEntry
from app.services.jellyfin.client import JellyfinClient, JellyfinError


MANAGED_TAG = "18x-managed"


class CollectionSyncService:
    """按当前扫描结果维护带有 18x 标签的 Jellyfin 合集。"""

    def sync(self, db: Session, client: JellyfinClient) -> dict[str, int]:
        result = {
            "collections_created": 0,
            "collections_renamed": 0,
            "collections_deleted": 0,
            "items_added": 0,
            "items_removed": 0,
            "pending_items": 0,
            "conflicts": 0,
            "errors": 0,
        }

        media_items = db.scalars(
            select(JellyfinMediaItem)
            .where(JellyfinMediaItem.active.is_(True))
            .options(selectinload(JellyfinMediaItem.keyword_links))
        ).all()
        try:
            path_to_item_id = dict(client.iter_media_paths())
        except JellyfinError:
            # 拿不到影片列表（比如扫描中）时停止，避免按过期信息增删合集
            result["pending_items"] = sum(1 for item in media_items if item.resolve_state != "resolved")
            result["errors"] = 1
            return result

        for item in media_items:
            item_id = path_to_item_id.get(item.path)
            item.jellyfin_item_id = item_id
            item.resolve_state = "resolved" if item_id else "pending"
        result["pending_items"] = sum(1 for item in media_items if item.resolve_state != "resolved")

        try:
            remote_collections = client.list_collections()
        except JellyfinError:
            result["errors"] = 1
            db.commit()
            return result

        remote_by_id = {
            str(collection.get("id")): collection
            for collection in remote_collections
            if collection.get("id") is not None
        }
        active_entries = db.scalars(
            select(KeywordEntry).where(
                KeywordEntry.keyword_type == "whitelist",
                KeywordEntry.status == "active",
            )
        ).all()
        active_entry_by_id = {entry.id: entry for entry in active_entries}

        expected_ids: dict[int, set[str]] = {}
        for item in media_items:
            for link in item.keyword_links:
                if link.keyword_entry_id not in active_entry_by_id:
                    continue
                expected_ids.setdefault(link.keyword_entry_id, set())
                if item.resolve_state == "resolved" and item.jellyfin_item_id:
                    expected_ids[link.keyword_entry_id].add(item.jellyfin_item_id)

        mappings = db.scalars(select(JellyfinKeywordCollection)).all()
        mapping_by_keyword: dict[int, JellyfinKeywordCollection] = {}
        for mapping in mappings:
            if mapping.keyword_entry_id is not None and mapping.keyword_entry_id not in mapping_by_keyword:
                mapping_by_keyword[mapping.keyword_entry_id] = mapping

        now = datetime.now(timezone.utc)
        for entry in active_entries:
            if entry.id not in expected_ids:
                continue
            mapping = mapping_by_keyword.get(entry.id)
            try:
                if mapping is not None and mapping.status == "conflict":
                    conflicted_remote = (
                        remote_by_id.get(mapping.jellyfin_collection_id)
                        if mapping.jellyfin_collection_id
                        else self._find_unmanaged_same_name(remote_collections, entry.canonical_name)
                    )
                    if conflicted_remote is not None and not (
                        mapping.jellyfin_collection_id and self._is_managed(conflicted_remote)
                    ):
                        result["conflicts"] += 1
                        continue

                expected = expected_ids[entry.id]
                if mapping is not None and mapping.jellyfin_collection_id:
                    collection_id = mapping.jellyfin_collection_id
                    remote = remote_by_id.get(collection_id)
                    if remote is not None:
                        if mapping.status == "untagged":
                            # 上次建好合集但打标签失败，这里补上
                            client.set_name_and_tags(collection_id, entry.canonical_name, [MANAGED_TAG])
                            remote = {**remote, "name": entry.canonical_name, "tags": [MANAGED_TAG]}
                        if not self._is_managed(remote):
                            mapping.status = "conflict"
                            mapping.last_sync_at = now
                            result["conflicts"] += 1
                            continue
                        self._sync_existing_collection(
                            client,
                            collection_id,
                            remote,
                            expected,
                            entry.canonical_name,
                            result,
                        )
                        mapping.status = "active"
                        mapping.canonical_name_snapshot = entry.canonical_name
                        mapping.last_sync_at = now
                        mapping.last_error = None
                        continue

                unmanaged = self._find_unmanaged_same_name(remote_collections, entry.canonical_name)
                if unmanaged is not None:
                    if mapping is None:
                        mapping = JellyfinKeywordCollection(
                            keyword_entry_id=entry.id,
                            jellyfin_collection_id=None,
                            canonical_name_snapshot=entry.canonical_name,
                            status="conflict",
                            last_sync_at=now,
                        )
                        db.add(mapping)
                    else:
                        mapping.jellyfin_collection_id = None
                        mapping.canonical_name_snapshot = entry.canonical_name
                        mapping.status = "conflict"
                        mapping.last_sync_at = now
                    result["conflicts"] += 1
                    continue

                if not expected:
                    # 影片还没入库时不建空合集，等下次同步
                    continue

                collection_id = client.create_collection(entry.canonical_name, sorted(expected))
                result["collections_created"] += 1
                result["items_added"] += len(expected)
                # 先记下合集，打标签失败时下次还能认出来
                if mapping is None:
                    mapping = JellyfinKeywordCollection(
                        keyword_entry_id=entry.id,
                        jellyfin_collection_id=collection_id,
                        canonical_name_snapshot=entry.canonical_name,
                        status="untagged",
                        last_sync_at=now,
                    )
                    db.add(mapping)
                    mapping_by_keyword[entry.id] = mapping
                else:
                    mapping.jellyfin_collection_id = collection_id
                    mapping.canonical_name_snapshot = entry.canonical_name
                    mapping.status = "untagged"
                    mapping.last_sync_at = now
                client.set_name_and_tags(collection_id, entry.canonical_name, [MANAGED_TAG])
                mapping.status = "active"
                mapping.last_error = None
            except Exception as exc:
                if mapping is not None:
                    mapping.last_error = str(exc)
                result["errors"] += 1

        active_association_ids = set(expected_ids)
        for mapping in mappings:
            if mapping.status == "retired":
                continue
            keyword_id = mapping.keyword_entry_id
            if keyword_id in active_association_ids and keyword_id in active_entry_by_id:
                continue
            try:
                collection_id = mapping.jellyfin_collection_id
                remote = remote_by_id.get(collection_id) if collection_id else None
                if remote is not None and self._is_managed(remote):
                    client.delete_item(collection_id)
                    result["collections_deleted"] += 1
                mapping.status = "retired"
                mapping.last_sync_at = now
                mapping.last_error = None
            except Exception as exc:
                mapping.last_error = str(exc)
                result["errors"] += 1

        db.commit()
        return result

    @staticmethod
    def _is_managed(collection: dict[str, Any]) -> bool:
        tags = collection.get("tags", [])
        return isinstance(tags, list) and MANAGED_TAG in tags

    @staticmethod
    def _find_unmanaged_same_name(collections: list[dict], name: str) -> dict | None:
        for collection in collections:
            if collection.get("name") == name and not CollectionSyncService._is_managed(collection):
                return collection
        return None

    @staticmethod
    def _sync_existing_collection(
        client: JellyfinClient,
        collection_id: str,
        remote: dict[str, Any],
        expected: set[str],
        canonical_name: str,
        result: dict[str, int],
    ) -> None:
        current = client.get_collection_item_ids(collection_id)
        to_add = sorted(expected - current)
        if to_add:
            client.add_to_collection(collection_id, to_add)
            result["items_added"] += len(to_add)
        to_remove = sorted(current - expected)
        if to_remove:
            client.remove_from_collection(collection_id, to_remove)
            result["items_removed"] += len(to_remove)
        if remote.get("name") != canonical_name:
            tags = remote.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            if MANAGED_TAG not in tags:
                tags = [*tags, MANAGED_TAG]
            client.set_name_and_tags(collection_id, canonical_name, [str(tag) for tag in tags])
            result["collections_renamed"] += 1
