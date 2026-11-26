"""Gfriends 头像库：索引缓存、按名字找图、MDC 演员对照表和图片下载。

Gfriends 索引 Filetree.json 的结构是 {"Content": {来源目录: {"日文名.jpg": "实际文件名?t=时间戳"}}}，
图片地址是 <BASE>/Content/<来源目录>/<实际文件名>。只按完整名字精确匹配，不做模糊匹配，避免贴错人。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import httpx

GFRIENDS_BASE = "https://raw.githubusercontent.com/gfriends/gfriends/master"
FILETREE_URL = f"{GFRIENDS_BASE}/Filetree.json"

_STRIP = re.compile(r"[\s・･·（）()\[\]【】]")
_NUMBER_SUFFIX = re.compile(r"-\d+$")
_BRACKETED = re.compile(r"^(.+?)（(.+)）$")


class GfriendsError(RuntimeError):
    """索引或图片拿不到、不是图片、太大等。"""


def normalize_gfriends_name(name: str) -> str:
    """去掉空白、间隔号和各种括号，再统一小写。"""
    return _STRIP.sub("", name or "").lower()


def _display_variants(display: str) -> list[str]:
    """一个文件显示名的几种写法：原名、去掉末尾 -数字、「A（B）」里的 A 和 B。"""
    variants = [display, _NUMBER_SUFFIX.sub("", display)]
    bracketed = _BRACKETED.match(display)
    if bracketed:
        variants += [bracketed.group(1), bracketed.group(2)]
    return variants


class GfriendsIndex:
    """归一化名 → 「<来源目录>/<实际文件名>」。"""

    def __init__(self, lookup: dict[str, str], name_map: dict[str, str] | None) -> None:
        self._lookup = lookup
        self._name_map = name_map or {}
        self.used_name_map = bool(name_map)

    @classmethod
    def from_filetree(cls, filetree: dict, name_map: dict[str, str] | None = None) -> "GfriendsIndex":
        """同一个名字出现在多个来源目录时，取来源目录名排序最小的那个，保证每次结果一样。"""
        content = filetree.get("Content") or {}
        lookup: dict[str, str] = {}
        for folder in sorted(content):
            files = content[folder]
            if not isinstance(files, dict):
                continue
            for key, actual in files.items():
                file_name = str(actual).split("?", 1)[0]
                display = re.sub(r"\.jpg$", "", key, flags=re.IGNORECASE)
                for variant in _display_variants(display):
                    normalized = normalize_gfriends_name(variant)
                    if normalized:
                        lookup.setdefault(normalized, f"{folder}/{file_name}")
        return cls(lookup, name_map)

    def find(self, names: list[str]) -> str | None:
        """按顺序逐个名字查：先直接查，再经对照表换成日文名查；第一个命中就返回。"""
        for name in names:
            normalized = normalize_gfriends_name(name)
            if not normalized:
                continue
            hit = self._lookup.get(normalized)
            if hit is None and normalized in self._name_map:
                hit = self._lookup.get(normalize_gfriends_name(self._name_map[normalized]))
            if hit is not None:
                return hit
        return None


def load_name_map(path: str | None) -> dict[str, str] | None:
    """读 MDC 的 mapping_actor.xml：keyword / zh_cn / zh_tw 里每个名字 → jp 原文。

    路径为空、文件读不了或不是合法 XML 时返回 None（只按原名匹配），不抛错。
    """
    if not path:
        return None
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    name_map: dict[str, str] = {}
    for row in root.iter("a"):
        jp = (row.get("jp") or "").strip()
        if not jp:
            continue
        names = (row.get("keyword") or "").split(",") + [row.get("zh_cn") or "", row.get("zh_tw") or ""]
        for name in names:
            normalized = normalize_gfriends_name(name)
            if normalized:
                name_map.setdefault(normalized, jp)
    return name_map


def load_filetree(
    cache_path: Path, *, fetch: Callable[[], bytes], now: datetime, max_age_days: int = 7
) -> dict:
    """缓存在 max_age_days 天内直接读缓存；否则重新下载并写回。下载失败时有缓存就用旧缓存，没有就抛错。"""
    cache_path = Path(cache_path)
    if cache_path.is_file():
        modified = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if now - modified <= timedelta(days=max_age_days):
            return json.loads(cache_path.read_text(encoding="utf-8"))
    try:
        payload = fetch()
        data = json.loads(payload)
    except Exception as exc:  # noqa: BLE001 — 任何下载或解析失败都退回旧缓存
        if cache_path.is_file():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        raise GfriendsError(f"Gfriends 索引下载失败且没有缓存：{exc}") from exc
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, cache_path)
    return data


def fetch_filetree(*, timeout: float = 60) -> bytes:
    """下载 Gfriends 官方索引原文。"""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(FILETREE_URL)
        response.raise_for_status()
        return response.content


def gfriends_image_url(rel_path: str) -> str:
    return f"{GFRIENDS_BASE}/Content/{rel_path}"


def download_image(
    url: str,
    *,
    timeout: float = 30,
    max_bytes: int = 5 * 1024 * 1024,
    transport: httpx.BaseTransport | None = None,
) -> tuple[bytes, str]:
    """下载一张图，返回（内容, Content-Type）；非 200、不是图片、超过上限都抛 GfriendsError。"""
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise GfriendsError(f"头像下载失败（HTTP {response.status_code}）")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                if not content_type.startswith("image/"):
                    raise GfriendsError(f"头像地址返回的不是图片（{content_type or '未知类型'}）")
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise GfriendsError("头像图片超过 5MB")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise GfriendsError("头像图片超过 5MB")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise GfriendsError(f"头像下载失败：{exc}") from exc
    return b"".join(chunks), content_type
