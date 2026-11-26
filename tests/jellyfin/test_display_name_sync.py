from __future__ import annotations

import pytest

from app.models.jellyfin import JellyfinKeywordCollection, JellyfinMediaItem, JellyfinMediaKeyword
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.jellyfin.client import JellyfinError
from app.services.jellyfin.display_name_sync_service import (
    DisplayNameSyncAborted,
    DisplayNameSyncService,
    UnknownKeyword,
)
from app.services.keywords.registry_service import normalize_keyword_text


ROOT = "/r/已整理"


class FakeDisplayClient:
    """测试用的内存 Jellyfin：只实现显示名同步用到的三个方法。"""

    def __init__(self, items: dict[str, tuple[str, str, list[str] | None]]):
        self.items = {
            path: {"id": item_id, "name": name, "locked_fields": locked}
            for path, (item_id, name, locked) in items.items()
        }
        self.set_calls: list[tuple[str, str, bool]] = []
        self.order_calls: list[str] = []
        self.fail_ids: set[str] = set()
        self.fail_listing = False
        self.fail_order = False

    def iter_media_items(self):
        if self.fail_listing:
            raise JellyfinError("列表暂不可用")
        for path, item in self.items.items():
            locked = item["locked_fields"]
            yield {"id": item["id"], "path": path, "name": item["name"], "locked_fields": list(locked) if locked is not None else None}

    def set_item_name(self, item_id: str, name: str, *, lock: bool = True) -> None:
        self.set_calls.append((item_id, name, lock))
        if item_id in self.fail_ids:
            raise JellyfinError("改名失败")
        for item in self.items.values():
            if item["id"] == item_id:
                item["name"] = name
                locked = [field for field in (item["locked_fields"] or []) if field != "Name"]
                item["locked_fields"] = [*locked, "Name"] if lock else locked

    def ensure_sort_name_order(self, collection_id: str) -> bool:
        self.order_calls.append(collection_id)
        if self.fail_order:
            raise JellyfinError("合集排序失败")
        return True


def _entry(db_session, name: str, *, aliases: tuple[str, ...] = ()) -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=normalize_keyword_text(name),
        keyword_type="whitelist",
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    for alias in aliases:
        db_session.add(KeywordAlias(keyword_entry_id=entry.id, alias=alias, alias_normalized=normalize_keyword_text(alias)))
    db_session.commit()
    return entry


def _media(db_session, path: str, entry: KeywordEntry | None = None, *, source: str = "local", active: bool = True):
    item = JellyfinMediaItem(source=source, path=path, active=active)
    db_session.add(item)
    db_session.flush()
    if entry is not None:
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


def _mapping(db_session, entry: KeywordEntry, collection_id: str, *, status: str = "active"):
    db_session.add(
        JellyfinKeywordCollection(
            keyword_entry_id=entry.id,
            jellyfin_collection_id=collection_id,
            canonical_name_snapshot=entry.canonical_name,
            status=status,
        )
    )
    db_session.commit()


def _sync(db_session, client, **kwargs):
    return DisplayNameSyncService().sync(db_session, client, local_roots=[ROOT], **kwargs)


