from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx


class DownloaderRemoteError(RuntimeError):
    """RN 下载器返回不可用或拒绝请求时的安全错误。"""

    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DownloaderClient:
    """调用 RN 下载器 Web API 的短生命周期客户端。"""

    settings: Any
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None

    @property
    def base_url(self) -> str:
        return str(getattr(self.settings, "downloader_base_url", "")).rstrip("/")

    @property
    def password(self) -> str:
        return str(getattr(self.settings, "downloader_password", "") or "")

    @property
    def timeout(self) -> float:
        return float(getattr(self.settings, "downloader_timeout_seconds", 10.0) or 10.0)

    def _client(self) -> httpx.Client:
        if not self.base_url:
            raise DownloaderRemoteError("not_configured", "下载器地址未配置")
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise DownloaderRemoteError("invalid_response", "下载器返回格式无效", status_code=response.status_code) from exc
        if not isinstance(payload, dict):
            raise DownloaderRemoteError("invalid_response", "下载器返回格式无效", status_code=response.status_code)
        return payload

    def health(self) -> dict[str, Any]:
        with self._client() as client:
            try:
                response = client.get("/healthz")
            except httpx.HTTPError as exc:
                raise DownloaderRemoteError("unreachable", "下载器无法连接") from exc
        if response.status_code >= 400:
            raise DownloaderRemoteError("not_ready", "下载器尚未就绪", status_code=response.status_code)
        return self._json(response)

    def _authenticated(self) -> tuple[httpx.Client, str]:
        client = self._client()
        try:
            response = client.post("/login", data={"password": self.password})
        except httpx.HTTPError as exc:
            client.close()
            raise DownloaderRemoteError("unreachable", "下载器无法连接") from exc
        payload = self._json(response)
        if response.status_code >= 400 or str(payload.get("code")) != "1":
            client.close()
            raise DownloaderRemoteError("authentication_failed", "下载器认证失败", status_code=response.status_code)
        try:
            csrf_response = client.get("/api/csrf-token")
        except httpx.HTTPError as exc:
            client.close()
            raise DownloaderRemoteError("unreachable", "下载器无法连接") from exc
        csrf_payload = self._json(csrf_response)
        csrf = csrf_payload.get("csrf_token")
        if csrf_response.status_code >= 400 or not isinstance(csrf, str) or not csrf:
            client.close()
            raise DownloaderRemoteError("csrf_failed", "下载器 CSRF 会话初始化失败", status_code=csrf_response.status_code)
        return client, csrf

    def _authenticated_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        client, csrf = self._authenticated()
        try:
            request_headers = {"X-CSRF-Token": csrf, **(headers or {})}
            try:
                response = client.request(method, path, params=params, headers=request_headers)
            except httpx.HTTPError as exc:
                raise DownloaderRemoteError("unreachable", "下载器无法连接") from exc
            payload = self._json(response)
            if response.status_code >= 400:
                code = str(payload.get("error_code") or "remote_error")
                message = str(payload.get("message") or "下载器拒绝了请求")
                raise DownloaderRemoteError(code, message, status_code=response.status_code)
            return payload
        finally:
            client.close()

    def list_packages(self, *, cursor: str | None = None, page_size: int = 200) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": max(1, min(int(page_size), 200))}
        if cursor:
            params["cursor"] = cursor
        return self._authenticated_request("GET", "/api/packages", params=params)

    def list_tasks(self) -> list[dict[str, Any]]:
        payload = self._authenticated_request("GET", "/api/tasks")
        items = payload.get("items", payload)
        if not isinstance(items, list):
            raise DownloaderRemoteError("invalid_response", "下载器任务列表格式无效")
        return [item for item in items if isinstance(item, dict)]

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._authenticated_request("GET", f"/api/tasks/{task_id}")

    def get_dashboard(self) -> dict[str, Any]:
        return self._authenticated_request("GET", "/api/task-dashboard")

    def submit_package(self, package_id: int, idempotency_key: str) -> dict[str, Any]:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        return self._authenticated_request(
            "POST",
            f"/api/packages/{int(package_id)}/download-batch",
            headers={"Idempotency-Key": idempotency_key},
        )

    def set_download_state(self, state: Literal["pause", "resume"]) -> dict[str, Any]:
        remote_state = "pause" if state == "pause" else "continue"
        return self._authenticated_request("POST", "/set_download_state", params={"state": remote_state})

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self._authenticated_request("POST", f"/api/tasks/{task_id}/cancel")

    def retry_task(self, task_id: str) -> dict[str, Any]:
        return self._authenticated_request("POST", f"/api/tasks/{task_id}/retry")
