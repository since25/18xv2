from __future__ import annotations

import time
from typing import Any, Callable, Iterator

import httpx


class JellyfinError(Exception):
    """Jellyfin 请求或返回结果不可用时抛出的错误。"""


class JellyfinClient:
    """Jellyfin API 的短生命周期同步客户端。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float,
        page_size: int,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.page_size = max(1, int(page_size))
        self.transport = transport
        self._sleep = sleep_fn or time.sleep
        self._session: httpx.Client | None = None
        self._admin_user_id: str | None = None

    def __enter__(self) -> "JellyfinClient":
        self._session = self._new_session()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """关闭上下文中复用的 HTTP 客户端。"""
        if self._session is not None:
            self._session.close()
            self._session = None

    def _new_session(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Authorization": f'MediaBrowser Token="{self.api_key}"'},
            transport=self.transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """发起请求，连接错误、429 和 5xx 最多重试三次。"""
        for attempt in range(4):
            owned = self._session is None
            session = self._session or self._new_session()
            try:
                try:
                    response = session.request(method, path, params=params, json=json)
                except httpx.RequestError as exc:
                    if attempt < 3:
                        self._sleep(2**attempt)
                        continue
                    raise JellyfinError("Jellyfin 连接失败") from exc

                retryable = response.status_code == 429 or response.status_code >= 500
                if response.status_code < 400:
                    return response
                if retryable and attempt < 3:
                    self._sleep(2**attempt)
                    continue
                raise JellyfinError(f"Jellyfin 请求失败（HTTP {response.status_code}）")
            finally:
                if owned:
                    session.close()
        raise JellyfinError("Jellyfin 请求失败")

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise JellyfinError("Jellyfin 返回格式无效") from exc
        if not isinstance(payload, dict):
            raise JellyfinError("Jellyfin 返回对象格式无效")
        return payload

    @staticmethod
    def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("Items", payload.get("items", []))
        if not isinstance(items, list):
            raise JellyfinError("Jellyfin 列表格式无效")
        return [item for item in items if isinstance(item, dict)]

    def iter_media_paths(self) -> Iterator[tuple[str, str]]:
        """分页读取所有媒体路径和 Jellyfin 条目 ID。"""
        start_index = 0
        while True:
            response = self._request(
                "GET",
                "/Items",
                params={
                    "Recursive": "true",
                    "IsFolder": "false",
                    "Fields": "Path",
                    "StartIndex": start_index,
                    "Limit": self.page_size,
                },
            )
            payload = self._payload(response)
            items = self._items(payload)
            for item in items:
                path = item.get("Path", item.get("path"))
                item_id = item.get("Id", item.get("id"))
                if isinstance(path, str) and isinstance(item_id, str):
                    yield path, item_id

            start_index += len(items)
            total = payload.get("TotalRecordCount", payload.get("totalRecordCount"))
            if not items:
                break
            if total is not None:
                try:
                    if start_index >= int(total):
                        break
                except (TypeError, ValueError):
                    pass
            elif len(items) < self.page_size:
                break

    def list_collections(self) -> list[dict]:
        """列出 Jellyfin 中的 BoxSet 合集及其标签。"""
        response = self._request(
            "GET",
            "/Items",
            params={"IncludeItemTypes": "BoxSet", "Recursive": "true", "Fields": "Tags"},
        )
        items = self._items(self._payload(response))
        collections: list[dict] = []
        for item in items:
            item_id = item.get("Id", item.get("id"))
            name = item.get("Name", item.get("name"))
            tags = item.get("Tags", item.get("tags", []))
            if not isinstance(item_id, str) or not isinstance(name, str):
                continue
            if not isinstance(tags, list):
                tags = []
            collections.append({"id": item_id, "name": name, "tags": [str(tag) for tag in tags]})
        return collections

    def get_collection_item_ids(self, collection_id: str) -> set[str]:
        """分页读取合集的成员 ID。"""
        start_index = 0
        item_ids: set[str] = set()
        # Jellyfin 10.10 不指定用户时合集成员为空
        user_id = self._get_admin_user_id()
        while True:
            response = self._request(
                "GET",
                "/Items",
                params={"ParentId": collection_id, "userId": user_id, "StartIndex": start_index, "Limit": self.page_size},
            )
            payload = self._payload(response)
            items = self._items(payload)
            for item in items:
                item_id = item.get("Id", item.get("id"))
                if isinstance(item_id, str):
                    item_ids.add(item_id)
            start_index += len(items)
            total = payload.get("TotalRecordCount", payload.get("totalRecordCount"))
            if not items:
                break
            if total is not None:
                try:
                    if start_index >= int(total):
                        break
                except (TypeError, ValueError):
                    pass
            elif len(items) < self.page_size:
                break
        return item_ids

    @staticmethod
    def _chunks(item_ids: list[str], size: int = 100) -> Iterator[list[str]]:
        for index in range(0, len(item_ids), size):
            yield item_ids[index : index + size]

    def create_collection(self, name: str, item_ids: list[str]) -> str:
        """创建合集并返回新合集 ID；成员分批写入，避免请求地址超长。"""
        first_batch = item_ids[:100]
        response = self._request("POST", "/Collections", params={"Name": name, "Ids": ",".join(first_batch)})
        payload = self._payload(response) if response.content else {}
        collection_id = payload.get("Id", payload.get("id", payload.get("CollectionId")))
        if not isinstance(collection_id, str):
            collection_id = response.headers.get("Location", "").rstrip("/").split("/")[-1]
        if not collection_id:
            raise JellyfinError("Jellyfin 创建合集未返回 ID")
        self.add_to_collection(collection_id, item_ids[100:])
        return collection_id

    def add_to_collection(self, collection_id: str, item_ids: list[str]) -> None:
        """分批向合集添加成员，每批最多 100 个。"""
        for chunk in self._chunks(item_ids):
            self._request("POST", f"/Collections/{collection_id}/Items", params={"Ids": ",".join(chunk)})

    def remove_from_collection(self, collection_id: str, item_ids: list[str]) -> None:
        """分批从合集移除成员，每批最多 100 个。"""
        for chunk in self._chunks(item_ids):
            self._request("DELETE", f"/Collections/{collection_id}/Items", params={"Ids": ",".join(chunk)})

    def _get_admin_user_id(self) -> str:
        """取管理员用户 ID：Jellyfin 10.10 用 API Key 读单个条目和合集成员时必须指定用户。"""
        if self._admin_user_id is None:
            response = self._request("GET", "/Users")
            try:
                users = response.json()
            except ValueError as exc:
                raise JellyfinError("Jellyfin 返回格式无效") from exc
            if not isinstance(users, list):
                raise JellyfinError("Jellyfin 用户列表格式无效")
            for user in users:
                if isinstance(user, dict) and (user.get("Policy") or {}).get("IsAdministrator") and isinstance(user.get("Id"), str):
                    self._admin_user_id = user["Id"]
                    break
            if self._admin_user_id is None:
                raise JellyfinError("Jellyfin 没有可用的管理员用户")
        return self._admin_user_id

    def set_name_and_tags(self, collection_id: str, name: str, tags: list[str]) -> None:
        """读取合集完整对象后更新名称和标签。"""
        response = self._request("GET", f"/Items/{collection_id}", params={"userId": self._get_admin_user_id()})
        payload = self._payload(response)
        payload["Name"] = name
        payload["Tags"] = tags
        self._request("POST", f"/Items/{collection_id}", json=payload)

    def delete_item(self, collection_id: str) -> None:
        """删除一个 Jellyfin 合集。"""
        self._request("DELETE", f"/Items/{collection_id}")