def test_dry_run_reports_without_writing(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _media(db_session, f"{ROOT}/甲/包/b.mp4", entry)
    _mapping(db_session, entry, "c1")
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/甲/包/b.mp4": ("i2", "b", [])})

    result = _sync(db_session, client, dry_run=True)

    assert result["dry_run"] is True
    assert result["to_update"] == 2
    assert result["updated"] == 0
    assert client.set_calls == []
    assert client.order_calls == []
    assert result["samples"][0] == {"path": f"{ROOT}/甲/包/a.mp4", "old": "a", "new": "甲/包 · 01"}


def test_apply_renames_and_second_run_is_idempotent(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _media(db_session, f"{ROOT}/甲/包/b.mp4", entry)
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/甲/包/b.mp4": ("i2", "b", [])})

    first = _sync(db_session, client)
    second = _sync(db_session, client)

    assert first["updated"] == 2
    assert client.set_calls == [("i1", "甲/包 · 01", True), ("i2", "甲/包 · 02", True)]
    assert second["to_update"] == 0
    assert second["unchanged"] == 2
    assert len(client.set_calls) == 2


def test_relocks_when_name_correct_but_unlocked(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _media(db_session, f"{ROOT}/甲/包/b.mp4", entry)
    client = FakeDisplayClient(
        {
            f"{ROOT}/甲/包/a.mp4": ("i1", "甲/包 · 01", []),
            f"{ROOT}/甲/包/b.mp4": ("i2", "甲/包 · 02", None),
        }
    )

    result = _sync(db_session, client)

    assert client.set_calls == [("i1", "甲/包 · 01", True)]
    assert result["unchanged"] == 1


def test_items_missing_in_jellyfin_do_not_take_numbers(db_session):
    entry = _entry(db_session, "甲")
    for name in ("a", "b", "c"):
        _media(db_session, f"{ROOT}/甲/包/{name}.mp4", entry)
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/甲/包/c.mp4": ("i3", "c", [])})

    result = _sync(db_session, client)

    assert ("i1", "甲/包 · 01", True) in client.set_calls
    assert ("i3", "甲/包 · 02", True) in client.set_calls
    assert result["not_in_jellyfin"] == 1


def test_keyword_filter_only_touches_that_keyword(db_session):
    jia = _entry(db_session, "甲")
    yi = _entry(db_session, "乙")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", jia)
    _media(db_session, f"{ROOT}/乙/包/a.mp4", yi)
    _mapping(db_session, jia, "c-jia")
    _mapping(db_session, yi, "c-yi")
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/乙/包/a.mp4": ("i2", "a", [])})

    result = _sync(db_session, client, keyword="甲")

    assert client.set_calls == [("i1", "甲/包 · 01", True)]
    assert client.order_calls == ["c-jia"]
    assert result["updated"] == 1


def test_keyword_filter_accepts_alias(db_session):
    jia = _entry(db_session, "甲", aliases=("甲酱",))
    yi = _entry(db_session, "乙")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", jia)
    _media(db_session, f"{ROOT}/乙/包/a.mp4", yi)
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/乙/包/a.mp4": ("i2", "a", [])})

    _sync(db_session, client, keyword="甲酱")

    assert client.set_calls == [("i1", "甲/包 · 01", True)]


def test_unknown_keyword_raises(db_session):
    client = FakeDisplayClient({})

    with pytest.raises(UnknownKeyword):
        _sync(db_session, client, keyword="不存在")


def test_single_failure_does_not_stop_others(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _media(db_session, f"{ROOT}/甲/包/b.mp4", entry)
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", []), f"{ROOT}/甲/包/b.mp4": ("i2", "b", [])})
    client.fail_ids = {"i1"}

    result = _sync(db_session, client)

    assert result["failed"] == 1
    assert result["updated"] == 1
    assert ("i2", "甲/包 · 02", True) in client.set_calls


def test_listing_failure_raises_without_writes(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _mapping(db_session, entry, "c1")
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", [])})
    client.fail_listing = True

    # 整轮没干成活时要让任务按失败收尾，不能显示"完成"
    with pytest.raises(JellyfinError):
        _sync(db_session, client)

    assert client.set_calls == []
    assert client.order_calls == []


def test_empty_local_roots_raises_before_touching_jellyfin(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _mapping(db_session, entry, "c1")
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "a", [])})

    with pytest.raises(ValueError):
        DisplayNameSyncService().sync(db_session, client, local_roots=[""])

    assert client.set_calls == []
    assert client.order_calls == []


def test_consecutive_write_failures_abort_the_run(db_session):
    entry = _entry(db_session, "甲")
    items = {}
    for index in range(25):
        path = f"{ROOT}/甲/包/{index}.mp4"
        _media(db_session, path, entry)
        items[path] = (f"i{index}", str(index), [])
    _mapping(db_session, entry, "c1")
    client = FakeDisplayClient(items)
    client.fail_ids = {f"i{index}" for index in range(25)}

    # Jellyfin 挂掉时不能对剩下几万条挨个重试，连续 20 条失败就停
    with pytest.raises(DisplayNameSyncAborted):
        _sync(db_session, client)

    assert len(client.set_calls) == 20
    assert client.order_calls == []


def test_success_resets_consecutive_failure_count(db_session):
    entry = _entry(db_session, "甲")
    items = {}
    for index in range(30):
        path = f"{ROOT}/甲/包/{index}.mp4"
        _media(db_session, path, entry)
        items[path] = (f"i{index}", str(index), [])
    client = FakeDisplayClient(items)
    # 每 10 条里只有 1 条成功，从不连续失败 20 条
    client.fail_ids = {f"i{index}" for index in range(30) if index % 10 != 9}

    result = _sync(db_session, client)

    assert result["failed"] == 27
    assert result["updated"] == 3


def test_consecutive_collection_failures_abort_the_run(db_session):
    client = FakeDisplayClient({})
    for index in range(25):
        entry = _entry(db_session, f"关键词{index}")
        _mapping(db_session, entry, f"c{index}")
    client.fail_order = True

    with pytest.raises(DisplayNameSyncAborted):
        _sync(db_session, client)

    assert len(client.order_calls) == 20


def test_inactive_and_115_items_untouched(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _media(db_session, f"{ROOT}/甲/包/b.mp4", entry, active=False)
    _media(db_session, f"{ROOT}/甲/包/c.strm", entry, source="strm_115")
    client = FakeDisplayClient(
        {
            f"{ROOT}/甲/包/a.mp4": ("i1", "a", []),
            f"{ROOT}/甲/包/b.mp4": ("i2", "b", []),
            f"{ROOT}/甲/包/c.strm": ("i3", "c", []),
        }
    )

    _sync(db_session, client)

    assert client.set_calls == [("i1", "甲/包 · 01", True)]


def test_orders_only_active_mapped_collections(db_session):
    jia = _entry(db_session, "甲")
    yi = _entry(db_session, "乙")
    _mapping(db_session, jia, "c-active")
    _mapping(db_session, yi, "c-old", status="retired")
    client = FakeDisplayClient({})

    result = _sync(db_session, client)

    assert client.order_calls == ["c-active"]
    assert result["collections_ordered"] == 1


def test_restore_sets_stem_and_unlocks(db_session):
    entry = _entry(db_session, "甲")
    _media(db_session, f"{ROOT}/甲/包/a.mp4", entry)
    _mapping(db_session, entry, "c1")
    client = FakeDisplayClient({f"{ROOT}/甲/包/a.mp4": ("i1", "甲/包 · 01", ["Name"])})

    result = _sync(db_session, client, restore=True)

    assert result["restore"] is True
    assert client.set_calls == [("i1", "a", False)]
    assert result["updated"] == 1
    assert client.order_calls == []
