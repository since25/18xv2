from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
import qrcode

from app.services.client_115.client import Client115Error, Real115Client
router = APIRouter(prefix="/tools/open-auth", tags=["tools"])

_DATA_DIR = Path("data")
_RECORDS_FILE = _DATA_DIR / "open_api_auth_records.json"
_session_lock = Lock()
_sessions: dict[str, "_OpenAuthSession"] = {}


@dataclass(slots=True)
class _OpenAuthSession:
    session_id: str
    uid: str
    sign: str
    time_value: str
    qrcode: str
    qr_image_url: str
    code_verifier: str
    created_at: str
    updated_at: str
    status: int = 0
    message: str = "waiting"
    error: str = ""
    completed: bool = False


class OpenAuthSessionResponse(BaseModel):
    session_id: str
    uid: str
    status: int
    message: str
    qrcode: str
    qr_image_url: str
    error: str | None = None
    created_at: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_status_text(status: int) -> str:
    return {0: "waiting", 1: "scanned", 2: "authorized", -1: "expired", -2: "canceled"}.get(
        status, f"unknown:{status}"
    )


def _to_response(session: _OpenAuthSession) -> OpenAuthSessionResponse:
    return OpenAuthSessionResponse(
        session_id=session.session_id,
        uid=session.uid,
        status=session.status,
        message=session.message,
        qrcode=session.qrcode,
        qr_image_url=session.qr_image_url,
        error=session.error or None,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _load_records() -> list[dict]:
    if not _RECORDS_FILE.exists():
        return []
    try:
        return json.loads(_RECORDS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_records(records: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _RECORDS_FILE.write_text(
        json.dumps(records[:30], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_record(*, token_expires_at: datetime | None) -> None:
    records = _load_records()
    records.insert(
        0,
        {
            "created_at": _now_iso(),
            "token_expires_at": token_expires_at.astimezone(timezone.utc).isoformat() if token_expires_at else None,
        },
    )
    _save_records(records)


def _status_from_payload(payload: dict) -> int:
    data = payload.get("data") or {}
    try:
        return int(data.get("status", 0))
    except (TypeError, ValueError):
        return 0


@router.get("/records")
def list_open_auth_records() -> dict[str, list[dict]]:
    return {"records": _load_records()}


@router.post("/sessions", response_model=OpenAuthSessionResponse)
def create_open_auth_session(request: Request) -> OpenAuthSessionResponse:
    client: Real115Client = request.app.state.client_115
    try:
        device_code, code_verifier = client.create_device_code()
    except Client115Error as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    timestamp = _now_iso()
    uid = str(device_code.uid)
    session = _OpenAuthSession(
        session_id=uuid4().hex,
        uid=uid,
        sign=str(device_code.sign),
        time_value=str(device_code.time),
        qrcode=device_code.qrcode,
        qr_image_url="",
        code_verifier=code_verifier,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.qr_image_url = f"/api/tools/open-auth/sessions/{session.session_id}/qrcode"
    with _session_lock:
        _sessions[session.session_id] = session
    return _to_response(session)


@router.get("/sessions/{session_id}/qrcode")
def open_auth_qrcode_image(session_id: str) -> Response:
    with _session_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Open API 扫码会话不存在")

    image = qrcode.make(session.qrcode)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.get("/sessions/{session_id}", response_model=OpenAuthSessionResponse)
def poll_open_auth_session(session_id: str, request: Request) -> OpenAuthSessionResponse:
    client: Real115Client = request.app.state.client_115
    with _session_lock:
        session = _sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Open API 扫码会话不存在")

        if session.completed or session.status in {-1, -2, -3}:
            return _to_response(session)

        try:
            payload = client.poll_device_status(session.uid, session.time_value, session.sign)
            session.status = _status_from_payload(payload)
            session.message = _resolve_status_text(session.status)
            session.updated_at = _now_iso()

            if session.status == 2 and not session.completed:
                token = client.exchange_device_code(session.uid, session.code_verifier)
                client.persist_token_payload(token)
                status_info = client.get_auth_status_info()
                request.app.state.client_115_ready = bool(status_info["ready"])
                request.app.state.client_115_last_error = status_info["error"]
                request.app.state.client_115_last_error_at = status_info["error_at"]
                request.app.state.client_115_status = status_info["status"]
                request.app.state.client_115_access_token_expires_at = status_info["access_token_expires_at"]
                session.completed = True
                _append_record(token_expires_at=status_info["access_token_expires_at"])
        except Client115Error as exc:
            session.status = -3
            session.message = "error"
            session.error = str(exc)
            session.updated_at = _now_iso()

        _sessions[session_id] = session
        return _to_response(session)
