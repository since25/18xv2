from __future__ import annotations

import base64
import time
from typing import Any, Callable, Iterator, Sequence
from urllib.parse import quote

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
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> httpx.Response:
        """发起请求，连接错误、429 和 5xx 最多重试三次；allow_404 时 404 原样返回给调用方判断。"""
        for attempt in range(4):
            owned = self._session is None
            session = self._session or self._new_session()
            try:
                try:
                    response = session.request(
                        method, path, params=params, json=json, content=content, headers=headers
                    )
                except httpx.RequestError as exc:
                    if attempt < 3:
                        self._sleep(2**attempt)
                        continue
                    raise JellyfinError("Jellyfin 连接失败") from exc

                retryable = response.status_code == 429 or response.status_code >= 500
                if response.status_code < 400 or (allow_404 and response.status_code == 404):
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

    def _iter_media_pages(self, fields: str, *, parent_id: str | None = None) -> Iterator[dict[str, Any]]:
        """分页读取非文件夹条目，逐个返回原始条目对象；给了 parent_id 时只读这个库或合集。"""
        params: dict[str, Any] = {"Recursive": "true", "IsFolder": "false", "Fields": fields}
        if parent_id:
            # Jellyfin 10.10 用 API Key 按上级读取时要带用户，否则合集成员为空
            params["ParentId"] = parent_id
            params["userId"] = self._get_admin_user_id()
        start_index = 0
        while True:
            response = self._request(
                "GET",
                "/Items",
                params={**params, "StartIndex": start_index, "Limit": self.page_size},
            )
            payload = self._payload(response)
            items = self._items(payload)
            yield from items

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

    def iter_media_paths(self) -> Iterator[tuple[str, str]]:
        """分页读取所有媒体路径和 Jellyfin 条目 ID。"""
        for item in self._iter_media_pages("Path"):
            path = item.get("Path", item.get("path"))
            item_id = item.get("Id", item.get("id"))
            if isinstance(path, str) and isinstance(item_id, str):
                yield path, item_id

    def find_library_id(self, locations: Sequence[str]) -> str | None:
        """按媒体库的文件夹位置找库 ID；找不到时返回 None。"""
        wanted = {location.rstrip("/") for location in locations if location and location.rstrip("/")}
        response = self._request("GET", "/Library/VirtualFolders")
        try:
            libraries = response.json()
        except ValueError as exc:
            raise JellyfinError("Jellyfin 返回格式无效") from exc
        if not isinstance(libraries, list):
            raise JellyfinError("Jellyfin 媒体库列表格式无效")
        for library in libraries:
            if not isinstance(library, dict):
                continue
            library_locations = {str(path).rstrip("/") for path in library.get("Locations") or []}
            library_id = library.get("ItemId")
            if wanted & library_locations and isinstance(library_id, str):
                return library_id
        return None

    def iter_collection_media_items(self, collection_id: str) -> Iterator[dict[str, Any]]:
        """读取一个合集成员的 ID、路径、名字、锁定字段和强制排序名。"""
        return self.iter_media_items(parent_id=collection_id)

    def iter_media_items(self, parent_id: str | None = None) -> Iterator[dict[str, Any]]:
        """分页读取条目的 ID、路径、名字、锁定字段和强制排序名；返回里没有的为 None。

        parent_id 为媒体库或合集 ID 时只读它下面的条目，为 None 时读全部。
        """
        # Fields=Settings 才返回 LockedFields，Fields=SortName 才返回 ForcedSortName（10.10.7 实测，未设置时不返回该键）
        for item in self._iter_media_pages("Path,Settings,SortName", parent_id=parent_id):
            path = item.get("Path", item.get("path"))
            item_id = item.get("Id", item.get("id"))
            if not isinstance(path, str) or not isinstance(item_id, str):
                continue
            name = item.get("Name", item.get("name"))
            locked = item.get("LockedFields", item.get("lockedFields"))
            sort_name = item.get("ForcedSortName", item.get("forcedSortName"))
            yield {
                "id": item_id,
                "path": path,
                "name": name if isinstance(name, str) else "",
                "locked_fields": [str(field) for field in locked] if isinstance(locked, list) else None,
                "sort_name": sort_name if isinstance(sort_name, str) and sort_name else None,
            }

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

    def _get_item_as_admin(self, item_id: str) -> dict[str, Any]:
        """以管理员身份读取单个条目的完整对象，供改写后整体提交。"""
        response = self._request("GET", f"/Items/{item_id}", params={"userId": self._get_admin_user_id()})
        return self._payload(response)

    def set_item_name(self, item_id: str, name: str, *, sort_name: str | None = None, lock: bool = True) -> None:
        """改条目显示名和强制排序名（None 表示清掉，按名字自动排序）；
        lock=True 时锁定名字防止重扫改回，lock=False 时解锁（回滚用）。"""
        payload = self._get_item_as_admin(item_id)
        payload["Name"] = name
        payload["ForcedSortName"] = sort_name
        locked = payload.get("LockedFields")
        locked = [str(field) for field in locked] if isinstance(locked, list) else []
        if lock and "Name" not in locked:
            locked.append("Name")
        if not lock:
            locked = [field for field in locked if field != "Name"]
        payload["LockedFields"] = locked
        self._request("POST", f"/Items/{item_id}", json=payload)

    def ensure_sort_name_order(self, collection_id: str) -> bool:
        """把合集设为按名字排序；已经是则不写，返回是否改动。"""
        payload = self._get_item_as_admin(collection_id)
        if payload.get("DisplayOrder") == "SortName":
            return False
        payload["DisplayOrder"] = "SortName"
        self._request("POST", f"/Items/{collection_id}", json=payload)
        return True

    def delete_item(self, collection_id: str) -> None:
        """删除一个 Jellyfin 合集。"""
        self._request("DELETE", f"/Items/{collection_id}")

    def refresh_library(self, library_id: str) -> None:
        """扫描媒体库里新增和更新的文件（即界面里的「扫描新增和更新的文件」）。

        不做全量刷新：元数据和图片都用 Default 模式，不替换已有元数据和图片。
        """
        self._request(
            "POST",
            f"/Items/{library_id}/Refresh",
            params={
                "Recursive": "true",
                "MetadataRefreshMode": "Default",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": "false",
                "ReplaceAllImages": "false",
            },
        )

    def get_person(self, name: str) -> dict[str, Any] | None:
        """按人名查 Jellyfin 人物，返回 {"id", "has_primary"}；人物不存在或没有 Id 时返回 None，其他错误照常抛。"""
        response = self._request("GET", f"/Persons/{quote(name, safe='')}", allow_404=True)
        if response.status_code == 404:
            return None
        payload = self._payload(response)
        person_id = payload.get("Id")
        if not isinstance(person_id, str) or not person_id:
            return None
        image_tags = payload.get("ImageTags") or {}
        return {"id": person_id, "has_primary": bool(isinstance(image_tags, dict) and image_tags.get("Primary"))}

    def upload_person_image(self, person_id: str, content: bytes, content_type: str) -> None:
        """把图片设为人物主图；Jellyfin 要求请求体是图片的 base64、Content-Type 是图片类型。"""
        self._request(
            "POST",
            f"/Items/{person_id}/Images/Primary",
            content=base64.b64encode(content),
            headers={"Content-Type": content_type},
        )

    def get_person_image(self, name: str) -> tuple[bytes, str] | None:
        """按人名取 Jellyfin 人物主图，返回（内容, Content-Type）。

        人物不存在、返回里没有 Id、没有主图或请求失败时返回 None，不抛错。
        """
        try:
            # 名字整体编码，含斜杠或空格时也不会拆开路径
            response = self._request("GET", f"/Persons/{quote(name, safe='')}")
            person_id = self._payload(response).get("Id")
            if not isinstance(person_id, str) or not person_id:
                return None
            image = self._request("GET", f"/Items/{person_id}/Images/Primary")
        except JellyfinError:
            return None
        return image.content, image.headers.get("Content-Type", "application/octet-stream")
