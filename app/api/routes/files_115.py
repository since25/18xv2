"""
115 文件元信息查询路由。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/115", tags=["115"])


class FileInfoRequest(BaseModel):
    cids: list[str]


class FileInfoItem(BaseModel):
    size: int | None = None
    modified_at: str | None = None  # ISO 8601 字符串或原始值
    error: str | None = None


class FileInfoResponse(BaseModel):
    results: dict[str, FileInfoItem]


@router.post("/file-info", response_model=FileInfoResponse)
def get_file_info(body: FileInfoRequest, request: Request) -> FileInfoResponse:
    """批量查询 115 文件元信息，每个 cid 独立处理，单个失败不中断其余请求。"""
    client_115 = getattr(request.app.state, "client_115", None)
    results: dict[str, FileInfoItem] = {}

    if client_115 is None:
        # client 未初始化，所有 cid 返回错误
        for cid in body.cids:
            results[cid] = FileInfoItem(error="115 client 未初始化")
        return FileInfoResponse(results=results)

    for cid in body.cids:
        try:
            data = client_115.get_file_info(file_id=cid)
            size = data.get("file_size") if isinstance(data, dict) else None
            utime = data.get("utime") if isinstance(data, dict) else None
            results[cid] = FileInfoItem(
                size=size,
                modified_at=str(utime) if utime is not None else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_file_info 失败，cid=%s: %s", cid, exc)
            results[cid] = FileInfoItem(error=str(exc))

    return FileInfoResponse(results=results)
