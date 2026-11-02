from __future__ import annotations

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
