from __future__ import annotations

import json
import logging

from app.core.auth import verify_password
from app.core.config import get_settings
from app.services.auth.bootstrap import ensure_admin_password_initialized


def test_first_bootstrap_creates_auth_file_and_hash(tmp_path, monkeypatch, caplog) -> None:
    auth_path = tmp_path / "auth.json"
    monkeypatch.setenv("AUTH_STORE_PATH", str(auth_path))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    get_settings.cache_clear()

    caplog.set_level(logging.INFO)

    generated_password = ensure_admin_password_initialized()

    assert generated_password is not None
    assert auth_path.exists()

    payload = json.loads(auth_path.read_text(encoding="utf-8"))
    assert payload["username"] == "wang"
    assert payload["password_printed_once"] is True
    assert verify_password(generated_password, payload["password_hash"]) is True
    assert "initial password (shown only once)" in caplog.text


def test_second_bootstrap_keeps_existing_hash_and_does_not_log_password(tmp_path, monkeypatch, caplog) -> None:
    auth_path = tmp_path / "auth.json"
    monkeypatch.setenv("AUTH_STORE_PATH", str(auth_path))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    get_settings.cache_clear()

    first_password = ensure_admin_password_initialized()
    original_payload = json.loads(auth_path.read_text(encoding="utf-8"))

    caplog.clear()
    caplog.set_level(logging.INFO)

    second_password = ensure_admin_password_initialized()
    second_payload = json.loads(auth_path.read_text(encoding="utf-8"))

    assert first_password is not None
    assert second_password is None
    assert original_payload["password_hash"] == second_payload["password_hash"]
    assert "shown only once" not in caplog.text
    assert "already initialized" in caplog.text
