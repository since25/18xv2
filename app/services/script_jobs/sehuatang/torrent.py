"""从种子文件里取出文件和目录名（最小 bencode 解析，不加依赖）。"""

from __future__ import annotations


class TorrentParseError(ValueError):
    """不是合法的种子文件。"""


def _decode(data: bytes, index: int):
    if index >= len(data):
        raise TorrentParseError("种子数据意外结束")
    marker = data[index : index + 1]
    if marker == b"i":
        end = data.find(b"e", index)
        if end < 0:
            raise TorrentParseError("整数未结束")
        try:
            return int(data[index + 1 : end]), end + 1
        except ValueError as exc:
            raise TorrentParseError("整数格式错误") from exc
    if marker == b"l":
        index += 1
        items = []
        while data[index : index + 1] != b"e":
            item, index = _decode(data, index)
            items.append(item)
        return items, index + 1
    if marker == b"d":
        index += 1
        result = {}
        while data[index : index + 1] != b"e":
            key, index = _decode(data, index)
            if not isinstance(key, bytes):
                raise TorrentParseError("字典键必须是字符串")
            value, index = _decode(data, index)
            result[key] = value
        return result, index + 1
    if marker.isdigit():
        colon = data.find(b":", index)
        if colon < 0:
            raise TorrentParseError("字符串长度未结束")
        try:
            length = int(data[index:colon])
        except ValueError as exc:
            raise TorrentParseError("字符串长度格式错误") from exc
        start = colon + 1
        if start + length > len(data):
            raise TorrentParseError("字符串超出数据长度")
        return data[start : start + length], start + length
    raise TorrentParseError("无法识别的 bencode 数据")


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def list_names(data: bytes) -> list[str]:
    """返回种子名，以及多文件种子里每个文件的相对路径（优先 utf-8 字段）。"""
    if not data or data[:1] != b"d":
        raise TorrentParseError("不是种子文件")
    try:
        root, _ = _decode(data, 0)
    except IndexError as exc:
        raise TorrentParseError("种子数据意外结束") from exc
    info = root.get(b"info") if isinstance(root, dict) else None
    if not isinstance(info, dict):
        raise TorrentParseError("种子缺少 info")
    names = [_text(info.get(b"name.utf-8", info.get(b"name", b"")))]
    for entry in info.get(b"files", []) or []:
        if not isinstance(entry, dict):
            continue
        parts = entry.get(b"path.utf-8", entry.get(b"path", []))
        if isinstance(parts, list):
            names.append("/".join(_text(part) for part in parts))
    return [name for name in names if name]
