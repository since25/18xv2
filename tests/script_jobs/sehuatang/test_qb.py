from __future__ import annotations

import httpx
import pytest

from app.services.script_jobs.sehuatang.qb import QbClient, QbError


def _client(handler) -> QbClient:
    return QbClient("https://qb.invalid:16666", "user", "SECRET-PW-456", transport=httpx.MockTransport(handler))


def test_login_and_add_torrent_send_category():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.login()
    client.add_torrent(b"d4:infod4:name1:aee", "1.torrent", "国产BT")
    client.add_magnets(["magnet:?xt=urn:btih:A", "magnet:?xt=urn:btih:B"], "国产BT")

    assert [request.url.path for request in seen] == [
        "/api/v2/auth/login",
        "/api/v2/torrents/add",
        "/api/v2/torrents/add",
    ]
    assert "国产BT".encode() in seen[1].content
    assert b"magnet:?xt=urn:btih:A\nmagnet:?xt=urn:btih:B" in httpx.QueryParams(seen[2].content.decode()).get(
        "urls"
    ).encode()


def test_login_failure_raises_without_password():
    client = _client(lambda request: httpx.Response(200, text="Fails."))
    with pytest.raises(QbError) as excinfo:
        client.login()
    assert "SECRET-PW-456" not in str(excinfo.value)
    assert "登录失败" in str(excinfo.value)


def test_qb_error_message_has_no_request_body():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    client.login()
    with pytest.raises(QbError) as excinfo:
        client.add_magnets(["magnet:?xt=urn:btih:SECRETHASH"], "国产BT")
    message = str(excinfo.value)
    assert "Fails." in message
    assert "SECRETHASH" not in message


def test_connection_error_becomes_qb_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(QbError, match="连接失败"):
        _client(handler).login()
