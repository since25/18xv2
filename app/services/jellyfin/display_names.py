"""本地已整理视频在 Jellyfin 里的显示名规则。

规则见 docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md 第五节：
按相对根目录的路径取「关键词/资源包」作为分组（直接在关键词下的只取关键词），
同一分组内按相对路径自然排序编号，显示为「序号 · 分组名」（序号在前，客户端截断时也看得到）。
排序名另存为「分组名 · 序号」并把数字补零，保证合集仍按「包 → 序号」播放。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import re
from typing import NamedTuple


_DIGITS = re.compile(r"(\d+)")
# 与 Jellyfin 自动生成排序名时一致：数字补到 10 位，按数值顺序排
_SORT_DIGITS = 10


class DisplayName(NamedTuple):
    """一个视频的显示名和写进 Jellyfin 强制排序名的值。"""

    name: str
    sort_name: str


def _pad_digits(text: str) -> str:
    return _DIGITS.sub(lambda match: match.group().zfill(_SORT_DIGITS), text)


def natural_key(text: str) -> tuple:
    """自然排序键：数字块按数值比较，文本块忽略大小写；最后带上原文保证顺序稳定。"""
    # re.split 带分组时，偶数位一定是文本块、奇数位一定是数字块，同位置类型一致可比较
    chunks = tuple(int(chunk) if index % 2 else chunk.casefold() for index, chunk in enumerate(_DIGITS.split(text)))
    return chunks, text


def compute_display_names(paths: Iterable[str], local_roots: Sequence[str]) -> dict[str, DisplayName]:
    """按路径算出显示名和排序名；不在任何根目录下、或直接放在根目录下的路径不出现在结果里。"""
    roots = [root.rstrip("/") for root in local_roots if root and root.rstrip("/")]
    groups: dict[str, list[tuple[str, str]]] = {}
    for path in dict.fromkeys(paths):
        relative = None
        for root in roots:
            prefix = root + "/"
            if path.startswith(prefix):
                relative = path[len(prefix) :]
                break
        if relative is None:
            continue
        parts = relative.split("/")
        if len(parts) < 2:
            continue
        # 3 层及以上取前两层，更深的 V、视图 这类子目录不进名字
        group = "/".join(parts[:2]) if len(parts) >= 3 else parts[0]
        groups.setdefault(group, []).append((relative, path))

    names: dict[str, DisplayName] = {}
    for group, members in groups.items():
        members.sort(key=lambda member: natural_key(member[0]))
        width = max(2, len(str(len(members))))
        for index, (_relative, path) in enumerate(members, start=1):
            names[path] = DisplayName(
                name=f"{index:0{width}d} · {group}",
                sort_name=_pad_digits(f"{group} · {index}"),
            )
    return names
