from __future__ import annotations

import stat

import pytest

from app.services.script_jobs.site_session import load_site_session, save_site_session, site_session_status


UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/143.0.0.0"


def test_save_and_load_site_session_roundtrip_and_mode_0600(tmp_path):
    path = tmp_path / "sehuatang" / "site_session.json"
    save_site_session(path, "a=1; cf_clearance=SECRET-COOKIE-123 ;  b = x=y ;", UA)
    session = load_site_session(path)
    assert session.cookies == {"a": "1", "cf_clearance": "SECRET-COOKIE-123", "b": "x=y"}
    assert session.user_agent == UA
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_status_never_contains_cookie(tmp_path):
    path = tmp_path / "site_session.json"
    assert site_session_status(path) == {"configured": False, "updated_at": None}
    save_site_session(path, "cf_clearance=SECRET-COOKIE-123", UA)
    status = site_session_status(path)
    assert status["configured"] is True
    assert status["updated_at"] is not None
    assert "SECRET" not in str(status)


def test_load_missing_returns_none(tmp_path):
    assert load_site_session(tmp_path / "missing.json") is None


def test_save_rejects_cookie_without_pairs(tmp_path):
    with pytest.raises(ValueError):
        save_site_session(tmp_path / "s.json", "garbage", UA)
