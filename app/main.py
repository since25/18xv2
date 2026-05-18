from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import get_settings
from app.api.deps import optional_authenticated_user
from app.services.auth.bootstrap import ensure_admin_password_initialized

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {
    "/healthz",
    "/auth/login",
    "/auth/logout",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时创建 115 client 单例，仅读取本地 token 状态，不主动 refresh。"""
    from app.services.client_115.client import Real115Client

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    ensure_admin_password_initialized(settings)

    client = Real115Client()
    app.state.client_115 = client
    status_info = client.get_auth_status_info()
    app.state.client_115_ready = bool(status_info["ready"])
    app.state.client_115_last_error = status_info["error"]
    app.state.client_115_last_error_at = status_info["error_at"]
    app.state.client_115_status = status_info["status"]
    app.state.client_115_access_token_expires_at = status_info["access_token_expires_at"]
    logger.info("115 client singleton ready in passive mode")

    # 上次异常退出可能留下 status="pending" 的记录，防止 UI 显示永久 pending
    from app.db.session import SessionLocal as _SessionLocal
    from app.models.tree import TreeImport as _TreeImport
    with _SessionLocal() as _s:
        interrupted = (
            _s.query(_TreeImport)
            .filter(_TreeImport.status == "pending")
            .update({"status": "interrupted"})
        )
        _s.commit()
        if interrupted:
            logger.info("lifespan: 清理 %d 条残留 pending 导入记录 → interrupted", interrupted)

    yield
    logger.info("Shutting down")


app = FastAPI(title="18x Organizer", version="0.2.0", lifespan=lifespan)
if get_settings().auth_trust_proxy:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

from app.api.routes import (  # noqa: E402 — import after app creation
    auth,
    auth_code,
    cleanup,
    extractor,
    files_115,
    home,
    imports,
    jobs,
    keywords,
    local_cleanup,
    local_organize,
    local_tree_export,
    magnet_tasks,
    nodes,
    open_auth,
    path_picker,
    plans,
    qr_login,
    strategy,
    tasks,
)


@app.middleware("http")
async def enforce_authentication(request: Request, call_next):
    settings = get_settings()
    if not settings.auth_enabled:
        return await call_next(request)

    if request.url.path not in _PUBLIC_PATHS:
        username = optional_authenticated_user(request)
        if username is None:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        request.state.authenticated_username = username

    return await call_next(request)


app.include_router(auth.router)
app.include_router(home.router)
app.include_router(auth_code.router)
app.include_router(imports.router)
app.include_router(nodes.router)
app.include_router(strategy.router)
app.include_router(extractor.router)
app.include_router(keywords.router)
app.include_router(keywords.legacy_router)
app.include_router(cleanup.router)
app.include_router(local_cleanup.router)
app.include_router(local_organize.router)
app.include_router(local_tree_export.router)
app.include_router(magnet_tasks.router)
app.include_router(path_picker.router)
app.include_router(plans.router)
app.include_router(jobs.router)
app.include_router(tasks.router)
app.include_router(qr_login.router)
app.include_router(open_auth.router)
app.include_router(files_115.router)


@app.get("/healthz")
def healthcheck(request: Request) -> dict:
    client_ready = getattr(request.app.state, "client_115_ready", False)
    authorization_status = getattr(request.app.state, "client_115_status", None)
    return {
        "status": "ok",
        "service_status": "ok",
        "auth_mode": "open_api_token",
        "authorization_status": authorization_status or ("ready" if client_ready else "needs_auth"),
        "client_115": client_ready,
        "client_115_error": getattr(request.app.state, "client_115_last_error", None),
    }


# 客户端 app 标识 → 描述
_APP_DESCRIPTIONS: dict[str, str] = {
    "web": "115生活_网页端",
    "desktop": "115浏览器",
    "ios": "115生活_苹果端",
    "android": "115生活_安卓端",
    "ipad": "115生活_苹果平板端",
    "bios": "未知: ios",
    "bandroid": "未知: android",
    "bipad": "未知: ipad",
    "115ios": "115_苹果端",
    "115android": "115_安卓端",
    "115ipad": "115_苹果平板端",
    "tv": "115生活_安卓电视端",
    "apple_tv": "115生活_苹果电视端",
    "qandriod": "115管理_安卓端",
    "qios": "115管理_苹果端",
    "qipad": "115管理_苹果平板端",
    "os_windows": "115生活_Windows端",
    "os_mac": "115生活_macOS端",
    "os_linux": "115生活_Linux端",
    "wechatmini": "115生活_微信小程序端",
    "alipaymini": "115生活_支付宝小程序",
    "harmony": "115_鸿蒙端",
}


@app.get("/system-status")
def system_status(request: Request) -> dict:
    """返回缓存的 Open API 状态和 cookies 可用性；不主动探测 token。"""
    import json
    from pathlib import Path

    client_115 = getattr(request.app.state, "client_115", None)
    token_expires_at = None
    auth_status = "error"
    if client_115 is not None and hasattr(client_115, "get_auth_status_info"):
        status_info = client_115.get_auth_status_info()
        ready = bool(status_info["ready"])
        token_error = status_info["error"]
        token_error_at = status_info["error_at"]
        token_expires_at = status_info["access_token_expires_at"]
        auth_status = str(status_info["status"])
    else:
        ready = getattr(request.app.state, "client_115_ready", False)
        token_error = getattr(request.app.state, "client_115_last_error", None)
        token_error_at = getattr(request.app.state, "client_115_last_error_at", None)
        token_expires_at = getattr(request.app.state, "client_115_access_token_expires_at", None)
        auth_status = "ok" if ready else "error"
    request.app.state.client_115_ready = ready
    request.app.state.client_115_last_error = token_error
    request.app.state.client_115_last_error_at = token_error_at
    request.app.state.client_115_status = auth_status
    request.app.state.client_115_access_token_expires_at = token_expires_at
    token_status = auth_status

    # ── 2. Cookies 检查（每条 QR 记录）────────────────────────────────
    data_dir = Path("data")
    records_file = data_dir / "qr_records.json"
    records: list[dict] = []
    if records_file.exists():
        try:
            records = json.loads(records_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    cookies_status: list[dict] = []
    try:
        import p115client as _p115  # noqa: PLC0415
    except ImportError:
        _p115 = None  # type: ignore[assignment]

    for rec in records:
        app_name = rec.get("app", "")
        saved_path = rec.get("saved_path", "")
        cookie_file = Path(saved_path) if saved_path else None
        entry: dict = {
            "app": app_name,
            "app_description": _APP_DESCRIPTIONS.get(app_name, app_name),
            "file_name": rec.get("file_name", ""),
            "saved_path": saved_path,
            "uid": rec.get("uid", ""),
            "status": "error",
            "user_name": None,
            "error": None,
        }
        if not cookie_file or not cookie_file.exists():
            entry["error"] = "cookie 文件不存在"
            cookies_status.append(entry)
            continue
        if _p115 is None:
            entry["error"] = "p115client 未安装"
            cookies_status.append(entry)
            continue
        try:
            c = _p115.P115Client(cookie_file.read_text().strip())
            info = c.user_info()
            user_data = (info.get("data") or {})
            entry["status"] = "ok"
            entry["user_name"] = user_data.get("user_name")
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
        cookies_status.append(entry)

    return {
        "token_status": token_status,
        "token_error": token_error,
        "token_error_at": token_error_at,
        "token_expires_at": token_expires_at,
        "token_probe_mode": "passive_cached_state",
        "cookies": cookies_status,
    }
