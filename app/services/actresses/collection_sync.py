"""白名单女优的 Jellyfin 合集：每个白名单女优一个带 18x 标签的合集。

规则与关键词合集一致（增量增删、只动 18x 建的合集、单个合集失败不影响其他），
状态机沿用 `CollectionSyncService`：active / untagged / conflict / retired。
成员取 `JellyfinMediaItem.jellyfin_item_id`，由关键词合集同步写入，所以必须在它之后调用。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import Actress, JellyfinActressCollection
from app.models.jellyfin import JellyfinKeywordCollection
from app.services.actresses.archive_service import require_strm_roots
from app.services.actresses.films import load_films
from app.services.actresses.names import build_name_index, normalize_actress_name
from app.services.jellyfin.client import JellyfinClient, JellyfinError
from app.services.jellyfin.collection_sync_service import MANAGED_TAG, CollectionSyncService

_is_managed = CollectionSyncService._is_managed
_find_unmanaged_same_name = CollectionSyncService._find_unmanaged_same_name
_sync_existing_collection = CollectionSyncService._sync_existing_collection


class ActressCollectionSyncService:
    """按白名单女优维护 Jellyfin 合集。"""

    def sync(self, db: Session, client: JellyfinClient, *, strm_roots: list[str]) -> dict[str, int]:
        """同步全部白名单女优的合集，返回各项计数。

        根目录没配置时抛 ActressError：否则一部片都读不到，会把合集成员清空。
        """
        require_strm_roots(strm_roots, "同步女优合集")
        result = {
            "collections_created": 0,
            "collections_renamed": 0,
            "collections_deleted": 0,
            "items_added": 0,
            "items_removed": 0,
            "conflicts": 0,
            "errors": 0,
        }

        try:
            remote_collections = client.list_collections()
        except JellyfinError:
            result["errors"] = 1
            return result
        remote_by_id = {
            str(collection.get("id")): collection
            for collection in remote_collections
            if collection.get("id") is not None
        }

        whitelisted = db.scalars(select(Actress).where(Actress.status == "whitelist").order_by(Actress.id)).all()
        whitelist_ids = {actress.id for actress in whitelisted}
        # 每个白名单女优出演的、已在 Jellyfin 找到条目的片子
        expected_ids: dict[int, set[str]] = {actress.id: set() for actress in whitelisted}
        name_index = build_name_index(db)
        for film in load_films(db, strm_roots=strm_roots):
            for raw_name in film.actor_names:
                actress_id = name_index.get(normalize_actress_name(raw_name))
                if actress_id in expected_ids:
                    expected_ids[actress_id].update(film.jellyfin_item_ids)

        # 关键词合集正在用的名字，女优合集不能再用
        keyword_names = set(
            db.scalars(
                select(JellyfinKeywordCollection.canonical_name_snapshot).where(
                    JellyfinKeywordCollection.status == "active"
                )
            )
        )

        mappings = db.scalars(select(JellyfinActressCollection).order_by(JellyfinActressCollection.id)).all()
        mapping_by_actress: dict[int, JellyfinActressCollection] = {}
        for mapping in mappings:
            if mapping.actress_id is not None and mapping.actress_id not in mapping_by_actress:
                mapping_by_actress[mapping.actress_id] = mapping

        now = datetime.now(timezone.utc)
        for actress in whitelisted:
            name = actress.canonical_name
            expected = expected_ids[actress.id]
            mapping = mapping_by_actress.get(actress.id)
            if mapping is None and not expected:
                # 没有可放的片子、也没建过合集：不建空合集，也不必检查重名
                continue
            try:
                if name in keyword_names:
                    # 与关键词合集同名：两边都不改，只报告冲突
                    if mapping is None:
                        mapping = JellyfinActressCollection(
                            actress_id=actress.id,
                            jellyfin_collection_id=None,
                            canonical_name_snapshot=name,
                            status="conflict",
                            last_sync_at=now,
                        )
                        db.add(mapping)
                        mapping_by_actress[actress.id] = mapping
                    else:
                        mapping.canonical_name_snapshot = name
                        mapping.status = "conflict"
                        mapping.last_sync_at = now
                    result["conflicts"] += 1
                    continue

                if mapping is not None and mapping.status == "conflict":
                    conflicted_remote = (
                        remote_by_id.get(mapping.jellyfin_collection_id)
                        if mapping.jellyfin_collection_id
                        else _find_unmanaged_same_name(remote_collections, name)
                    )
                    if conflicted_remote is not None and not (
                        mapping.jellyfin_collection_id and _is_managed(conflicted_remote)
                    ):
                        result["conflicts"] += 1
                        continue

                if mapping is not None and mapping.jellyfin_collection_id:
                    collection_id = mapping.jellyfin_collection_id
                    remote = remote_by_id.get(collection_id)
                    if remote is not None:
                        if mapping.status == "untagged":
                            # 上次建好合集但打标签失败，这里补上
                            client.set_name_and_tags(collection_id, name, [MANAGED_TAG])
                            remote = {**remote, "name": name, "tags": [MANAGED_TAG]}
                        if not _is_managed(remote):
                            mapping.status = "conflict"
                            mapping.last_sync_at = now
                            result["conflicts"] += 1
                            continue
                        _sync_existing_collection(client, collection_id, remote, expected, name, result)
                        mapping.status = "active"
                        mapping.canonical_name_snapshot = name
                        mapping.last_sync_at = now
                        mapping.last_error = None
                        continue

                unmanaged = _find_unmanaged_same_name(remote_collections, name)
                if unmanaged is not None:
                    if mapping is None:
                        mapping = JellyfinActressCollection(
                            actress_id=actress.id,
                            jellyfin_collection_id=None,
                            canonical_name_snapshot=name,
                            status="conflict",
                            last_sync_at=now,
                        )
                        db.add(mapping)
                        mapping_by_actress[actress.id] = mapping
                    else:
                        mapping.jellyfin_collection_id = None
                        mapping.canonical_name_snapshot = name
                        mapping.status = "conflict"
                        mapping.last_sync_at = now
                    result["conflicts"] += 1
                    continue

                if not expected:
                    # 片子还没在 Jellyfin 找到条目时不建空合集，等下次同步
                    continue

                collection_id = client.create_collection(name, sorted(expected))
                result["collections_created"] += 1
                result["items_added"] += len(expected)
                # 先记下合集，打标签失败时下次还能认出来
                if mapping is None:
                    mapping = JellyfinActressCollection(
                        actress_id=actress.id,
                        jellyfin_collection_id=collection_id,
                        canonical_name_snapshot=name,
                        status="untagged",
                        last_sync_at=now,
                    )
                    db.add(mapping)
                    mapping_by_actress[actress.id] = mapping
                else:
                    mapping.jellyfin_collection_id = collection_id
                    mapping.canonical_name_snapshot = name
                    mapping.status = "untagged"
                    mapping.last_sync_at = now
                client.set_name_and_tags(collection_id, name, [MANAGED_TAG])
                mapping.status = "active"
                mapping.last_error = None
            except Exception as exc:
                if mapping is not None:
                    mapping.last_error = str(exc)
                result["errors"] += 1

        # 不再是白名单、或已被合并删除（actress_id 被外键置空）的女优：清空并删除 18x 建的合集
        for mapping in mappings:
            if mapping.status == "retired" or mapping.actress_id in whitelist_ids:
                continue
            try:
                collection_id = mapping.jellyfin_collection_id
                remote = remote_by_id.get(collection_id) if collection_id else None
                if remote is not None and _is_managed(remote):
                    members = sorted(client.get_collection_item_ids(collection_id))
                    if members:
                        client.remove_from_collection(collection_id, members)
                        result["items_removed"] += len(members)
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
