"""
115 Open API client.

Design:
- Real115Client is a singleton created once at app startup via FastAPI lifespan.
- Tokens are loaded from data/tokens.json (Docker volume) on init, falling back
  to ACCESS_TOKEN / REFRESH_TOKEN env vars as the initial seed.
- On every successful token refresh the new tokens are written back to
  data/tokens.json so they survive container restarts.
- A single shared _open_client (P115OpenClient) is reused across requests;
  it is replaced only when tokens actually change.
"""
from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
import secrets
import time

from app.core.config import Settings, get_settings
from app.services.client_115.schemas import (
    ClientActionResult,
    DeviceCodePayload,
    NodePayload,
    OfflineTaskPayload,
    TokenPayload,
)
from app.services.client_115.token_store import load_token_state, save_tokens

logger = logging.getLogger(__name__)

_AUTH_ERROR_CODE_RE = re.compile(r"\b(401401\d{2})\b")
_REFRESHABLE_ACCESS_TOKEN_CODES = {"40140125"}
_REFRESH_TOKEN_REAUTH_CODES = {"40140114", "40140115", "40140116", "40140119", "40140120"}
_REFRESH_THROTTLED_CODES = {"40140117"}

try:
    from p115client import P115OpenClient, check_response
except ImportError:  # pragma: no cover
    P115OpenClient = None

    def check_response(resp: dict) -> dict:
        return resp


class Client115Error(RuntimeError):
    pass


