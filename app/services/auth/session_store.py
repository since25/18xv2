from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path

from app.core.auth import generate_session_id
from app.core.config import Settings, get_settings


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    username: str
    created_at: str
    expires_at: str


class SessionStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        auth_path = Path(self.settings.auth_store_path)
        self.path = auth_path.with_name("auth_sessions.json")

    def _load_payload(self) -> dict[str, list[dict]]:
        if not self.path.exists():
            return {"sessions": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save_payload(self, payload: dict[str, list[dict]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _purge_expired(self, payload: dict[str, list[dict]], *, now: datetime) -> dict[str, list[dict]]:
        active_sessions = []
        for item in payload.get("sessions", []):
            try:
                expires_at = datetime.fromisoformat(str(item["expires_at"]))
            except (KeyError, TypeError, ValueError):
                continue
            if expires_at > now:
                active_sessions.append(item)
        payload["sessions"] = active_sessions
        return payload

    def create_session(self, username: str) -> SessionRecord:
        now = datetime.now().astimezone()
        expires_at = now + timedelta(hours=max(1, self.settings.auth_session_ttl_hours))
        record = SessionRecord(
            session_id=generate_session_id(),
            username=username,
            created_at=now.isoformat(timespec="seconds"),
            expires_at=expires_at.isoformat(timespec="seconds"),
        )
        payload = self._purge_expired(self._load_payload(), now=now)
        payload["sessions"].append(asdict(record))
        self._save_payload(payload)
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        now = datetime.now().astimezone()
        payload = self._purge_expired(self._load_payload(), now=now)
        self._save_payload(payload)
        for item in payload.get("sessions", []):
            if item.get("session_id") == session_id:
                return SessionRecord(
                    session_id=str(item["session_id"]),
                    username=str(item["username"]),
                    created_at=str(item["created_at"]),
                    expires_at=str(item["expires_at"]),
                )
        return None

    def delete_session(self, session_id: str) -> None:
        payload = self._load_payload()
        payload["sessions"] = [
            item for item in payload.get("sessions", []) if item.get("session_id") != session_id
        ]
        self._save_payload(payload)
