"""删完 115 文件后刷新 OpenList 的目录缓存。

OpenList 的目录列表有缓存，不请求那个目录就不会刷新；alist-strm 按旧列表生成 STRM 时，
刚删掉的片子会「删了又回来」。做法照搬 strmallinone / strm_webhook：列目录时带 refresh=true。
"""

from __future__ import annotations

import os

import httpx

from app.services.emby_media_actions.strm_mapping_service import decode_115_open_path


class OpenListError(RuntimeError):
    """刷新没成功（网络、鉴权、接口报错），只记在删除记录上，不影响删除结果。"""


def openlist_dir_for(url: str) -> str:
    """STRM 里的 OpenList 地址 → 这个文件在 OpenList 里所在目录，如 /115_OPEN/AV。

    不是 /d/115_OPEN/ 地址时抛 ValueError。
    """
    decoded = decode_115_open_path(url)
    return f"/{decoded.mount_name}{os.path.dirname(decoded.remote_path)}".rstrip("/")


class OpenListClient:
    """只用到「强制刷新列目录」这一个接口。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    def refresh_dir(self, path: str) -> None:
        """强制刷新 OpenList 里一个目录的缓存；任何失败都抛 OpenListError。"""
        payload = {"path": path, "refresh": True, "password": "", "page": 1, "per_page": 0}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(
                    f"{self.base_url}/api/fs/list",
                    headers={"Authorization": self._token},
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenListError(f"OpenList 刷新失败：{path}：{exc}") from exc
        if not isinstance(body, dict) or body.get("code") != 200:
            message = body.get("message") if isinstance(body, dict) else body
            raise OpenListError(f"OpenList 刷新失败：{path}：{message}")
