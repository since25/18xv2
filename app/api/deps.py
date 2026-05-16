from __future__ import annotations

from fastapi import HTTPException, Request

from app.db.session import get_db
from app.core.config import get_settings
from app.services.client_115.client import Real115Client
from app.services.auth.session_store import SessionStore
from app.services.source_article_db import SourceArticleDatabaseService


def get_115_client(request: Request) -> Real115Client:
    """Return the singleton 115 client stored on app state (created in lifespan)."""
    return request.app.state.client_115


def get_source_article_db() -> SourceArticleDatabaseService:
    return SourceArticleDatabaseService()

def optional_authenticated_user(request: Request) -> str | None:
    settings = get_settings()
    if not settings.auth_enabled:
        return settings.auth_username

    cached_username = getattr(request.state, "authenticated_username", None)
    if cached_username is not None:
        return cached_username

    session_id = request.cookies.get(settings.auth_cookie_name)
    if not session_id:
        return None

    session = SessionStore(settings).get_session(session_id)
    if session is None:
        return None

    request.state.authenticated_username = session.username
    return session.username


def require_authenticated_user(request: Request) -> str:
    username = optional_authenticated_user(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


__all__ = [
    "get_db",
    "get_115_client",
    "get_source_article_db",
    "optional_authenticated_user",
    "require_authenticated_user",
]
