from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import emby_media_actions as _emby_media_actions  # noqa: F401
from app.models import keywords as _keywords  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.services.client_115.client import Fake115Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_STRM_ROOTS", str(tmp_path))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_SOURCE_ROOTS", str(tmp_path / "source"))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS", str(tmp_path / "organized"))
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
    _main.app.state.client_115 = Fake115Client()
    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_metadata_candidate_apply_route(client: TestClient) -> None:
    created = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": "/media/a.strm",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "nfo_xml": "<movie><actor><name>演员A</name></actor></movie>",
            "actors": [{"name": "演员A", "role": None, "provider_ids": {}}],
        },
    )

    assert created.status_code == 200
    candidate_id = created.json()["metadata_candidate"]["id"]

    applied = client.post(
        f"/emby-media-actions/metadata-candidates/{candidate_id}/apply",
        json={"actors": ["演员A"], "note": "确认"},
    )

    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
