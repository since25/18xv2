"""
QR Login tool — integrated from p115_qr_login_tool.

Uses raw HTTP (urllib) to fetch QR token, poll status, and retrieve cookies.
This intentionally does NOT use p115client library methods for the cookie flow,
which is kept separate from the Open API token flow used by Real115Client.

Cookies are saved to data/cookies/ (volume-mounted in Docker).

Routes:
  GET  /tools/qr-login/clients  — list available 115 client types
  GET  /tools/qr-login/records  — saved login records
  POST /tools/qr-login/sessions — start a QR login session
  GET  /tools/qr-login/sessions/{session_id} — poll session status
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tools/qr-login", tags=["tools"])

_DATA_DIR = Path("data")
_COOKIES_DIR = _DATA_DIR / "cookies"
_RECORDS_FILE = _DATA_DIR / "qr_records.json"
_QRCODE_API_BASE = "https://qrcodeapi.115.com"

CLIENT_OPTIONS = [
    {"app": "wechatmini", "label": "微信小程序"},
    {"app": "alipaymini", "label": "支付宝小程序"},
    {"app": "web", "label": "网页端"},
    {"app": "desktop", "label": "115 浏览器"},
    {"app": "android", "label": "115 生活安卓端"},
    {"app": "ios", "label": "115 生活苹果端"},
    {"app": "os_windows", "label": "Windows 客户端"},
    {"app": "os_mac", "label": "macOS 客户端"},
    {"app": "qandroid", "label": "115 管理安卓端"},
    {"app": "qios", "label": "115 管理苹果端"},
]
_ALLOWED_APPS = {item["app"] for item in CLIENT_OPTIONS}

_session_lock = Lock()
_sessions: dict[str, "_LoginSession"] = {}
# 扫码会话只在扫码窗口内有效，超过 30 分钟的记录已无意义，创建新会话时惰性清理，
# 避免 _sessions 只增不减。
_SESSION_TTL_SECONDS = 30 * 60


def _prune_sessions() -> None:
    """清理过期会话（调用方必须已持有 _session_lock）。"""
    now_ts = datetime.now().astimezone().timestamp()
    expired = [
        sid
        for sid, item in _sessions.items()
        if now_ts - datetime.fromisoformat(item.created_at).timestamp() > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _sessions.pop(sid, None)


@dataclass(slots=True)
class _LoginSession:
    session_id: str
    app: str
    file_name: str
    uid: str
    qrcode_token: dict
    qr_content: str
    qr_image_url: str
    created_at: str
    updated_at: str
    status: int = 0
    message: str = "waiting"
    cookies: str = ""
    saved_path: str = ""
    error: str = ""


class CreateSessionRequest(BaseModel):
    app: str = Field(..., description="115 target app/device")
    file_name: str = Field(..., min_length=1, max_length=200)


class SessionResponse(BaseModel):
    session_id: str
    app: str
    file_name: str
    uid: str
    status: int
    message: str
    qr_content: str
    qr_image_url: str
    saved_path: str | None = None
    cookies: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanitize_file_name(file_name: str) -> str:
    name = Path(file_name).name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not name.endswith(".txt"):
        name += ".txt"
    return name


def _load_records() -> list[dict]:
    if not _RECORDS_FILE.exists():
        return []
    return json.loads(_RECORDS_FILE.read_text(encoding="utf-8"))


def _save_records(records: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _RECORDS_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _append_record(session: _LoginSession) -> None:
    records = _load_records()
    records.insert(
        0,
        {
            "app": session.app,
            "file_name": session.file_name,
            "saved_path": session.saved_path,
            "uid": session.uid,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        },
    )
    _save_records(records[:100])


def _to_response(session: _LoginSession) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        app=session.app,
        file_name=session.file_name,
        uid=session.uid,
        status=session.status,
        message=session.message,
        qr_content=session.qr_content,
        qr_image_url=session.qr_image_url,
        saved_path=session.saved_path or None,
        cookies=session.cookies or None,
        error=session.error or None,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _resolve_status_text(status: int) -> str:
    return {0: "waiting", 1: "scanned", 2: "signed_in", -1: "expired", -2: "canceled"}.get(
        status, f"unknown:{status}"
    )


def _format_115_error(resp: dict) -> str:
    parts: list[str] = []
    message = resp.get("message") or resp.get("error")
    code = resp.get("code") or resp.get("errno")
    if message:
        parts.append(str(message))
    if code not in (None, ""):
        parts.append(f"code={code}")
    if not parts:
        parts.append(json.dumps(resp, ensure_ascii=False))
    return " | ".join(parts)


def _normalize_cookie_payload(raw_cookie: str | dict) -> str:
    if isinstance(raw_cookie, str):
        return raw_cookie
    if isinstance(raw_cookie, dict):
        parts: list[str] = []
        for key, value in raw_cookie.items():
            if value in (None, ""):
                continue
            parts.append(f"{key}={value}")
        return "; ".join(parts)
    raise TypeError(f"Unsupported cookie payload type: {type(raw_cookie).__name__}")


def _request_json(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    data: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    final_url = url
    if params:
        final_url = f"{url}?{urlencode(params)}"
    body: bytes | None = None
    final_headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0",
    }
    if headers:
        final_headers.update(headers)
    if data is not None:
        body = urlencode(data).encode("utf-8")
        final_headers["content-type"] = "application/x-www-form-urlencoded"
    request = Request(final_url, data=body, headers=final_headers, method=method)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_login_app(app_name: str) -> tuple[str, dict[str, str]]:
    headers: dict[str, str] = {}
    app = app_name
    if app == "desktop":
        app = "web"
    elif app in {"windows", "mac", "linux"}:
        app = f"os_{app}"
    elif app in {"ios", "qios", "ipad", "qipad"}:
        if app == "ios":
            headers["user-agent"] = "UPhone/1.0.0"
        elif app == "qios":
            headers["user-agent"] = "OfficePhone/1.0.0"
        elif app == "ipad":
            headers["user-agent"] = "UPad/1.0.0"
        elif app == "qipad":
            headers["user-agent"] = "OfficePad/1.0.0"
        app = "ios"
    return app, headers


def _fetch_qrcode_token() -> dict:
    return _request_json(f"{_QRCODE_API_BASE}/api/1.0/web/1.0/token/")


def _fetch_qrcode_status(token: dict) -> dict:
    return _request_json(
        f"{_QRCODE_API_BASE}/get/status/",
        params={"uid": token["uid"], "time": token["time"], "sign": token["sign"]},
    )


def _fetch_login_result(uid: str, app_name: str) -> dict:
    app, headers = _normalize_login_app(app_name)
    return _request_json(
        f"{_QRCODE_API_BASE}/app/1.0/{app}/1.0/login/qrcode/",
        method="POST",
        data={"account": uid},
        headers=headers,
    )


# ── API routes ─────────────────────────────────────────────────────────────

@router.get("/clients")
def list_clients() -> dict[str, list[dict]]:
    return {"clients": CLIENT_OPTIONS}


@router.get("/records")
def list_records() -> dict[str, list[dict]]:
    return {"records": _load_records()}


@router.post("/sessions", response_model=SessionResponse)
def create_login_session(payload: CreateSessionRequest) -> SessionResponse:
    if payload.app not in _ALLOWED_APPS:
        raise HTTPException(status_code=400, detail="不支持的客户端")

    file_name = _sanitize_file_name(payload.file_name)
    token_resp = _fetch_qrcode_token()
    if not token_resp.get("state"):
        raise HTTPException(status_code=502, detail=_format_115_error(token_resp))

    token = dict(token_resp["data"])
    uid = str(token["uid"])
    qr_content = token.get("qrcode") or f"https://115.com/scan/dg-{uid}"
    qr_image_url = f"https://qrcodeapi.115.com/api/1.0/web/1.0/qrcode?uid={uid}"
    timestamp = _now_iso()
    session = _LoginSession(
        session_id=uuid4().hex,
        app=payload.app,
        file_name=file_name,
        uid=uid,
        qrcode_token=token,
        qr_content=qr_content,
        qr_image_url=qr_image_url,
        created_at=timestamp,
        updated_at=timestamp,
    )
    with _session_lock:
        _prune_sessions()
        _sessions[session.session_id] = session
    return _to_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def poll_login_session(session_id: str) -> SessionResponse:
    with _session_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="扫码会话不存在")

    with _session_lock:
        if session.status in {-1, -2, -3} or (session.status == 2 and session.saved_path):
            return _to_response(session)
        # 网络调用必须在锁外进行：之前在锁内请求 115 接口（超时最长 20s+），
        # 一个卡顿的轮询会阻塞所有扫码会话的创建与查询。
        qrcode_token = dict(session.qrcode_token)
        uid = session.uid
        app_name = session.app
        file_name = session.file_name
        already_saved = bool(session.saved_path)

    status_resp = _fetch_qrcode_status(qrcode_token)
    status = int((status_resp.get("data") or {}).get("status", 0))

    new_status = status
    new_message = _resolve_status_text(status)
    cookies_text = ""
    saved_path_str = ""
    error_text = ""

    if status == 2 and not already_saved:
        try:
            result_resp = _fetch_login_result(uid, app_name)
            if not result_resp.get("state"):
                new_status = -3
                new_message = "result_error"
                error_text = _format_115_error(result_resp)
            else:
                cookies_text = _normalize_cookie_payload(result_resp["data"]["cookie"])
                _COOKIES_DIR.mkdir(parents=True, exist_ok=True)
                saved_path = _COOKIES_DIR / file_name
                saved_path.write_text(cookies_text + "\n", encoding="utf-8")
                saved_path_str = str(saved_path)
        except Exception as exc:  # noqa: BLE001
            new_status = -3
            new_message = "result_error"
            error_text = str(exc)

    with _session_lock:
        session.status = new_status
        session.message = new_message
        session.updated_at = _now_iso()
        if error_text:
            session.error = error_text
        if saved_path_str:
            session.cookies = cookies_text
            session.saved_path = saved_path_str
            _append_record(session)
    return _to_response(session)
