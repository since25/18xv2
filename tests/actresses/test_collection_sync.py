from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import Actress, ActressAlias, JellyfinActressCollection, JellyfinMediaActor
from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem
from app.models.keywords import KeywordEntry
from app.services.actresses.archive_service import ActressError, ArchiveService
from app.services.actresses.collection_sync import ActressCollectionSyncService
from app.services.actresses.names import normalize_actress_name
from app.services.jellyfin.collection_sync_service import MANAGED_TAG
from app.services.keywords.registry_service import normalize_keyword_text

WRITE_CALLS = {"create", "set", "add", "remove", "delete"}

ZERO_RESULT = {
    "collections_created": 0,
    "collections_renamed": 0,
    "collections_deleted": 0,
    "items_added": 0,
    "items_removed": 0,
    "conflicts": 0,
    "errors": 0,
}


class FakeJellyfinClient:
    """测试用的内存 Jellyfin 客户端，只实现合集相关接口。"""

    def __init__(self) -> None:
        self.collections: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.next_collection_id = 1

    def list_collections(self) -> list[dict]:
        return [
            {"id": collection_id, "name": item["name"], "tags": list(item["tags"])}
            for collection_id, item in self.collections.items()
        ]

    def get_collection_item_ids(self, collection_id: str) -> set[str]:
        self.calls.append(("get", collection_id))
        return set(self.collections[collection_id]["items"])

    def create_collection(self, name: str, item_ids: list[str]) -> str:
        collection_id = f"collection-{self.next_collection_id}"
        self.next_collection_id += 1
        self.collections[collection_id] = {"name": name, "tags": [], "items": set(item_ids)}
        self.calls.append(("create", collection_id, name, list(item_ids)))
        return collection_id

    def set_name_and_tags(self, collection_id: str, name: str, tags: list[str]) -> None:
        self.calls.append(("set", collection_id, name, list(tags)))
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


def _add_film(
    db_session,
    root: Path,
    number: str,
    actors: tuple[str, ...],
    *,
    item_id: str | None = None,
    actor_dir: str = "甲",
) -> JellyfinMediaItem:
    """插入一部单段片子：一个 115 STRM 条目（给了 item_id 即已解析到 Jellyfin）和 NFO 演员行。"""
    item = JellyfinMediaItem(
        source="strm_115",
        path=str(root / actor_dir / number / f"{number}.strm"),
        jellyfin_item_id=item_id,
        resolve_state="resolved" if item_id else "pending",
    )
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
    return item


def _add_actress(db_session, name: str, *, status: str = "whitelist", aliases: tuple[str, ...] = ()) -> Actress:
    actress = Actress(canonical_name=name, canonical_name_normalized=normalize_actress_name(name), status=status)
    actress.aliases = [ActressAlias(alias=alias, alias_normalized=normalize_actress_name(alias)) for alias in aliases]
    db_session.add(actress)
    db_session.commit()
    return actress


def _mapping_of(db_session, actress: Actress) -> JellyfinActressCollection | None:
    return db_session.scalar(select(JellyfinActressCollection).where(JellyfinActressCollection.actress_id == actress.id))


def _roots(tmp_path: Path) -> list[str]:
    return [str(tmp_path / "strm")]


