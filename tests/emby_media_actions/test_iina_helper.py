from __future__ import annotations

from scripts.emby_media_action_shortcut import build_payload


def test_build_payload_for_delete_plan() -> None:
    payload = build_payload("delete-plan", "/media/a.strm", "iina_lua")

    assert payload["action"] == "delete_plan"
    assert payload["path"] == "/media/a.strm"
    assert payload["source"] == "iina_lua"


def test_build_payload_for_blacklist() -> None:
    payload = build_payload("blacklist", "/media/a.strm", "iina_lua")

    assert payload["action"] == "metadata_blacklist"
