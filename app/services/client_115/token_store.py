"""
Docker-safe token persistence.

Priority on load:  data/tokens.json  >  env vars (ACCESS_TOKEN / REFRESH_TOKEN)
On refresh:        always write to   data/tokens.json

data/ must be a Docker volume mount so tokens survive container restarts.
env vars (ACCESS_TOKEN / REFRESH_TOKEN) serve as the initial seed only;
once the app has refreshed a token, the file takes precedence.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_FILE = Path("data/tokens.json")


@dataclass(slots=True)
class TokenStoreState:
    access_token: str | None
    refresh_token: str | None
    access_token_expires_at: datetime | None = None


def _token_file() -> Path:
    return _TOKEN_FILE


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_token_state() -> TokenStoreState:
    """Return persisted token state from file first, env vars second."""
    token_file = _token_file()
    if token_file.exists():
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            at = data.get("access_token") or None
            rt = data.get("refresh_token") or None
            expires_at = _parse_datetime(data.get("access_token_expires_at"))
            if at:
                logger.debug("Loaded tokens from %s", token_file)
                return TokenStoreState(
                    access_token=at,
                    refresh_token=rt,
                    access_token_expires_at=expires_at,
                )
        except Exception as exc:
            logger.warning("Failed to read %s: %s", token_file, exc)

    at = os.environ.get("ACCESS_TOKEN") or None
    rt = os.environ.get("REFRESH_TOKEN") or None
    if at:
        logger.debug("Loaded tokens from environment variables")
    return TokenStoreState(access_token=at, refresh_token=rt, access_token_expires_at=None)


def load_tokens() -> tuple[str | None, str | None]:
    state = load_token_state()
    return state.access_token, state.refresh_token


def save_tokens(
    access_token: str,
    refresh_token: str | None,
    *,
    access_token_expires_at: datetime | None = None,
) -> None:
    """Persist tokens to data/tokens.json (survives Docker restarts)."""
    token_file = _token_file()
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, str] = {
            "access_token": access_token,
            "refresh_token": refresh_token or "",
        }
        if access_token_expires_at is not None:
            payload["access_token_expires_at"] = access_token_expires_at.isoformat()
        token_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Saved tokens to %s", token_file)
    except Exception as exc:
        logger.error("Failed to save tokens to %s: %s", token_file, exc)
