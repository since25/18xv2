from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.services.client_115.client import Client115Error, Real115Client
from app.services.client_115.schemas import TokenPayload


def _build_client(monkeypatch, tmp_path) -> Real115Client:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        ACCESS_TOKEN="access-token",
        REFRESH_TOKEN="refresh-token",
        APP_ID="app-id",
    )
    return Real115Client(settings=settings)


def test_40140126_does_not_trigger_refresh(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    refresh_attempts: list[str] = []

    def fake_refresh():
        refresh_attempts.append("called")
        raise AssertionError("40140126 should not trigger refresh")

    monkeypatch.setattr(client, "refresh_access_token_and_persist", fake_refresh)

    with pytest.raises(Client115Error):
        client._call(  # noqa: SLF001
            lambda: (_ for _ in ()).throw(
                Client115Error(
                    "[Errno 22] {'state': False, 'message': 'access_token 校验失败', 'code': 40140126}"
                )
            ),
            auth_required=True,
        )

    assert refresh_attempts == []
    status_info = client.get_auth_status_info()
    assert status_info["status"] == "reauth_required"


def test_persist_tokens_records_access_token_expiry(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    token = TokenPayload(
        access_token="new-access",
        refresh_token="new-refresh",
        expires_in=3600,
    )

    client.persist_token_payload(token)

    status_info = client.get_auth_status_info()
    expires_at = status_info["access_token_expires_at"]
    assert isinstance(expires_at, datetime)
    assert expires_at > datetime.now(timezone.utc) + timedelta(minutes=50)


def test_submit_magnet_download_accepts_dict_data(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    magnet_url = "magnet:?xt=urn:btih:dict-case"

    monkeypatch.setattr(
        client,
        "_call",
        lambda operation, auth_required=False: {
            "state": True,
            "data": {
                "task_id": 12345,
                "info_hash": "abc123",
                "url": magnet_url,
                "status": 1,
            },
        },
    )

    result = client.submit_magnet_download(magnet_url)

    assert result.task_id == "12345"
    assert result.info_hash == "abc123"
    assert result.url == magnet_url
    assert result.status == "1"


def test_submit_magnet_download_accepts_list_data(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    magnet_url = "magnet:?xt=urn:btih:list-case"

    monkeypatch.setattr(
        client,
        "_call",
        lambda operation, auth_required=False: {
            "state": True,
            "data": [
                {
                    "info_hash": "def456",
                    "url": magnet_url,
                }
            ],
        },
    )

    result = client.submit_magnet_download(magnet_url)

    assert result.task_id is None
    assert result.info_hash == "def456"
    assert result.url == magnet_url
