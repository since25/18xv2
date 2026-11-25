"""sehuatang 测试用的最小页面和种子构造。标题全部虚构。"""

from __future__ import annotations


def bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted((key.encode() if isinstance(key, str) else key, item) for key, item in value.items())
        return b"d" + b"".join(bencode(key) + bencode(item) for key, item in items) + b"e"
    raise TypeError(type(value))


def single_file_torrent(name: str) -> bytes:
    return bencode({"announce": "http://tracker.invalid/a", "info": {"name": name, "length": 10, "piece length": 16384}})


def multi_file_torrent(name: str, paths: list[list[str]]) -> bytes:
    files = [{"length": 1, "path": path} for path in paths]
    return bencode({"info": {"name": name, "files": files, "piece length": 16384}})


def list_page(posts: list[tuple[str, str]]) -> str:
    """posts: [(tid, 标题)]，生成带 a.s.xst 链接的列表页。"""
    rows = "".join(
        f'<tr><th><a href="thread-{tid}-1-1.html" class="s xst">{title}</a></th></tr>' for tid, title in posts
    )
    return f"<html><body><table>{rows}</table></body></html>"


def thread_page(*, magnets: list[str] = (), attachments: list[tuple[str, str]] = ()) -> str:
    """attachments: [(href, 链接文字)]。"""
    magnet_text = "".join(f"<p>{magnet}</p>" for magnet in magnets)
    links = "".join(f'<a href="{href}">{text}</a>' for href, text in attachments)
    return f"<html><body><div>{magnet_text}{links}</div></body></html>"
