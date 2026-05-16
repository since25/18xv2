from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.main import app


class _Fake115Client:
    def ensure_fresh_access_token(self) -> None:
        return None

    def get_auth_status_info(self) -> dict[str, object]:
        return {
            "ready": True,
            "status": "ok",
            "error": None,
            "error_at": None,
            "access_token_expires_at": None,
        }

    def exchange_auth_code(self, auth_code: str):
        from app.services.client_115.schemas import TokenPayload

        return TokenPayload(access_token=f"access-{auth_code}", refresh_token="refresh-token")

    def _persist_tokens(self, token) -> None:
        self.last_token = token

    def list_files(self, cid: str, limit: int = 1) -> dict:
        return {"cid": cid, "limit": limit}


@pytest.fixture
def client(tmp_path, db_session, monkeypatch):
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_USERNAME", "wang")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.api.deps import get_db
    from app.core.config import get_settings
    from app.services.auth import bootstrap as bootstrap_module
    from app.services.client_115 import client as client_module

    get_settings.cache_clear()
    monkeypatch.setattr(
        bootstrap_module,
        "generate_initial_password",
        lambda length=20: "FixedPassword123456789",
    )
    monkeypatch.setattr(client_module, "Real115Client", _Fake115Client)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _login(test_client: TestClient) -> None:
    response = test_client.post("/auth/login", json={"username": "wang", "password": "FixedPassword123456789"})
    assert response.status_code == 200


def test_batch_execute_requires_login(client: TestClient) -> None:
    response = client.post("/plans/batch-execute", json={"plan_ids": []})
    assert response.status_code == 401


def test_auth_code_requires_login(client: TestClient) -> None:
    response = client.post("/tools/auth-code", json={"auth_code": "demo"})
    assert response.status_code == 401


def test_logged_in_user_can_access_protected_tool_route(client: TestClient) -> None:
    _login(client)

    response = client.post("/tools/auth-code", json={"auth_code": "demo"})

    assert response.status_code == 200
    assert response.json()["success"] is True