class Real115Client:
    """Singleton 115 Open API client.

    Instantiate once (in FastAPI lifespan) and inject via app.state.
    Thread-safety note: _last_refresh_time and _last_request_at are instance
    variables now (not class variables), so multiple instances don't interfere.
    """

    def __init__(self, settings: Settings | None = None, timeout: float = 20.0) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout
        self._last_request_at: float = 0.0
        self._last_refresh_time: float = 0.0
        self._refresh_retry_after: float = 0.0
        self._auth_ready: bool = bool(self.settings.access_token)
        self._auth_status: str = "ok" if self.settings.access_token else "missing"
        self._last_auth_error: str | None = None
        self._last_auth_error_at: datetime | None = None
        self._access_token_expires_at: datetime | None = None
        self._open_client = None

        # Bootstrap tokens: file store takes priority over env vars
        token_state = load_token_state()
        if token_state.access_token:
            self.settings.access_token = token_state.access_token
            self.settings.refresh_token = token_state.refresh_token
            self._access_token_expires_at = token_state.access_token_expires_at
            self._auth_ready = True
            self._auth_status = "ok"
            logger.info("115 client initialised with tokens from token store")
        elif self.settings.access_token:
            logger.info("115 client initialised with tokens from environment")
            self._auth_ready = True
            self._auth_status = "ok"
        else:
            logger.warning("115 client has no ACCESS_TOKEN — auth-required calls will fail")
            self._auth_status = "missing"

    @staticmethod
    def _ensure_dependency() -> None:
        if P115OpenClient is None:
            raise Client115Error("p115client is not installed")

    @staticmethod
    def _is_invalid_access_token_error(message: str) -> bool:
        code = Real115Client._extract_auth_error_code(message)
        if code == "40140126":
            return False
        if code in _REFRESHABLE_ACCESS_TOKEN_CODES:
            return True
        normalized = message.lower()
        return (
            "access_token 无效" in message
            or "access token invalid" in normalized
            or "invalid access token" in normalized
            or "unauthorized" in normalized
        )

    @staticmethod
    def _extract_auth_error_code(message: str) -> str | None:
        match = _AUTH_ERROR_CODE_RE.search(message)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _normalize_expiry(expires_at: datetime | None) -> datetime | None:
        if expires_at is None:
            return None
        if expires_at.tzinfo is None:
            return expires_at.replace(tzinfo=timezone.utc)
        return expires_at.astimezone(timezone.utc)

    def _set_auth_state(
        self,
        status: str,
        *,
        ready: bool,
        error: str | None = None,
        error_at: datetime | None = None,
    ) -> None:
        self._auth_status = status
        self._auth_ready = ready
        self._last_auth_error = error
        self._last_auth_error_at = error_at

    def _persist_tokens(self, token: TokenPayload) -> None:
        """Update in-memory state and persist to data/tokens.json."""
        self.settings.access_token = token.access_token
        self.settings.refresh_token = token.refresh_token or self.settings.refresh_token
        expires_at = None
        if token.expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, token.expires_in))
        self._access_token_expires_at = expires_at
        # Replace open client so subsequent calls use the new token immediately
        self._open_client = P115OpenClient.from_token(
            token.access_token, self.settings.refresh_token or ""
        )
        save_tokens(
            token.access_token,
            self.settings.refresh_token,
            access_token_expires_at=expires_at,
        )
        get_settings.cache_clear()
        self._refresh_retry_after = 0.0
        self._set_auth_state("ok", ready=True)

    def _mark_refresh_throttled(self) -> None:
        cooldown = max(0, self.settings.api_refresh_cooldown_seconds)
        self._last_refresh_time = time.monotonic()
        self._refresh_retry_after = self._last_refresh_time + cooldown
        self._auth_status = "cooldown"

    def get_auth_status(self) -> tuple[bool, str | None, datetime | None]:
        return self._auth_ready, self._last_auth_error, self._last_auth_error_at

    def get_auth_status_info(self) -> dict[str, object]:
        status = self._auth_status
        if status == "cooldown" and not self._refresh_in_cooldown():
            status = "error" if self._last_auth_error else ("ok" if self._auth_ready else "missing")
            self._auth_status = status
        return {
            "ready": self._auth_ready,
            "status": status,
            "error": self._last_auth_error,
            "error_at": self._last_auth_error_at,
            "access_token_expires_at": self._normalize_expiry(self._access_token_expires_at),
        }

    def _record_auth_error(self, message: str, *, status: str = "error", ready: bool = False) -> None:
        self._set_auth_state(
            status,
            ready=ready,
            error=message,
            error_at=datetime.now(timezone.utc),
        )

    def _refresh_in_cooldown(self) -> bool:
        return time.monotonic() < self._refresh_retry_after

    def _should_refresh_access_token(self, min_ttl_seconds: int = 300) -> bool:
        if not self.settings.refresh_token or self._access_token_expires_at is None:
            return False
        expires_at = self._normalize_expiry(self._access_token_expires_at)
        if expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        return expires_at <= now + timedelta(seconds=max(0, min_ttl_seconds))

    def _handle_refresh_error(self, exc: Client115Error) -> None:
        message = str(exc)
        code = self._extract_auth_error_code(message)
        if code in _REFRESH_THROTTLED_CODES or "refresh frequently" in message.lower():
            self._mark_refresh_throttled()
            self._record_auth_error(message, status="cooldown")
            return
        if code in _REFRESH_TOKEN_REAUTH_CODES:
            self._record_auth_error(message, status="reauth_required")
            return
        self._record_auth_error(message)

    def refresh_access_token_and_persist(self) -> TokenPayload:
        token = self.refresh_access_token()
        self._persist_tokens(token)
        self._last_refresh_time = time.monotonic()
        logger.info("115 access token refreshed and persisted")
        return token

    def persist_token_payload(self, token: TokenPayload) -> None:
        self._persist_tokens(token)

    def ensure_fresh_access_token(self) -> TokenPayload | None:
        """Refresh only when token expiry is near or already reached."""
        if not self._should_refresh_access_token():
            return None
        if self._refresh_in_cooldown():
            logger.warning("115 token refresh is in cooldown, skipping proactive refresh")
            return None
        try:
            return self.refresh_access_token_and_persist()
        except Client115Error as exc:
            self._handle_refresh_error(exc)
            if self._auth_status == "cooldown":
                return None
            raise

    def _wait_for_rate_limit(self) -> None:
        min_interval = max(0, self.settings.api_min_interval_ms) / 1000
        if min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def _get_open_client(self):
        self._ensure_dependency()
        if not self.settings.access_token:
            raise Client115Error("ACCESS_TOKEN is not configured")
        if self._open_client is None:
            self._open_client = P115OpenClient.from_token(
                self.settings.access_token, self.settings.refresh_token or ""
            )
        return self._open_client

    def _call(self, operation, *, auth_required: bool = False) -> dict:
        self._ensure_dependency()
        retries = max(0, self.settings.api_max_retries)
        backoff = max(0, self.settings.api_retry_backoff_ms) / 1000
        last_error: Exception | None = None
        refreshed_on_invalid_token = False

        for attempt in range(retries + 1):
            try:
                if auth_required and not self.settings.access_token:
                    raise Client115Error("ACCESS_TOKEN is not configured")
                if auth_required and self._should_refresh_access_token() and not self._refresh_in_cooldown():
                    self.refresh_access_token_and_persist()
                self._wait_for_rate_limit()
                payload = check_response(operation())
                self._last_request_at = time.monotonic()
                if auth_required:
                    self._set_auth_state("ok", ready=True)
                return payload
            except Exception as exc:  # noqa: BLE001
                self._last_request_at = time.monotonic()
                last_error = exc
                error_code = self._extract_auth_error_code(str(exc))
                if auth_required and (
                    error_code in _REFRESH_THROTTLED_CODES or error_code in _REFRESH_TOKEN_REAUTH_CODES
                ):
                    self._handle_refresh_error(Client115Error(str(exc)))
                    break
                if (
                    auth_required
                    and self._is_invalid_access_token_error(str(exc))
                    and not refreshed_on_invalid_token
                ):
                    self._record_auth_error(str(exc))
                    if self._refresh_in_cooldown():
                        logger.warning("115 token refresh is in cooldown, skipping refresh attempt")
                        break
                    logger.warning("115 token invalid, attempting refresh…")
                    try:
                        self.refresh_access_token_and_persist()
                    except Client115Error as refresh_exc:
                        self._handle_refresh_error(refresh_exc)
                        if self._auth_status == "cooldown":
                            logger.warning("115 token refresh throttled, cooldown started: %s", refresh_exc)
                        else:
                            raise
                    refreshed_on_invalid_token = True
                    continue
                if auth_required:
                    code = self._extract_auth_error_code(str(exc))
                    if code == "40140126":
                        self._record_auth_error(str(exc), status="reauth_required")
                    else:
                        self._record_auth_error(str(exc))
                if attempt >= retries:
                    break
                time.sleep(backoff * (attempt + 1))

        raise Client115Error(str(last_error) if last_error else "115 request failed")

    # ── Auth / token flows ───────────────────────────────────────────────

    def build_authorize_url(self, state: str = "codex", redirect_uri: str | None = None) -> str:
        if not self.settings.app_id:
            raise Client115Error("APP_ID is not configured")
        resolved_redirect = redirect_uri or self.settings.app_redirect_uri
        if not resolved_redirect:
            raise Client115Error("APP_REDIRECT_URI is not configured")
        payload = self._call(
            lambda: P115OpenClient.login_authorize_open(
                {
                    "client_id": self.settings.app_id,
                    "redirect_uri": resolved_redirect,
                    "response_type": "code",
                    "state": state,
                }
            )
        )
        url = payload.get("url")
        if not url:
            raise Client115Error("115 authorize URL was not returned")
        return str(url)

    def create_device_code(self) -> tuple[DeviceCodePayload, str]:
        """Initiate device-code / QR flow for Open API token acquisition."""
        if not self.settings.app_id:
            raise Client115Error("APP_ID is not configured")
        code_verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        payload = self._call(
            lambda: P115OpenClient.login_qrcode_token_open(
                {
                    "client_id": self.settings.app_id,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "sha256",
                }
            )
        )
        return DeviceCodePayload.model_validate(payload["data"]), code_verifier

    def poll_device_status(self, uid: str, time_value: str | int, sign: str) -> dict:
        return self._call(
            lambda: P115OpenClient.login_qrcode_scan_status(
                {"uid": uid, "time": str(time_value), "sign": sign}
            )
        )

    def exchange_device_code(self, uid: str, code_verifier: str) -> TokenPayload:
        payload = self._call(
            lambda: P115OpenClient.login_qrcode_access_token_open(
                {"uid": uid, "code_verifier": code_verifier}
            )
        )
        return TokenPayload.model_validate(payload["data"])

    def exchange_auth_code(self, code: str, redirect_uri: str | None = None) -> TokenPayload:
        if not self.settings.app_id or not self.settings.app_secret:
            raise Client115Error("APP_ID or APP_SECRET is not configured")
        resolved_redirect = redirect_uri or self.settings.app_redirect_uri
        if not resolved_redirect:
            raise Client115Error("APP_REDIRECT_URI is not configured")
        payload = self._call(
            lambda: P115OpenClient.login_authorize_access_token_open(
                {
                    "client_id": self.settings.app_id,
                    "client_secret": self.settings.app_secret,
                    "code": code,
                    "redirect_uri": resolved_redirect,
                    "grant_type": "authorization_code",
                }
            )
        )
        return TokenPayload.model_validate(payload["data"])

    def refresh_access_token(self, refresh_token: str | None = None) -> TokenPayload:
        token = refresh_token or self.settings.refresh_token
        if not token:
            raise Client115Error("REFRESH_TOKEN is not configured")
        payload = self._call(
            lambda: P115OpenClient.login_refresh_token_open({"refresh_token": token})
        )
        return TokenPayload.model_validate(payload["data"])

    # ── File system operations ───────────────────────────────────────────

    def list_files(self, cid: str = "0", limit: int = 20, offset: int = 0, show_dir: int = 1) -> dict:
        return self._call(
            lambda: self._get_open_client().fs_files(
                {"cid": cid, "limit": limit, "offset": offset, "show_dir": show_dir}
            ),
            auth_required=True,
        )

    @staticmethod
    def _display_path_parts(path: str) -> list[str]:
        cleaned = path.strip().strip("/")
        if not cleaned:
            return []
        parts = [part for part in cleaned.split("/") if part]
        if parts and parts[0] == "根目录":
            parts = parts[1:]
        return parts

    def path_parts_for_display_path(self, path: str) -> list[str]:
        return self._display_path_parts(path)

    def normalize_open_path(self, path: str) -> str:
        parts = self._display_path_parts(path)
        if not parts:
            return "/"
        return "/" + "/".join(parts)

    def build_path_from_paths(self, paths: Iterable[dict], leaf_name: str | None = None) -> str:
        names = [str(item.get("file_name")) for item in paths if item.get("file_name")]
        if leaf_name:
            names.append(leaf_name)
        return "/".join(names)

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        if not file_id and not path:
            raise Client115Error("file_id or path is required")
        if file_id:
            return self._call(
                lambda: self._get_open_client().fs_info({"file_id": file_id}),
                auth_required=True,
            )
        normalized_path = self.normalize_open_path(path or "")
        return self._call(
            lambda: self._get_open_client().fs_info({"path": normalized_path}, method="POST"),
            auth_required=True,
        )

    def get_full_path(self, file_id: str) -> str:
        payload = self.get_file(file_id=file_id)
        data = payload.get("data", {})
        return self.build_path_from_paths(data.get("paths", []), data.get("file_name"))

    def search_nodes(
        self, keyword: str, limit: int = 20, offset: int = 0, folders_only: bool = False
    ) -> list[NodePayload]:
        payload = self._call(
            lambda: self._get_open_client().fs_search(
                {
                    "search_value": keyword,
                    "limit": limit,
                    "offset": offset,
                    "fc": 1 if folders_only else None,
                }
            ),
            auth_required=True,
        )
        nodes: list[NodePayload] = []
        for item in payload.get("data", []):
            file_name = item.get("file_name", "")
            parent_id = item.get("parent_id")
            nodes.append(
                NodePayload(
                    id=str(item.get("file_id")),
                    name=file_name,
                    path=file_name,
                    parent_id=str(parent_id) if parent_id is not None else None,
                    is_file=str(item.get("file_category")) == "1",
                )
            )
        return nodes

    def submit_magnet_download(self, magnet_url: str, target_cid: str | None = None) -> OfflineTaskPayload:
        payload: dict[str, str] = {"urls": magnet_url.strip()}
        resolved_target_cid = target_cid or self.settings.offline_default_target_cid
        if resolved_target_cid:
            payload["wp_path_id"] = resolved_target_cid
        response = self._call(
            lambda: self._get_open_client().offline_add_urls_open(payload),
            auth_required=True,
        )
        data = self._normalize_offline_task_response(response)
        return OfflineTaskPayload(
            task_id=str(data.get("task_id")) if data.get("task_id") is not None else None,
            info_hash=data.get("info_hash"),
            url=data.get("url") or magnet_url,
            name=data.get("name"),
            status=str(data.get("status")) if data.get("status") is not None else None,
        )

    @staticmethod
    def _normalize_offline_task_response(response: dict) -> dict:
        data = response.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    return item
            raise Client115Error("115 offline add returned an empty task list")
        if isinstance(response, dict):
            return response
        raise Client115Error(
            f"115 offline add returned unsupported payload type: {type(response).__name__}"
        )

    def create_folder(self, pid: str, file_name: str) -> ClientActionResult:
        payload = self._call(
            lambda: self._get_open_client().fs_mkdir({"pid": pid, "file_name": file_name}),
            auth_required=True,
        )
        return ClientActionResult(
            success=True, action="create_folder", message="created", payload=payload.get("data")
        )

    def rename_node(self, file_id: str, new_name: str, dry_run: bool = True) -> ClientActionResult:
        if dry_run:
            return ClientActionResult(
                success=True, action="rename", message="dry-run",
                payload={"file_id": file_id, "file_name": new_name},
            )
        payload = self._call(
            lambda: self._get_open_client().fs_rename((file_id, new_name)),
            auth_required=True,
        )
        return ClientActionResult(
            success=True, action="rename", message="renamed", payload=payload.get("data")
        )

    def move_node(self, file_id: str, to_cid: str, dry_run: bool = True) -> ClientActionResult:
        if dry_run:
            return ClientActionResult(
                success=True, action="move", message="dry-run",
                payload={"file_id": file_id, "to_cid": to_cid},
            )
        payload = self._call(
            lambda: self._get_open_client().fs_move({"file_ids": file_id, "to_cid": to_cid}),
            auth_required=True,
        )
        return ClientActionResult(
            success=True, action="move", message="moved", payload={"data": payload.get("data")}
        )

    def batch_move_nodes(self, file_ids: list[str], to_cid: str, dry_run: bool = True) -> list[ClientActionResult]:
        return [self.move_node(file_id=fid, to_cid=to_cid, dry_run=dry_run) for fid in file_ids]

    def delete_node(self, file_id: str, dry_run: bool = True) -> ClientActionResult:
        if dry_run:
            return ClientActionResult(
                success=True, action="delete", message="dry-run", payload={"file_id": file_id}
            )
        payload = self._call(
            lambda: self._get_open_client().fs_delete(file_id),
            auth_required=True,
        )
        return ClientActionResult(
            success=True, action="delete", message="deleted", payload={"data": payload.get("data")}
        )

    def batch_delete_nodes(self, file_ids: list[str], dry_run: bool = True) -> list[ClientActionResult]:
        return [self.delete_node(file_id=fid, dry_run=dry_run) for fid in file_ids]


