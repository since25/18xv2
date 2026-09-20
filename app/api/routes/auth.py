from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from threading import Lock

from app.api.deps import require_authenticated_user
from app.core.auth import verify_password
from app.core.config import get_settings
from app.services.auth.session_store import SessionStore
from app.services.auth.user_store import UserStore

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_FAILURES: dict[str, list[datetime]] = {}
_LOGIN_FAILURE_LOCK = Lock()
_LOGIN_WINDOW = timedelta(minutes=15)
_LOGIN_LOCKOUT = timedelta(minutes=5)
_LOGIN_MAX_FAILURES = 5


def _login_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_login_locked(key: str, now: datetime) -> bool:
    with _LOGIN_FAILURE_LOCK:
        failures = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW]
        _LOGIN_FAILURES[key] = failures
        return len(failures) >= _LOGIN_MAX_FAILURES


def _record_login_failure(key: str, now: datetime) -> None:
    with _LOGIN_FAILURE_LOCK:
        failures = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW]
        failures.append(now)
        _LOGIN_FAILURES[key] = failures


def _clear_login_failures(key: str) -> None:
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURES.pop(key, None)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    username: str


class MeResponse(BaseModel):
    username: str


class LogoutResponse(BaseModel):
    success: bool


def _should_use_secure_cookie(request: Request) -> bool:
    settings = get_settings()
    return settings.auth_cookie_secure and request.url.scheme == "https"


def _set_session_cookie(request: Request, response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=session_id,
        httponly=True,
        secure=_should_use_secure_cookie(request),
        samesite=settings.auth_cookie_samesite,
        max_age=max(3600, settings.auth_session_ttl_hours * 3600),
        path="/",
    )


def _clear_session_cookie(request: Request, response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=_should_use_secure_cookie(request),
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    settings = get_settings()
    if not settings.auth_enabled:
        return LoginResponse(success=True, username=settings.auth_username)

    now = datetime.now(UTC)
    login_key = _login_key(request)
    if _is_login_locked(login_key, now):
        raise HTTPException(status_code=429, detail="Too many login failures; try again later")

    stored_user = UserStore(settings).load()
    if stored_user is None:
        raise HTTPException(status_code=503, detail="Admin password is not initialized")
    if payload.username != settings.auth_username:
        _record_login_failure(login_key, now)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(payload.password, stored_user.password_hash):
        _record_login_failure(login_key, now)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    _clear_login_failures(login_key)
    session = SessionStore(settings).create_session(username=settings.auth_username)
    _set_session_cookie(request, response, session.session_id)
    return LoginResponse(success=True, username=settings.auth_username)


@router.post("/logout", response_model=LogoutResponse)
def logout(request: Request, response: Response) -> LogoutResponse:
    settings = get_settings()
    session_id = request.cookies.get(settings.auth_cookie_name)
    if session_id:
        SessionStore(settings).delete_session(session_id)
    _clear_session_cookie(request, response)
    return LogoutResponse(success=True)


@router.get("/me", response_model=MeResponse)
def me(username: str = Depends(require_authenticated_user)) -> MeResponse:
    return MeResponse(username=username)
