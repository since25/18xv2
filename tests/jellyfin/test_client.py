from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services.jellyfin.client import JellyfinClient, JellyfinError


def test_iter_media_paths_paginates():
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        start = int(request.url.params["StartIndex"])
        if start == 0:
            return httpx.Response(
                200,
                json={
                    "Items": [{"Path": "/媒体/一.mp4", "Id": "item-1"}, {"Path": "/媒体/二.mp4", "Id": "item-2"}],
                    "TotalRecordCount": 3,
                },
            )
        return httpx.Response(200, json={"Items": [{"Path": "/媒体/三.mp4", "Id": "item-3"}], "TotalRecordCount": 3})

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert list(client.iter_media_paths()) == [
        ("/媒体/一.mp4", "item-1"),
        ("/媒体/二.mp4", "item-2"),
        ("/媒体/三.mp4", "item-3"),
    ]
    assert len(calls) == 2
    assert calls[0]["Limit"] == "2"
    assert calls[1]["StartIndex"] == "2"


def test_retry_on_503_then_success():
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})

    client = JellyfinClient(
        "http://jellyfin.test",
        "test-key",
        3,
        2,
        httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
    )

    assert list(client.iter_media_paths()) == []
    assert attempts == 2
    assert sleeps == [1]


def test_no_retry_on_404():
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"error": "missing"})

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    with pytest.raises(JellyfinError):
        list(client.iter_media_paths())
    assert attempts == 1


def test_auth_header_sent():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == 'MediaBrowser Token="test-key"'
        return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert list(client.iter_media_paths()) == []


def test_set_name_and_tags_reads_item_as_user():
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/Users":
            return httpx.Response(
                200,
                json=[
                    {"Id": "user-2", "Policy": {"IsAdministrator": False}},
                    {"Id": "user-1", "Policy": {"IsAdministrator": True}},
                ],
            )
        if request.method == "GET" and request.url.path == "/Items/collection-1":
            # Jellyfin 10.10 用 API Key 读单个条目时必须指定用户，否则返回 400
            if request.url.params.get("userId") != "user-1":
                return httpx.Response(400)
            return httpx.Response(200, json={"Id": "collection-1", "Name": "旧名", "Tags": []})
        if request.method == "POST" and request.url.path == "/Items/collection-1":
            posted.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.set_name_and_tags("collection-1", "演员甲", ["18x-managed"])

    assert posted == [{"Id": "collection-1", "Name": "演员甲", "Tags": ["18x-managed"]}]


def test_set_name_and_tags_fails_without_admin_user():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Users":
            return httpx.Response(200, json=[{"Id": "user-2", "Policy": {"IsAdministrator": False}}])
        return httpx.Response(404)

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    with pytest.raises(JellyfinError):
        client.set_name_and_tags("collection-1", "演员甲", ["18x-managed"])


