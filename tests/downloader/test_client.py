from __future__ import annotations

import json

import httpx
import pytest

from app.services.downloader.client import DownloaderClient, DownloaderRemoteError


class Settings:
    downloader_base_url = "http://rn.test"
    downloader_password = "secret"
    downloader_timeout_seconds = 3.0
    downloader_node_key = "rn"


def test_client_logs_in_gets_csrf_and_reads_packages_with_cursor():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.headers)))
        if request.method == "POST" and request.url.path == "/login":
            assert request.content == b"password=secret"
            return httpx.Response(200, json={"code": "1"})
        if request.method == "GET" and request.url.path == "/api/csrf-token":
            return httpx.Response(200, json={"csrf_token": "csrf-1"})
        if request.method == "GET" and request.url.path == "/api/packages":
            assert request.headers["X-CSRF-Token"] == "csrf-1"
            return httpx.Response(200, json={"items": [{"id": 9, "title": "A"}], "next_cursor": "next"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    client = DownloaderClient(Settings(), transport=httpx.MockTransport(handler))
    payload = client.list_packages(cursor="old", page_size=10)
    assert payload["items"][0]["id"] == 9
    assert payload["next_cursor"] == "next"
    assert [path for _, path, _ in calls] == ["/login", "/api/csrf-token", "/api/packages"]


def test_client_submits_incremental_package_with_idempotency_and_csrf():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/login":
            return httpx.Response(200, json={"code": "1"})
        if request.method == "GET" and request.url.path == "/api/csrf-token":
            return httpx.Response(200, json={"csrf_token": "csrf-2"})
        if request.method == "POST" and request.url.path == "/api/packages/123/download-batch":
            assert request.headers["X-CSRF-Token"] == "csrf-2"
            assert request.headers["Idempotency-Key"] == "18x:123:r4:incremental"
            assert json.loads(request.content) == {"mode": "incremental"}
            return httpx.Response(202, json={"batch": {"id": 5, "task_id": "task-5"}, "created": True})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    client = DownloaderClient(Settings(), transport=httpx.MockTransport(handler))
    assert client.submit_package(123, "18x:123:r4:incremental", mode="incremental")["batch"]["task_id"] == "task-5"


def test_client_maps_login_failure_without_exposing_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0"})

    client = DownloaderClient(Settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(DownloaderRemoteError) as error:
        client.get_dashboard()
    assert error.value.code == "authentication_failed"
    assert "secret" not in str(error.value)


def test_client_accepts_rn_task_list_response_as_json_array():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/login":
            return httpx.Response(200, json={"code": "1"})
        if request.method == "GET" and request.url.path == "/api/csrf-token":
            return httpx.Response(200, json={"csrf_token": "csrf-3"})
        if request.method == "GET" and request.url.path == "/api/tasks":
            return httpx.Response(200, json=[{"task_id": "task-1", "status": "completed"}])
        raise AssertionError(f"unexpected {request.method} {request.url}")

    client = DownloaderClient(Settings(), transport=httpx.MockTransport(handler))
    assert client.list_tasks() == [{"task_id": "task-1", "status": "completed"}]
