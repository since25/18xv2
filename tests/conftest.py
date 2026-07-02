"""
共享 pytest fixture。每个测试函数获得独立的 SQLite 数据库和 Fake115Client 实例。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import dedupe as _dedupe_models  # noqa: F401
from app.models import emby_media_actions as _emby_media_actions_models  # noqa: F401
from app.models import keywords as _keywords_models  # noqa: F401
from app.models import organization as _organization_models  # noqa: F401
from app.models import review_intake as _review_intake_models  # noqa: F401
from app.models import tasks as _task_models  # noqa: F401
from app.models import tree as _tree_models  # noqa: F401
from app.models import whitelist as _whitelist_models  # noqa: F401
from app.services.client_115.client import Fake115Client


@pytest.fixture
def db_session(tmp_path) -> Session:
    """每个测试独立 SQLite，避免测试间状态污染。"""
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def fake_client() -> Fake115Client:
    """返回一个空 Fake115Client，可通过 add_node() 添加测试数据。"""
    return Fake115Client()