def test_create_collection_sends_large_member_list_in_batches():
    batches: list[tuple[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batches.append((request.url.path, request.url.params["Ids"].split(",")))
        if request.url.path == "/Collections":
            return httpx.Response(200, json={"Id": "collection-1"})
        return httpx.Response(204)

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)
    item_ids = [f"item-{index}" for index in range(250)]

    assert client.create_collection("演员甲", item_ids) == "collection-1"

    assert [path for path, _ in batches] == ["/Collections", "/Collections/collection-1/Items", "/Collections/collection-1/Items"]
    assert all(len(ids) <= 100 for _, ids in batches)
    assert [item for _, ids in batches for item in ids] == item_ids


def test_get_collection_item_ids_reads_members_as_user():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Users":
            return httpx.Response(200, json=[{"Id": "user-1", "Policy": {"IsAdministrator": True}}])
        # Jellyfin 10.10 读合集成员时不指定用户会返回空列表
        if request.url.params.get("userId") != "user-1":
            return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})
        return httpx.Response(200, json={"Items": [{"Id": "item-1"}, {"Id": "item-2"}], "TotalRecordCount": 2})

    client = JellyfinClient("http://jellyfin.test", "test-key", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.get_collection_item_ids("collection-1") == {"item-1", "item-2"}


def test_iter_media_items_reads_name_and_locks():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "Items": [
                    {
                        "Id": "i1",
                        "Path": "/r/甲/包/a.mp4",
                        "Name": "a",
                        "LockedFields": ["Name"],
                        "ForcedSortName": "甲/包 · 0000000001",
                    },
                    {"Id": "i2", "Path": "/r/甲/包/b.mp4", "Name": "b"},
                ],
                "TotalRecordCount": 2,
            },
        )

    client = JellyfinClient("http://jf.test", "k", 3, 50, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert list(client.iter_media_items()) == [
        {"id": "i1", "path": "/r/甲/包/a.mp4", "name": "a", "locked_fields": ["Name"], "sort_name": "甲/包 · 0000000001"},
        {"id": "i2", "path": "/r/甲/包/b.mp4", "name": "b", "locked_fields": None, "sort_name": None},
    ]
    # SortName 字段才会返回 ForcedSortName（10.10.7 实测，未设置时不返回该键）
    assert seen[0]["Fields"] == "Path,Settings,SortName"
    assert seen[0]["IsFolder"] == "false"


def _item_handler(item: dict, posted: list[dict]):
    """模拟管理员读写单个条目：GET 必须带管理员 userId，POST 记录提交内容。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/Users":
            return httpx.Response(200, json=[{"Id": "user-1", "Policy": {"IsAdministrator": True}}])
        if request.method == "GET" and request.url.path == f"/Items/{item['Id']}":
            if request.url.params.get("userId") != "user-1":
                return httpx.Response(400)
            return httpx.Response(200, json=dict(item))
        if request.method == "POST" and request.url.path == f"/Items/{item['Id']}":
            posted.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)

    return handler


def test_set_item_name_appends_name_lock():
    posted: list[dict] = []
    handler = _item_handler({"Id": "i1", "Name": "old", "LockedFields": ["Overview"]}, posted)
    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.set_item_name("i1", "01 · 甲/包", sort_name="甲/包 · 0000000001")

    assert len(posted) == 1
    assert posted[0]["Name"] == "01 · 甲/包"
    assert posted[0]["ForcedSortName"] == "甲/包 · 0000000001"
    assert posted[0]["LockedFields"] == ["Overview", "Name"]


def test_set_item_name_does_not_duplicate_lock():
    posted: list[dict] = []
    handler = _item_handler({"Id": "i1", "Name": "old", "LockedFields": ["Name"]}, posted)
    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.set_item_name("i1", "01 · 甲/包", sort_name="甲/包 · 0000000001")

    assert posted[0]["LockedFields"] == ["Name"]


def test_set_item_name_unlock_removes_name_lock():
    posted: list[dict] = []
    handler = _item_handler(
        {"Id": "i1", "Name": "01 · 甲/包", "ForcedSortName": "甲/包 · 0000000001", "LockedFields": ["Overview", "Name"]},
        posted,
    )
    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.set_item_name("i1", "a", sort_name=None, lock=False)

    assert posted[0]["Name"] == "a"
    # 回滚时清掉强制排序名，排序回到 Jellyfin 按名字自动计算
    assert posted[0]["ForcedSortName"] is None
    assert posted[0]["LockedFields"] == ["Overview"]


def test_ensure_sort_name_order_writes_only_when_needed():
    posted: list[dict] = []
    handler = _item_handler({"Id": "c1", "Name": "甲", "DisplayOrder": "PremiereDate"}, posted)
    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.ensure_sort_name_order("c1") is True
    assert posted[0]["DisplayOrder"] == "SortName"

    posted_again: list[dict] = []
    handler = _item_handler({"Id": "c1", "Name": "甲", "DisplayOrder": "SortName"}, posted_again)
    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.ensure_sort_name_order("c1") is False
    assert posted_again == []


def test_find_library_id_matches_location():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/Library/VirtualFolders"
        return httpx.Response(
            200,
            json=[
                {"Name": "115番号", "ItemId": "lib-115", "Locations": ["/mnt/user/docker1/alist-strm/video/302porn_tv1"]},
                {"Name": "本地已整理", "ItemId": "lib-local", "Locations": ["/mnt/disk2/qbbtdn/已整理"]},
            ],
        )

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    # 根目录带不带结尾 / 都能对上
    assert client.find_library_id(["/mnt/disk2/qbbtdn/已整理/"]) == "lib-local"
    assert client.find_library_id(["/别处"]) is None


def _listing_handler(seen: list[dict], items: list[dict]):
    """模拟管理员用户和一页条目列表，记录每次列表请求的参数。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Users":
            return httpx.Response(200, json=[{"Id": "user-1", "Policy": {"IsAdministrator": True}}])
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": len(items)})

    return handler


def test_iter_media_items_can_limit_to_one_library():
    seen: list[dict] = []
    handler = _listing_handler(seen, [{"Id": "i1", "Path": "/r/甲/包/a.mp4", "Name": "a"}])
    client = JellyfinClient("http://jf.test", "k", 3, 50, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert [item["id"] for item in client.iter_media_items(parent_id="lib-local")] == ["i1"]
    assert seen[0]["ParentId"] == "lib-local"
    assert seen[0]["userId"] == "user-1"
    assert seen[0]["Fields"] == "Path,Settings,SortName"


def test_iter_media_items_without_library_reads_everything():
    seen: list[dict] = []
    handler = _listing_handler(seen, [])
    client = JellyfinClient("http://jf.test", "k", 3, 50, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert list(client.iter_media_items()) == []
    assert "ParentId" not in seen[0]


def test_iter_collection_media_items_reads_member_details_as_admin():
    seen: list[dict] = []
    handler = _listing_handler(
        seen, [{"Id": "i1", "Path": "/r/甲/包/a.mp4", "Name": "01 · 甲/包", "LockedFields": ["Name"]}]
    )
    client = JellyfinClient("http://jf.test", "k", 3, 50, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert list(client.iter_collection_media_items("c-jia")) == [
        {"id": "i1", "path": "/r/甲/包/a.mp4", "name": "01 · 甲/包", "locked_fields": ["Name"], "sort_name": None}
    ]
    # Jellyfin 10.10 不带用户读合集成员会返回空
    assert seen[0]["ParentId"] == "c-jia"
    assert seen[0]["userId"] == "user-1"


def test_refresh_library_uses_default_modes():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.refresh_library("lib-115")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/Items/lib-115/Refresh"
    # 界面里的「扫描新增和更新的文件」，不是全量刷新
    assert dict(request.url.params) == {
        "Recursive": "true",
        "MetadataRefreshMode": "Default",
        "ImageRefreshMode": "Default",
        "ReplaceAllMetadata": "false",
        "ReplaceAllImages": "false",
    }
    assert "FullRefresh" not in str(request.url)


def test_refresh_item_params():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.refresh_item("abc")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/Items/abc/Refresh"
    # 按 NFO 重建这个条目的元数据，图片不动
    assert dict(request.url.params) == {
        "MetadataRefreshMode": "FullRefresh",
        "ImageRefreshMode": "Default",
        "ReplaceAllMetadata": "true",
        "ReplaceAllImages": "false",
    }


def test_get_person_image_returns_content_and_type():
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        if request.url.path == "/Persons/甲 乙/丙":
            return httpx.Response(200, json={"Id": "person-1", "Name": "甲 乙/丙"})
        if request.url.path == "/Items/person-1/Images/Primary":
            return httpx.Response(200, content=b"img-bytes", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.get_person_image("甲 乙/丙") == (b"img-bytes", "image/jpeg")
    # 名字整体 URL 编码，斜杠和空格都不能拆开路径
    assert seen[0] == b"/Persons/%E7%94%B2%20%E4%B9%99%2F%E4%B8%99"


def test_get_person_image_returns_none_when_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Persons/有人无图":
            return httpx.Response(200, json={"Id": "person-2"})
        if request.url.path == "/Persons/无编号":
            return httpx.Response(200, json={"Name": "无编号"})
        return httpx.Response(404)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    # 人物不存在、人物没有图、返回里没有 Id 都返回 None，不抛错
    assert client.get_person_image("查无此人") is None
    assert client.get_person_image("有人无图") is None
    assert client.get_person_image("无编号") is None


def test_get_person_returns_id_and_primary_flag():
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        if request.url.path == "/Persons/甲 乙/丙":
            return httpx.Response(200, json={"Id": "p1", "ImageTags": {"Primary": "tag"}})
        if request.url.path == "/Persons/无图":
            return httpx.Response(200, json={"Id": "p2", "ImageTags": {}})
        return httpx.Response(404)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.get_person("甲 乙/丙") == {"id": "p1", "has_primary": True}
    assert seen[0] == b"/Persons/%E7%94%B2%20%E4%B9%99%2F%E4%B8%99"
    assert client.get_person("无图") == {"id": "p2", "has_primary": False}


def test_get_person_404_or_no_id_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Persons/无编号":
            return httpx.Response(200, json={"Name": "无编号"})
        return httpx.Response(404)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    assert client.get_person("查无此人") is None
    assert client.get_person("无编号") is None


def test_get_person_other_errors_raise():
    client = JellyfinClient(
        "http://jf.test", "k", 3, 2, httpx.MockTransport(lambda request: httpx.Response(401)), sleep_fn=lambda _: None
    )

    with pytest.raises(JellyfinError):
        client.get_person("甲")


def test_upload_person_image_posts_base64():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    client = JellyfinClient("http://jf.test", "k", 3, 2, httpx.MockTransport(handler), sleep_fn=lambda _: None)

    client.upload_person_image("p1", b"\xff\xd8abc", "image/jpeg")

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/Items/p1/Images/Primary"
    assert request.headers["Content-Type"] == "image/jpeg"
    assert request.content == base64.b64encode(b"\xff\xd8abc")


def test_upload_person_image_raises_on_error():
    client = JellyfinClient(
        "http://jf.test", "k", 3, 2, httpx.MockTransport(lambda request: httpx.Response(400)), sleep_fn=lambda _: None
    )

    with pytest.raises(JellyfinError):
        client.upload_person_image("p1", b"img", "image/jpeg")
