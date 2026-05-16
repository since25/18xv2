"""
QR Login tool — integrated from p115_qr_login_tool.

Uses raw HTTP (urllib) to fetch QR token, poll status, and retrieve cookies.
This intentionally does NOT use p115client library methods for the cookie flow,
which is kept separate from the Open API token flow used by Real115Client.

Cookies are saved to data/cookies/ (volume-mounted in Docker).

Routes:
  GET  /tools/qr-login          — HTML workbench
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
from fastapi.responses import HTMLResponse
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

@router.get("", response_class=HTMLResponse)
def qr_login_page() -> str:
    options_html = "".join(
        f'<option value="{item["app"]}">{item["label"]} ({item["app"]})</option>'
        for item in CLIENT_OPTIONS
    )
    return _QR_LOGIN_HTML.replace("<!-- __CLIENT_OPTIONS__ -->", options_html)


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
        _sessions[session.session_id] = session
    return _to_response(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def poll_login_session(session_id: str) -> SessionResponse:
    with _session_lock:
        session = _sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="扫码会话不存在")

        if session.status in {-1, -2, -3} or (session.status == 2 and session.saved_path):
            return _to_response(session)

        status_resp = _fetch_qrcode_status(dict(session.qrcode_token))
        status = int((status_resp.get("data") or {}).get("status", 0))
        session.status = status
        session.message = _resolve_status_text(status)
        session.updated_at = _now_iso()

        if status == 2 and not session.saved_path:
            try:
                result_resp = _fetch_login_result(session.uid, session.app)
                if not result_resp.get("state"):
                    session.status = -3
                    session.message = "result_error"
                    session.error = _format_115_error(result_resp)
                    session.updated_at = _now_iso()
                    _sessions[session.session_id] = session
                    return _to_response(session)
                cookies = _normalize_cookie_payload(result_resp["data"]["cookie"])
                _COOKIES_DIR.mkdir(parents=True, exist_ok=True)
                saved_path = _COOKIES_DIR / session.file_name
                saved_path.write_text(cookies + "\n", encoding="utf-8")
                session.cookies = cookies
                session.saved_path = str(saved_path)
                _append_record(session)
            except Exception as exc:  # noqa: BLE001
                session.status = -3
                session.message = "result_error"
                session.error = str(exc)
                session.updated_at = _now_iso()

        _sessions[session.session_id] = session
        return _to_response(session)


# ── Embedded HTML ──────────────────────────────────────────────────────────

_QR_LOGIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>115 扫码登录工具</title>
  <style>
    :root{--bg:#f4efe7;--card:#fffaf4;--ink:#1e2320;--muted:#66706a;--accent:#125f54;--line:#ded4c6;--soft:#dcefeb}
    *{box-sizing:border-box}
    body{margin:0;font-family:"PingFang SC","Noto Sans SC",sans-serif;background:linear-gradient(135deg,#f8f2ea,#ebe0d2);color:var(--ink)}
    .shell{max-width:900px;margin:0 auto;padding:28px 18px 48px}
    .hero{padding:24px;color:#fff;background:linear-gradient(135deg,rgba(18,95,84,.95),rgba(15,92,138,.92));border-radius:24px;margin-bottom:22px}
    .hero h1{margin:0 0 6px;font-size:22px}
    .hero p{margin:0;opacity:.85;font-size:14px}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin-bottom:18px}
    label{display:block;margin:10px 0 5px;font-size:13px;color:var(--muted)}
    select,input{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:12px;font:inherit;background:#fff}
    button{width:100%;padding:12px;margin-top:12px;border:none;border-radius:14px;cursor:pointer;font:inherit;font-weight:600;background:var(--accent);color:#fff}
    button.sec{background:var(--soft);color:var(--accent);border:1px solid rgba(18,95,84,.2)}
    .qr-wrap{text-align:center;padding:16px 0}
    .qr-wrap img{max-width:220px;border-radius:12px;border:1px solid var(--line)}
    .status-box{margin-top:14px;padding:12px 16px;border-radius:14px;background:#f3ece2;font-size:13px;line-height:1.6;white-space:pre-wrap}
    .badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;background:#eee5d8;color:var(--muted);margin-right:6px}
    .badge.ok{background:#c7ead5;color:#0d5c3a}
    .badge.err{background:#f7d9d6;color:#8c2010}
    .record-list{display:grid;gap:10px;margin-top:14px}
    .record{background:#fff;border:1px solid var(--line);border-radius:14px;padding:10px 14px;font-size:13px}
    .record strong{display:block;margin-bottom:4px}
    .record .meta{color:var(--muted)}
    a{color:var(--accent)}
  </style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <h1>115 扫码登录工具</h1>
    <p>扫码获取 115 账号 Cookie，保存为文本文件备用。此功能与 Open API Token 流程相互独立。</p>
  </section>

  <div class="panel">
    <label for="appSel">目标客户端</label>
    <select id="appSel"><!-- __CLIENT_OPTIONS__ --></select>
    <div id="clientErr" style="display:none;color:#8c2010;font-size:13px;margin-top:6px;padding:8px 12px;background:#fff0ee;border-radius:10px;border:1px solid rgba(140,32,16,.18)"></div>
    <label for="fileNameInput">保存文件名</label>
    <input id="fileNameInput" placeholder="例如：myaccount" />
    <button id="startBtn">生成二维码</button>
  </div>

  <div class="panel" id="qrPanel" style="display:none">
    <div class="qr-wrap">
      <img id="qrImg" src="" alt="QR Code" />
      <div style="margin-top:8px;font-size:13px;color:var(--muted)">请使用 115 扫码</div>
    </div>
    <div class="status-box" id="statusBox">等待扫码…</div>
    <button class="sec" id="stopBtn" style="margin-top:10px">停止轮询</button>
  </div>

  <div class="panel">
    <strong style="font-size:15px">历史记录</strong>
    <button class="sec" id="refreshRecordsBtn" style="width:auto;padding:6px 16px;margin-top:8px">刷新</button>
    <div class="record-list" id="recordList"><div style="color:var(--muted);font-size:13px;margin-top:10px">暂无记录</div></div>
  </div>
</div>

<script>
const API = "/tools/qr-login";
let pollTimer = null;
let currentSessionId = null;

async function fetchJson(url, opts = {}) {
  const r = await fetch(url, opts);
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

async function loadClients() {
  const errDiv = document.getElementById("clientErr");
  try {
    const data = await fetchJson(API + "/clients");
    if (!Array.isArray(data.clients) || data.clients.length === 0) {
      errDiv.textContent = "未获取到客户端列表，请刷新重试。";
      errDiv.style.display = "";
      return;
    }
    const sel = document.getElementById("appSel");
    sel.innerHTML = "";
    data.clients.forEach(c => {
      const o = document.createElement("option");
      o.value = c.app;
      o.textContent = c.label + " (" + c.app + ")";
      sel.appendChild(o);
    });
    errDiv.style.display = "none";
  } catch (e) {
    errDiv.textContent = "加载客户端失败：" + e.message;
    errDiv.style.display = "";
  }
}

async function loadRecords() {
  const { records } = await fetchJson(API + "/records");
  const list = document.getElementById("recordList");
  if (!records.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:13px;margin-top:10px">暂无记录</div>';
    return;
  }
  list.innerHTML = records.map(r => `
    <div class="record">
      <strong>${r.file_name}</strong>
      <div class="meta">客户端：${r.app} &nbsp;|&nbsp; uid: ${r.uid}</div>
      <div class="meta">保存路径：${r.saved_path || "—"}</div>
      <div class="meta">${r.updated_at}</div>
    </div>`).join("");
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function statusBadge(status, message) {
  if (status === 2) return '<span class="badge ok">已登录</span>';
  if (status < 0) return '<span class="badge err">' + message + '</span>';
  if (status === 1) return '<span class="badge">已扫码，请在手机确认</span>';
  return '<span class="badge">等待扫码</span>';
}

async function poll() {
  if (!currentSessionId) return;
  try {
    const s = await fetchJson(API + "/sessions/" + currentSessionId);
    const box = document.getElementById("statusBox");
    box.innerHTML = statusBadge(s.status, s.message);
    if (s.status === 2 && s.saved_path) {
      box.innerHTML += "\n✅ Cookie 已保存至：" + s.saved_path;
      if (s.cookies) box.innerHTML += "\n\nCookie 预览（前200字符）：\n" + s.cookies.slice(0, 200);
      stopPolling();
      loadRecords();
    } else if (s.status < 0) {
      box.innerHTML += (s.error ? "\n错误：" + s.error : "");
      stopPolling();
    }
  } catch(e) {
    document.getElementById("statusBox").textContent = "轮询出错：" + e.message;
    stopPolling();
  }
}

document.getElementById("startBtn").addEventListener("click", async () => {
  stopPolling();
  const app = document.getElementById("appSel").value;
  const fileName = document.getElementById("fileNameInput").value.trim() || "cookie";
  try {
    const s = await fetchJson(API + "/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app, file_name: fileName }),
    });
    currentSessionId = s.session_id;
    document.getElementById("qrImg").src = s.qr_image_url;
    document.getElementById("qrPanel").style.display = "";
    document.getElementById("statusBox").textContent = "等待扫码…";
    pollTimer = setInterval(poll, 2000);
  } catch(e) {
    alert("创建会话失败：" + e.message);
  }
});

document.getElementById("stopBtn").addEventListener("click", () => {
  stopPolling();
  document.getElementById("statusBox").textContent = "已停止轮询。";
});

document.getElementById("refreshRecordsBtn").addEventListener("click", loadRecords);

loadClients();
loadRecords();
</script>
</body>
</html>"""