class Fake115Client:
    """In-memory stub for tests — mirrors Real115Client's public interface."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodePayload] = {}

    def ensure_fresh_access_token(self):
        return None

    def add_node(self, node: NodePayload) -> None:
        self.nodes[node.id] = node

    def list_files(self, cid: str = "0", limit: int = 20, offset: int = 0, show_dir: int = 1) -> dict:
        children = [n for n in self.nodes.values() if (n.parent_id or "0") == cid]
        sliced = children[offset: offset + limit]
        return {
            "state": True,
            "count": len(children),
            "offset": offset,
            "limit": limit,
            "cid": cid,
            "data": [
                {"fid": n.id, "pid": n.parent_id or "0", "fc": "1" if n.is_file else "0", "fn": n.name}
                for n in sliced
            ],
        }

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        node: NodePayload | None = None
        if file_id is not None:
            node = self.nodes.get(file_id)
        elif path is not None:
            normalized = path.strip("/")
            for candidate in self.nodes.values():
                if candidate.path.strip("/") == normalized:
                    node = candidate
                    break
        if node is None:
            raise Client115Error("Node not found")
        parent_segments = node.path.strip("/").split("/")[:-1]
        paths = [{"file_name": seg} for seg in parent_segments]
        return {
            "state": True,
            "data": {
                "file_id": node.id,
                "file_name": node.name,
                "parent_id": node.parent_id,
                "file_category": "1" if node.is_file else "0",
                "paths": paths,
            },
        }

    def get_full_path(self, file_id: str) -> str:
        return self.nodes[file_id].path

    def search_nodes(self, keyword: str, limit: int = 20, offset: int = 0, folders_only: bool = False) -> list[NodePayload]:
        keyword = keyword.lower()
        results = [n for n in self.nodes.values() if keyword in n.name.lower() or keyword in n.path.lower()]
        if folders_only:
            results = [n for n in results if not n.is_file]
        return results[offset: offset + limit]

    def submit_magnet_download(self, magnet_url: str, target_cid: str | None = None) -> OfflineTaskPayload:
        return OfflineTaskPayload(task_id="fake-task-1", info_hash=None, url=magnet_url, name=None, status="submitted")

    def create_folder(self, pid: str, file_name: str) -> ClientActionResult:
        new_id = str(len(self.nodes) + 1)
        parent_path = "" if pid == "0" else self.nodes[pid].path
        path = f"{parent_path}/{file_name}".strip("/")
        self.nodes[new_id] = NodePayload(id=new_id, name=file_name, path=path, parent_id=None if pid == "0" else pid, is_file=False)
        return ClientActionResult(success=True, action="create_folder", message="created", payload={"file_id": new_id, "file_name": file_name})

    def rename_node(self, file_id: str, new_name: str, dry_run: bool = True) -> ClientActionResult:
        node = self.nodes[file_id]
        if dry_run:
            return ClientActionResult(success=True, action="rename", message="dry-run", payload=node.model_dump())
        prefix = node.path[: -len(node.name)] if len(node.name) <= len(node.path) else ""
        node.path = f"{prefix}{new_name}".strip("/")
        node.name = new_name
        return ClientActionResult(success=True, action="rename", message="renamed", payload=node.model_dump())

    def move_node(self, file_id: str, to_cid: str, dry_run: bool = True) -> ClientActionResult:
        node = self.nodes[file_id]
        if dry_run:
            return ClientActionResult(success=True, action="move", message="dry-run", payload=node.model_dump())
        parent_path = "" if to_cid == "0" else self.nodes[to_cid].path
        node.path = f"{parent_path}/{node.name}".strip("/")
        node.parent_id = None if to_cid == "0" else to_cid
        return ClientActionResult(success=True, action="move", message="moved", payload=node.model_dump())

    def batch_move_nodes(self, file_ids: list[str], to_cid: str, dry_run: bool = True) -> list[ClientActionResult]:
        return [self.move_node(file_id=fid, to_cid=to_cid, dry_run=dry_run) for fid in file_ids]

    def delete_node(self, file_id: str, dry_run: bool = True) -> ClientActionResult:
        node = self.nodes[file_id]
        if dry_run:
            return ClientActionResult(success=True, action="delete", message="dry-run", payload=node.model_dump())
        del self.nodes[file_id]
        return ClientActionResult(success=True, action="delete", message="deleted", payload={"file_id": file_id})

    def batch_delete_nodes(self, file_ids: list[str], dry_run: bool = True) -> list[ClientActionResult]:
        return [self.delete_node(file_id=fid, dry_run=dry_run) for fid in file_ids]
