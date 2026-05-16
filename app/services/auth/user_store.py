from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
from pathlib import Path

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AdminUserRecord:
    username: str
    password_hash: str
    password_initialized_at: str
    password_printed_once: bool


class UserStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(self.settings.auth_store_path)

    def load(self) -> AdminUserRecord | None:
        if not self.path.exists():
            return None

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        record = AdminUserRecord(
            username=str(payload["username"]),
            password_hash=str(payload["password_hash"]),
            password_initialized_at=str(payload["password_initialized_at"]),
            password_printed_once=bool(payload.get("password_printed_once", False)),
        )
        if record.username != self.settings.auth_username:
            logger.warning(
                "Configured AUTH_USERNAME=%s differs from persisted auth username=%s; keeping existing password hash",
                self.settings.auth_username,
                record.username,
            )
        return record

    def save(self, record: AdminUserRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def create(self, *, username: str, password_hash: str, initialized_at: datetime) -> AdminUserRecord:
        record = AdminUserRecord(
            username=username,
            password_hash=password_hash,
            password_initialized_at=initialized_at.isoformat(timespec="seconds"),
            password_printed_once=True,
        )
        self.save(record)
        return record
