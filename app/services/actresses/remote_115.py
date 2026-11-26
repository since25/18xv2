"""把 STRM 里的 115_OPEN 地址解析成 115 上的文件。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.client_115.client import Client115Error, Fake115Client, Real115Client
from app.services.emby_media_actions.strm_mapping_service import decode_115_open_path

# 115 对不存在路径的报错只认错误码 430004（「文件（夹）不存在或已删除。」，2026-11-26 只读核实）。
# 不认裸的「不存在」：鉴权类报错（如令牌不存在）也可能带这几个字；也不认英文 not found（接口地址错误等）。
# 误判成「已不存在」会让本地文件被删而 115 原文件还在，所以认不出来的一律当 error（这部片什么都不删）。
MISSING_ERROR_CODE = re.compile(r"(?<!\d)430004(?!\d)")


@dataclass
class Remote115:
    """一个 STRM 地址在 115 上的解析结果。"""

    # found（拿到 file_id）/ missing（115 上已不存在）/ error（解析失败，不能删）
    state: str
    file_id: str | None = None
    remote_path: str | None = None
    note: str | None = None


def resolve_115(client: Real115Client | Fake115Client, url: str) -> Remote115:
    """解析地址并按路径查 115 文件；只有确认是文件才算 found。"""
    try:
        remote_path = decode_115_open_path(url).remote_path
    except ValueError:
        return Remote115(state="error", note="不是 115_OPEN 地址")

    try:
        payload = client.get_file(path=remote_path)
    except Client115Error as exc:
        text = str(exc)
        if MISSING_ERROR_CODE.search(text):
            return Remote115(state="missing", remote_path=remote_path, note=f"115 上已不存在：{text}")
        return Remote115(state="error", remote_path=remote_path, note=f"115 查询失败：{text}")
    except Exception as exc:  # noqa: BLE001 — 任何其他异常都只记失败，不当成已不存在
        return Remote115(state="error", remote_path=remote_path, note=f"115 查询失败：{exc}")

    data = payload.get("data") if isinstance(payload, dict) else None
    # 目录还在、文件已没了时 115 不报错，返回成功和空结果（2026-11-26 只读核实）
    if isinstance(payload, dict) and payload.get("state") is True and not data:
        return Remote115(state="missing", remote_path=remote_path, note="115 上已不存在：按路径查询返回空结果")
    file_id = str(data.get("file_id") or "") if isinstance(data, dict) else ""
    if not file_id:
        return Remote115(state="error", remote_path=remote_path, note="115 没有返回 file_id")
    # file_category：1 文件、0 文件夹；不是文件就不能交给删除
    if str(data.get("file_category")) != "1":
        return Remote115(state="error", remote_path=remote_path, note="115 上这个路径不是文件")
    return Remote115(state="found", file_id=file_id, remote_path=remote_path)
