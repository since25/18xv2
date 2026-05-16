from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture
def client(tmp_path, db_session, monkeypatch):
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTH_SESSION_TTL_HOURS", "24")

    from app.api.deps import get_db
    from app.core.config import get_settings
    from app.services.auth import bootstrap as bootstrap_module
    from app.services.client_115.client import Real115Client

    get_settings.cache_clear()
    monkeypatch.setattr(
        bootstrap_module,
        "generate_initial_password",
        lambda length=20: "FixedPassword123456789",
    )
    monkeypatch.setattr(Real115Client, "ensure_fresh_access_token", lambda self: None)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_login_success_and_me_returns_username(client: TestClient) -> None:
    login_response = client.post(
        "/auth/login",
        json={"username": "wang", "password": "FixedPassword123456789"},
    )

    assert login_response.status_code == 200
    assert login_response.json() == {"success": True, "username": "wang"}
    assert "18x_session" in login_response.cookies

    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {"username": "wang"}


def test_login_with_wrong_password_returns_401(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "wang", "password": "wrong-password"})

    assert response.status_code == 401


def test_me_requires_login_and_logout_clears_session(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401

    login_response = client.post("/auth/login", json={"username": "wang", "password": "FixedPassword123456789"})
    assert login_response.status_code == 200

    logout_response = client.post("/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"success": True}

    assert client.get("/auth/me").status_code == 401


def test_login_cookie_is_not_secure_for_plain_http(tmp_path, db_session, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")

    from app.api.deps import get_db
    from app.core.config import get_settings
    from app.services.auth import bootstrap as bootstrap_module
    from app.services.client_115.client import Real115Client

    get_settings.cache_clear()
    monkeypatch.setattr(
        bootstrap_module,
        "generate_initial_password",
        lambda length=20: "FixedPassword123456789",
    )
    monkeypatch.setattr(Real115Client, "ensure_fresh_access_token", lambda self: None)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with TestClient(app, base_url="http://testserver") as http_client:
            response = http_client.post("/auth/login", json={"username": "wang", "password": "FixedPassword123456789"})
            assert response.status_code == 200
            assert "Secure" not in response.headers.get("set-cookie", "")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_login_cookie_is_secure_for_https(tmp_path, db_session, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")

    from app.api.deps import get_db
    from app.core.config import get_settings
    from app.services.auth import bootstrap as bootstrap_module
    from app.services.client_115.client import Real115Client

    get_settings.cache_clear()
    monkeypatch.setattr(
        bootstrap_module,
        "generate_initial_password",
        lambda length=20: "FixedPassword123456789",
    )
    monkeypatch.setattr(Real115Client, "ensure_fresh_access_token", lambda self: None)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with TestClient(app, base_url="https://testserver") as https_client:
            response = https_client.post("/auth/login", json={"username": "wang", "password": "FixedPassword123456789"})
            assert response.status_code == 200
            assert "Secure" in response.headers.get("set-cookie", "")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
