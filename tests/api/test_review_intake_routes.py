from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import review_intake as _review  # noqa: F401
from app.models import tree as _tree  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth_review_intake.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api import deps

    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_shortcut_bucket_endpoints_create_pending_items(client):
    resp = client.post(
        "/review-intake/whitelist",
        json={"raw_path": "/Volumes/finish/作品【姝姬娘娘】.mp4", "source": "shortcut"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["bucket"] == "whitelist"
    assert data["status"] == "pending"
    assert data["keyword_candidates"][0]["keyword"] == "姝姬娘娘"

    resp = client.get("/review-intake/items?bucket=whitelist&status=pending")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_approve_route_persists_keyword(client):
    created = client.post(
        "/review-intake/blacklist",
        json={"raw_path": "/Volumes/finish/作品【姝姬娘娘】.mp4"},
    ).json()

    resp = client.post(
        f"/review-intake/items/{created['id']}/approve",
        json={"keyword": "姝姬娘娘", "note": "确认黑名单"},
    )

    assert resp.status_code == 200
    approved = resp.json()
    assert approved["status"] == "approved"
    assert approved["approved_keyword"] == "姝姬娘娘"

    keywords = client.get("/keywords?keyword_type=blacklist&query=姝姬娘娘")
    assert keywords.status_code == 200
    assert keywords.json()["total"] == 1


def test_invalid_bucket_is_rejected(client):
    resp = client.post(
        "/review-intake/items",
        json={"bucket": "bad", "raw_path": "/tmp/a.mp4"},
    )

    assert resp.status_code == 422
