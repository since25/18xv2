from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import emby_media_action_shortcut as shortcut
from scripts.emby_media_action_shortcut import RequestFailed, build_payload


def test_build_payload_for_delete_plan() -> None:
    payload = build_payload("delete-plan", "/media/a.strm", "iina_lua")

    assert payload["action"] == "delete_plan"
    assert payload["path"] == "/media/a.strm"
    assert payload["source"] == "iina_lua"
    assert payload["emby_item_id"] == "/media/a.strm"
    assert payload["title"] == "a.strm"


def test_build_payload_for_blacklist() -> None:
    payload = build_payload("blacklist", "/media/a.strm", "iina_lua")

    assert payload["action"] == "metadata_blacklist"
    assert payload["path"] == "/media/a.strm"
    assert payload["source"] == "iina_lua"
    assert payload["emby_item_id"] == "/media/a.strm"
    assert payload["title"] == "a.strm"


def test_build_payload_for_whitelist() -> None:
    payload = build_payload("whitelist", "/media/a.strm", "iina_lua")

    assert payload["action"] == "metadata_whitelist"
    assert payload["path"] == "/media/a.strm"
    assert payload["source"] == "iina_lua"
    assert payload["emby_item_id"] == "/media/a.strm"
    assert payload["title"] == "a.strm"


@pytest.mark.parametrize(
    ("cli_action", "api_action"),
    [
        ("delete-plan", "delete_plan"),
        ("blacklist", "metadata_blacklist"),
        ("whitelist", "metadata_whitelist"),
    ],
)
def test_main_submits_intake_payload_for_each_action(
    cli_action: str,
    api_action: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[object, str, dict | None]] = []
    opener = object()

    def fake_build_opener(*_processors):
        return opener

    def fake_json_request(request_opener, url: str, payload: dict | None = None) -> dict:
        calls.append((request_opener, url, payload))
        return {"ok": True}

    monkeypatch.setattr(shortcut, "build_opener", fake_build_opener)
    monkeypatch.setattr(shortcut, "_json_request", fake_json_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "emby_media_action_shortcut.py",
            cli_action,
            "--path",
            "/media/a.strm",
            "--source",
            "iina_lua",
            "--base-url",
            "http://example.test/api/",
            "--cookie-path",
            str(tmp_path / "cookies.txt"),
        ],
    )

    assert shortcut.main() == 0

    assert calls == [
        (
            opener,
            "http://example.test/api/emby-media-actions/intake",
            {
                "action": api_action,
                "path": "/media/a.strm",
                "source": "iina_lua",
                "emby_item_id": "/media/a.strm",
                "title": "a.strm",
            },
        )
    ]
    output = capsys.readouterr()
    assert output.err == ""
    assert f"已提交 Emby 媒体动作：{cli_action}" in output.out


def test_main_prints_backend_error_and_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = object()

    def fake_build_opener(*_processors):
        return opener

    def fake_json_request(_request_opener, _url: str, _payload: dict | None = None) -> dict:
        raise RequestFailed(400, "bad")

    monkeypatch.setattr(shortcut, "build_opener", fake_build_opener)
    monkeypatch.setattr(shortcut, "_json_request", fake_json_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "emby_media_action_shortcut.py",
            "delete-plan",
            "--path",
            "/media/a.strm",
            "--base-url",
            "http://example.test/api",
            "--cookie-path",
            str(tmp_path / "cookies.txt"),
        ],
    )

    assert shortcut.main() == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "bad" in output.err
