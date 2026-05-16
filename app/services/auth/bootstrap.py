from __future__ import annotations

from datetime import datetime
import logging

from app.core.auth import generate_initial_password, hash_password
from app.core.config import Settings, get_settings
from app.services.auth.user_store import UserStore

logger = logging.getLogger(__name__)


def ensure_admin_password_initialized(settings: Settings | None = None) -> str | None:
    resolved_settings = settings or get_settings()
    if not resolved_settings.auth_enabled:
        logger.info("[auth-init] auth disabled; skip password bootstrap")
        return None

    store = UserStore(resolved_settings)
    existing = store.load()
    if existing is not None:
        logger.info("[auth-init] admin password already initialized; skip password generation")
        return None

    password = generate_initial_password()
    store.create(
        username=resolved_settings.auth_username,
        password_hash=hash_password(password),
        initialized_at=datetime.now().astimezone(),
    )
    logger.info("[auth-init] admin username: %s", resolved_settings.auth_username)
    logger.info("[auth-init] initial password (shown only once): %s", password)
    return password
