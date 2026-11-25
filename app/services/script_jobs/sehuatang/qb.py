"""qBittorrent WebAPI：登录后用接口提交种子或磁力（不再往监视目录放文件）。

报错信息只含状态码和响应开头，不含请求内容和密码。
"""

from __future__ import annotations

import httpx


class QbError(RuntimeError):
    """qB 登录、连接或提交失败。"""


class QbClient:
    def __init__(self, base_url: str, username: str, password: str, *, transport: httpx.BaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = httpx.Client(
            base_url=self._base_url,
            transport=transport,
            timeout=30,
            headers={"Referer": self._base_url},
        )

    def _post(self, path: str, **kwargs) -> httpx.Response:
        try:
            return self._client.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise QbError(f"qB 连接失败（{type(exc).__name__}）") from None

    def login(self) -> None:
        response = self._post("/api/v2/auth/login", data={"username": self._username, "password": self._password})
        if response.status_code != 200 or response.text.strip() != "Ok.":
            raise QbError(f"qB 登录失败（HTTP {response.status_code}）")

    def _check(self, response: httpx.Response) -> None:
        body = response.text.strip()
        if response.status_code != 200 or body != "Ok.":
            raise QbError(f"qB 拒收（HTTP {response.status_code}：{body[:50]}）")

    def add_torrent(self, data: bytes, filename: str, category: str) -> None:
        response = self._post(
            "/api/v2/torrents/add",
            files={"torrents": (filename, data, "application/x-bittorrent")},
            data={"category": category},
        )
        self._check(response)

    def add_magnets(self, urls: list[str], category: str) -> None:
        response = self._post("/api/v2/torrents/add", data={"urls": "\n".join(urls), "category": category})
        self._check(response)
