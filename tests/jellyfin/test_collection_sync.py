from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy import select

from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem, JellyfinMediaKeyword
from app.models.keywords import KeywordEntry
from app.services.jellyfin.client import JellyfinError
from app.services.jellyfin.collection_sync_service import MANAGED_TAG, CollectionSyncService
from app.services.keywords.registry_service import normalize_keyword_text


class FakeJellyfinClient:
    """测试用的内存 Jellyfin 客户端。"""

    def __init__(self, paths: Iterable[tuple[str, str]] = ()):
        self.paths = dict(paths)
        self.collections: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.fail_listing = False
        self.fail_collection_ids: set[str] = set()
        self.fail_tagging = False
        self.next_collection_id = 1

    def iter_media_paths(self):
        if self.fail_listing:
            raise JellyfinError("列表暂不可用")
        yield from self.paths.items()

    def list_collections(self) -> list[dict]:
        return [
            {"id": collection_id, "name": item["name"], "tags": list(item["tags"])}
            for collection_id, item in self.collections.items()
        ]

    def get_collection_item_ids(self, collection_id: str) -> set[str]:
        self.calls.append(("get", collection_id))
        if collection_id in self.fail_collection_ids:
            raise JellyfinError("合集读取失败")
        return set(self.collections[collection_id]["items"])

    def create_collection(self, name: str, item_ids: list[str]) -> str:
        collection_id = f"collection-{self.next_collection_id}"
        self.next_collection_id += 1
        self.collections[collection_id] = {"name": name, "tags": [], "items": set(item_ids)}
        self.calls.append(("create", collection_id, name, list(item_ids)))
        return collection_id

    def set_name_and_tags(self, collection_id: str, name: str, tags: list[str]) -> None:
        self.calls.append(("set", collection_id, name, list(tags)))
        if self.fail_tagging:
            raise JellyfinError("打标签失败")
        self.collections[collection_id]["name"] = name
        self.collections[collection_id]["tags"] = list(tags)

    def add_to_collection(self, collection_id: str, item_ids: list[str]) -> None:
        self.calls.append(("add", collection_id, list(item_ids)))
        self.collections[collection_id]["items"].update(item_ids)

    def remove_from_collection(self, collection_id: str, item_ids: list[str]) -> None:
        self.calls.append(("remove", collection_id, list(item_ids)))
        self.collections[collection_id]["items"].difference_update(item_ids)

    def delete_item(self, collection_id: str) -> None:
        self.calls.append(("delete", collection_id))
        self.collections.pop(collection_id, None)


def _entry(db_session, name: str, *, status: str = "active") -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=normalize_keyword_text(name),
        keyword_type="whitelist",
        status=status,
    )
    db_session.add(entry)
    db_session.flush()
    return entry


def _media_link(db_session, entry: KeywordEntry, path: str, *, item_id: str | None = None) -> JellyfinMediaItem:
    item = JellyfinMediaItem(
        source="local",
        path=path,
        jellyfin_item_id=item_id,
        resolve_state="resolved" if item_id else "pending",
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(
        JellyfinMediaKeyword(
            media_item_id=item.id,
            keyword_entry_id=entry.id,
            match_source="folder_segment",
            raw_term=entry.canonical_name,
        )
    )
    db_session.commit()
    return item


def _mapped_collection(db_session, entry: KeywordEntry, collection_id: str, name: str | None = None):
    mapping = JellyfinKeywordCollection(
        keyword_entry_id=entry.id,
        jellyfin_collection_id=collection_id,
        canonical_name_snapshot=name or entry.canonical_name,
        status="active",
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def test_sync_creates_tagged_collection_with_members(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])

    result = CollectionSyncService().sync(db_session, client)

    assert result["collections_created"] == 1
    created = next(item for item in client.collections.values() if item["name"] == "演员甲")
    assert created["tags"] == [MANAGED_TAG]
    assert created["items"] == {"item-1"}


def test_sync_is_idempotent(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])
    service = CollectionSyncService()

    service.sync(db_session, client)
    result = service.sync(db_session, client)

    assert result == {
        "collections_created": 0,
        "collections_renamed": 0,
        "collections_deleted": 0,
        "items_added": 0,
        "items_removed": 0,
        "pending_items": 0,
        "conflicts": 0,
        "errors": 0,
    }


def test_sync_keeps_pending_and_never_removes_when_unresolved(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4", item_id="item-old")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-old")])
    client.collections["collection-1"] = {
        "name": "演员甲",
        "tags": [MANAGED_TAG],
        "items": {"item-old", "item-extra"},
    }
    _mapped_collection(db_session, entry, "collection-1")
    client.fail_listing = True

    result = CollectionSyncService().sync(db_session, client)

    assert result["items_removed"] == 0
    assert ("remove", "collection-1", ["item-extra"]) not in client.calls
    assert client.collections["collection-1"]["items"] == {"item-old", "item-extra"}


