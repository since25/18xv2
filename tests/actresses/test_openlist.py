from __future__ import annotations

import json

import httpx
import pytest

from app.services.actresses.openlist import OpenListClient, OpenListError, openlist_dir_for


def _client(handler) -> OpenListClient:
    return OpenListClient("http://openlist.test/", "test-token", timeout=3, transport=httpx.MockTransport(handler))


def test_refresh_dir_posts_forced_list():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 200, "message": "success", "data": {"content": []}})

    _client(handler).refresh_dir("/115_OPEN/AV")

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://openlist.test/api/fs/list"
    assert request.headers["Authorization"] == "test-token"
    assert json.loads(request.content) == {
        "path": "/115_OPEN/AV",
        "refresh": True,
        "password": "",
        "page": 1,
        "per_page": 0,
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"code": 401, "message": "token is invalidated"}),
        httpx.Response(200, json={"code": 500, "message": "object not found"}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
    ],
    ids=["auth", "api-error", "http-500", "not-json"],
)
def test_refresh_dir_raises_on_failure(response):
    with pytest.raises(OpenListError):
        _client(lambda request: response).refresh_dir("/115_OPEN/AV")


def test_refresh_dir_wraps_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("虚构：连不上", request=request)

    with pytest.raises(OpenListError):
        _client(handler).refresh_dir("/115_OPEN/AV")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://openlist.test/d/115_OPEN/AV/ABC-001.mp4", "/115_OPEN/AV"),
        ("http://openlist.test/d/115_OPEN/AV/%E7%94%B2/ABC-001.mp4", "/115_OPEN/AV/甲"),
        ("http://openlist.test/d/115_OPEN/ABC-001.mp4", "/115_OPEN"),
    ],
)
def test_openlist_dir_for(url, expected):
    assert openlist_dir_for(url) == expected


def test_openlist_dir_for_rejects_non_115_url():
    with pytest.raises(ValueError):
        openlist_dir_for("http://openlist.test/d/other/AV/ABC-001.mp4")


def test_list_dir_returns_names_and_dirs():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "content": [
                        {"name": "a.nfo", "is_dir": False},
                        {"name": "sub", "is_dir": True},
                    ]
                },
            },
        )

    assert _client(handler).list_dir("/115_OPEN/AV") == [("a.nfo", False), ("sub", True)]
    assert json.loads(seen[0].content)["refresh"] is False
    assert json.loads(seen[0].content)["path"] == "/115_OPEN/AV"


def test_list_dir_null_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "data": {"content": None}})

    assert _client(handler).list_dir("/115_OPEN/AV") == []


def test_list_dir_error_raises():
    with pytest.raises(OpenListError):
        _client(lambda request: httpx.Response(200, json={"code": 500, "message": "object not found"})).list_dir(
            "/115_OPEN/AV"
        )
