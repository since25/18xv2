from __future__ import annotations

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