def test_sync_complete_listing_keeps_missing_path_pending_and_out_of_collection(db_session):
    entry = _entry(db_session, "演员甲")
    item = _media_link(db_session, entry, "/媒体/演员甲/missing.mp4")
    client = FakeJellyfinClient()

    result = CollectionSyncService().sync(db_session, client)

    db_session.refresh(item)
    mapping = db_session.scalar(select(JellyfinKeywordCollection))
    assert result["pending_items"] == 1
    assert item.resolve_state == "pending"
    assert mapping is None
    assert client.collections == {}


def test_sync_marks_conflict_for_unmanaged_same_name(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])
    client.collections["manual-1"] = {"name": "演员甲", "tags": [], "items": set()}

    result = CollectionSyncService().sync(db_session, client)

    mapping = db_session.scalar(select(JellyfinKeywordCollection))
    assert result["conflicts"] == 1
    assert mapping.status == "conflict"
    assert mapping.jellyfin_collection_id is None
    assert not any(call[0] in {"create", "set", "add", "remove", "delete"} for call in client.calls)


def test_sync_renames_when_keyword_renamed(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])
    client.collections["collection-1"] = {"name": "旧名称", "tags": [MANAGED_TAG], "items": {"item-1"}}
    _mapped_collection(db_session, entry, "collection-1", name="旧名称")
    entry.canonical_name = "新名称"
    entry.canonical_name_normalized = normalize_keyword_text("新名称")
    db_session.commit()

    result = CollectionSyncService().sync(db_session, client)

    assert result["collections_renamed"] == 1
    assert client.collections["collection-1"]["name"] == "新名称"


def test_sync_deletes_retired_managed_collection(db_session):
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4", item_id="item-1")
    client = FakeJellyfinClient()
    client.collections["collection-1"] = {"name": "演员甲", "tags": [MANAGED_TAG], "items": {"item-1"}}
    mapping = _mapped_collection(db_session, entry, "collection-1")

    db_session.delete(entry)
    db_session.commit()
    result = CollectionSyncService().sync(db_session, client)

    db_session.refresh(mapping)
    assert result["collections_deleted"] == 1
    assert mapping.status == "retired"
    assert "collection-1" not in client.collections


def test_sync_never_touches_untagged_mapped_collection(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])
    client.collections["collection-1"] = {"name": "演员甲", "tags": [], "items": {"item-old"}}
    _mapped_collection(db_session, entry, "collection-1")

    result = CollectionSyncService().sync(db_session, client)

    assert result["conflicts"] == 1
    assert client.collections["collection-1"]["items"] == {"item-old"}
    assert not any(call[0] in {"set", "add", "remove", "delete"} for call in client.calls)


def test_one_collection_error_does_not_stop_others(db_session):
    first = _entry(db_session, "演员甲")
    second = _entry(db_session, "演员乙")
    _media_link(db_session, first, "/媒体/演员甲/a.mp4")
    _media_link(db_session, second, "/媒体/演员乙/b.mp4")
    client = FakeJellyfinClient(
        [
            ("/媒体/演员甲/a.mp4", "item-1"),
            ("/媒体/演员乙/b.mp4", "item-2"),
        ]
    )
    client.collections["collection-1"] = {"name": "演员甲", "tags": [MANAGED_TAG], "items": set()}
    client.collections["collection-2"] = {"name": "演员乙", "tags": [MANAGED_TAG], "items": set()}
    _mapped_collection(db_session, first, "collection-1")
    _mapped_collection(db_session, second, "collection-2")
    client.fail_collection_ids.add("collection-1")

    result = CollectionSyncService().sync(db_session, client)

    assert result["errors"] == 1
    assert client.collections["collection-2"]["items"] == {"item-2"}


def test_sync_listing_failure_creates_nothing(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4", item_id="item-1")
    client = FakeJellyfinClient()
    client.fail_listing = True

    result = CollectionSyncService().sync(db_session, client)

    assert result["errors"] == 1
    assert result["collections_created"] == 0
    assert client.collections == {}


def test_sync_does_not_create_collection_without_resolved_members(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/missing.mp4")
    client = FakeJellyfinClient()

    result = CollectionSyncService().sync(db_session, client)

    assert result["collections_created"] == 0
    assert result["pending_items"] == 1
    assert client.collections == {}


def test_tagging_failure_keeps_mapping_and_next_sync_retries(db_session):
    entry = _entry(db_session, "演员甲")
    _media_link(db_session, entry, "/媒体/演员甲/a.mp4")
    client = FakeJellyfinClient([("/媒体/演员甲/a.mp4", "item-1")])
    client.fail_tagging = True
    service = CollectionSyncService()

    first = service.sync(db_session, client)

    mapping = db_session.scalar(select(JellyfinKeywordCollection))
    assert first["errors"] == 1
    assert mapping.jellyfin_collection_id == "collection-1"
    assert mapping.status == "untagged"
    assert mapping.last_error

    client.fail_tagging = False
    second = service.sync(db_session, client)

    db_session.refresh(mapping)
    assert second["errors"] == 0
    assert second["conflicts"] == 0
    assert second["collections_created"] == 0
    assert len(client.collections) == 1
    assert client.collections["collection-1"]["tags"] == [MANAGED_TAG]
    assert mapping.status == "active"
    assert mapping.last_error is None