def test_creates_collection_for_whitelisted_actress(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲", aliases=("甲甲",))
    _add_film(db_session, root, "ABC-001", ("甲", "乙"), item_id="jf-1")
    # 别名和空格写法也算她
    _add_film(db_session, root, "ABC-002", ("甲 甲",), item_id="jf-2")
    # 还没在 Jellyfin 找到条目的片子不进合集
    _add_film(db_session, root, "ABC-003", ("甲",))
    client = FakeJellyfinClient()
    service = ActressCollectionSyncService()

    result = service.sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == {**ZERO_RESULT, "collections_created": 1, "items_added": 2}
    assert list(client.collections.values()) == [{"name": "甲", "tags": [MANAGED_TAG], "items": {"jf-1", "jf-2"}}]
    mapping = _mapping_of(db_session, jia)
    assert mapping.status == "active"
    assert mapping.jellyfin_collection_id == "collection-1"
    assert mapping.canonical_name_snapshot == "甲"
    assert mapping.last_error is None

    # 再同步一次没有任何改动
    assert service.sync(db_session, client, strm_roots=_roots(tmp_path)) == ZERO_RESULT


def test_adds_and_removes_members_incrementally(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲")
    _add_film(db_session, root, "ABC-001", ("甲",), item_id="jf-1")
    client = FakeJellyfinClient()
    client.collections["collection-9"] = {"name": "甲", "tags": [MANAGED_TAG], "items": {"jf-old"}}
    db_session.add(
        JellyfinActressCollection(
            actress_id=jia.id, jellyfin_collection_id="collection-9", canonical_name_snapshot="甲", status="active"
        )
    )
    db_session.commit()

    result = ActressCollectionSyncService().sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == {**ZERO_RESULT, "items_added": 1, "items_removed": 1}
    assert client.collections["collection-9"]["items"] == {"jf-1"}


def test_ignores_blacklisted_and_unmarked(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_actress(db_session, "乙", status="blacklist")
    _add_actress(db_session, "丙", status="none")
    _add_film(db_session, root, "ABC-001", ("乙", "丙"), item_id="jf-1")
    # 档案里没有的演员也不建合集
    _add_film(db_session, root, "ABC-002", ("丁",), item_id="jf-2")
    client = FakeJellyfinClient()

    result = ActressCollectionSyncService().sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == ZERO_RESULT
    assert client.collections == {}
    assert db_session.scalars(select(JellyfinActressCollection)).all() == []


def test_does_not_create_empty_collection(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_actress(db_session, "甲")
    # 片子还没在 Jellyfin 找到条目
    _add_film(db_session, root, "ABC-001", ("甲",))
    client = FakeJellyfinClient()

    result = ActressCollectionSyncService().sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == ZERO_RESULT
    assert client.collections == {}
    assert db_session.scalars(select(JellyfinActressCollection)).all() == []


def test_retires_collection_after_unwhitelist(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲")
    _add_film(db_session, root, "ABC-001", ("甲",), item_id="jf-1")
    client = FakeJellyfinClient()
    service = ActressCollectionSyncService()
    service.sync(db_session, client, strm_roots=_roots(tmp_path))
    client.calls.clear()

    ArchiveService().set_status(db_session, [jia.id], "none", source="web")
    result = service.sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == {**ZERO_RESULT, "collections_deleted": 1, "items_removed": 1}
    # 先清空成员再删合集
    assert client.calls == [("get", "collection-1"), ("remove", "collection-1", ["jf-1"]), ("delete", "collection-1")]
    assert client.collections == {}
    mapping = _mapping_of(db_session, jia)
    assert mapping.status == "retired"
    assert mapping.last_error is None

    # 已退役的映射不再处理
    client.calls.clear()
    assert service.sync(db_session, client, strm_roots=_roots(tmp_path)) == ZERO_RESULT
    assert client.calls == []


def test_retires_collection_when_actress_merged_away(db_session, tmp_path):
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲")
    yi = _add_actress(db_session, "乙")
    _add_film(db_session, root, "ABC-001", ("甲",), item_id="jf-1")
    _add_film(db_session, root, "ABC-002", ("乙",), item_id="jf-2", actor_dir="乙")
    client = FakeJellyfinClient()
    service = ActressCollectionSyncService()
    service.sync(db_session, client, strm_roots=_roots(tmp_path))
    yi_mapping = _mapping_of(db_session, yi)
    yi_collection_id = yi_mapping.jellyfin_collection_id
    jia_collection_id = _mapping_of(db_session, jia).jellyfin_collection_id

    # 合并删除乙，映射的 actress_id 由外键置空
    ArchiveService().merge(db_session, yi.id, jia.id)
    db_session.expire_all()
    result = service.sync(db_session, client, strm_roots=_roots(tmp_path))

    db_session.refresh(yi_mapping)
    assert yi_mapping.actress_id is None
    assert yi_mapping.status == "retired"
    assert yi_collection_id not in client.collections
    # 乙成了甲的别名，乙的片子并进甲的合集
    assert client.collections[jia_collection_id]["items"] == {"jf-1", "jf-2"}
    assert result == {**ZERO_RESULT, "collections_deleted": 1, "items_added": 1, "items_removed": 1}


def test_actress_collection_conflicts_with_keyword_collection_name(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲")
    yi = _add_actress(db_session, "乙")
    _add_film(db_session, root, "ABC-001", ("甲",), item_id="jf-1")
    _add_film(db_session, root, "ABC-002", ("乙",), item_id="jf-2", actor_dir="乙")
    keyword = KeywordEntry(
        canonical_name="甲", canonical_name_normalized=normalize_keyword_text("甲"), keyword_type="whitelist"
    )
    db_session.add(keyword)
    db_session.flush()
    db_session.add_all(
        [
            JellyfinKeywordCollection(
                keyword_entry_id=keyword.id,
                jellyfin_collection_id="kw-1",
                canonical_name_snapshot="甲",
                status="active",
            ),
            # 已退役的关键词合集不占名字
            JellyfinKeywordCollection(
                keyword_entry_id=None, jellyfin_collection_id=None, canonical_name_snapshot="乙", status="retired"
            ),
        ]
    )
    db_session.commit()
    client = FakeJellyfinClient()
    client.collections["kw-1"] = {"name": "甲", "tags": [MANAGED_TAG], "items": {"kw-item"}}
    service = ActressCollectionSyncService()

    result = service.sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == {**ZERO_RESULT, "collections_created": 1, "items_added": 1, "conflicts": 1}
    # 关键词合集原样不动，甲不另建同名合集
    assert client.collections["kw-1"] == {"name": "甲", "tags": [MANAGED_TAG], "items": {"kw-item"}}
    assert not any(call[0] in WRITE_CALLS and call[1] == "kw-1" for call in client.calls)
    assert [item["name"] for item in client.collections.values()] == ["甲", "乙"]
    jia_mapping = _mapping_of(db_session, jia)
    assert jia_mapping.status == "conflict"
    assert jia_mapping.jellyfin_collection_id is None
    assert _mapping_of(db_session, yi).status == "active"

    # 冲突持续时每次只报告
    client.calls.clear()
    again = service.sync(db_session, client, strm_roots=_roots(tmp_path))
    assert again == {**ZERO_RESULT, "conflicts": 1}
    assert not any(call[0] in WRITE_CALLS for call in client.calls)


def test_leaves_unmanaged_collections_untouched(db_session, tmp_path):
    root = tmp_path / "strm"
    jia = _add_actress(db_session, "甲")
    yi = _add_actress(db_session, "乙", status="none")
    _add_film(db_session, root, "ABC-001", ("甲",), item_id="jf-1")
    client = FakeJellyfinClient()
    # 用户手工建的同名合集
    client.collections["manual-1"] = {"name": "甲", "tags": [], "items": {"manual-item"}}
    # 映射指向的合集被用户去掉了标签：退役时不删
    client.collections["manual-2"] = {"name": "乙", "tags": ["其他标签"], "items": {"manual-item"}}
    client.collections["manual-3"] = {"name": "别的合集", "tags": [], "items": {"jf-1"}}
    db_session.add(
        JellyfinActressCollection(
            actress_id=yi.id, jellyfin_collection_id="manual-2", canonical_name_snapshot="乙", status="active"
        )
    )
    db_session.commit()
    before = {collection_id: dict(item, items=set(item["items"])) for collection_id, item in client.collections.items()}

    result = ActressCollectionSyncService().sync(db_session, client, strm_roots=_roots(tmp_path))

    assert result == {**ZERO_RESULT, "conflicts": 1}
    assert client.collections == before
    assert not any(call[0] in WRITE_CALLS for call in client.calls)
    jia_mapping = _mapping_of(db_session, jia)
    assert jia_mapping.status == "conflict"
    assert jia_mapping.jellyfin_collection_id is None
    assert _mapping_of(db_session, yi).status == "retired"


def test_refuses_without_strm_roots(db_session, tmp_path):
    yi = _add_actress(db_session, "乙", status="none")
    client = FakeJellyfinClient()
    client.collections["collection-1"] = {"name": "乙", "tags": [MANAGED_TAG], "items": {"jf-1"}}
    db_session.add(
        JellyfinActressCollection(
            actress_id=yi.id, jellyfin_collection_id="collection-1", canonical_name_snapshot="乙", status="active"
        )
    )
    db_session.commit()

    # 根目录没配置时一部片都读不到，不能据此退役、删除合集
    with pytest.raises(ActressError):
        ActressCollectionSyncService().sync(db_session, client, strm_roots=[" "])

    assert "collection-1" in client.collections
    assert client.calls == []
    assert _mapping_of(db_session, yi).status == "active"
