"""女优删片的本地删除守卫、扫描路径换算和 STRM 地址索引。

扫描得到的是只读挂载路径，删除前用 PathMapper 换成可写挂载路径；
FilmDeleteGuard 只允许删两个可写根目录里规定位置的东西，路径上任何一段是链接都拒绝。
"""

from __future__ import annotations

import os
import shutil

from app.services.actresses.leftovers import SIDECAR_EXTS
from app.services.emby_media_actions.strm_mapping_service import normalize_stream_url


class GuardError(Exception):
    """删除请求越界或目标形态不对，拒绝执行，什么都没删。"""


def parse_path_map(value: str) -> list[tuple[str, str]]:
    """解析路径换算配置 `"旧前缀=>新前缀,旧前缀=>新前缀"`；空串返回 []，写法不对抛 ValueError。"""
    mappings: list[tuple[str, str]] = []
    for item in value.split(","):
        if not item.strip():
            continue
        source, separator, target = (part.strip() for part in item.partition("=>"))
        if not separator or not source or not target:
            raise ValueError(f"路径换算写法不对：{item.strip()}")
        mappings.append((source, target))
    return mappings


class PathMapper:
    """按最长前缀把扫描路径换成可写路径，只在目录边界匹配。"""

    def __init__(self, mappings: list[tuple[str, str]]) -> None:
        # 去掉末尾斜杠后按前缀长度倒序，先试最长的
        self.mappings = sorted(
            ((source.rstrip(os.sep), target.rstrip(os.sep)) for source, target in mappings),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def map(self, path: str) -> str:
        """换成最长命中的前缀；没有命中原样返回。"""
        for source, target in self.mappings:
            if path == source or path.startswith(source + os.sep):
                return target + path[len(source) :]
        return path


def _locate(path: str, root: str, *, depth: int | None, rule: str) -> str:
    """检查 path 在 root 之下（depth 给定时恰好这么多层）且从 root 往下没有经过链接，返回规整后的路径。

    之后的删除只对返回的规整路径操作，不对原始 path 操作。
    """
    if not os.path.isabs(path):
        raise GuardError(f"{rule}，不是绝对路径：{path}")
    target = os.path.abspath(path)
    root_abs = os.path.abspath(root)
    prefix = root_abs if root_abs.endswith(os.sep) else root_abs + os.sep
    parts = target[len(prefix) :].split(os.sep) if target.startswith(prefix) else []
    if not parts or (depth is not None and len(parts) != depth):
        raise GuardError(f"{rule}：{path}")
    # realpath 会解开所有链接：与「根的真实路径 + 相对各段」不一致，说明根以下（含目标本身）有链接
    if os.path.realpath(target) != os.path.join(os.path.realpath(root_abs), *parts):
        raise GuardError(f"路径经过链接，拒绝删除：{path}")
    return target


class FilmDeleteGuard:
    """只在两个可写根目录里删：`source_root` 下的 `.strm`、配套文件和目录，`organized_root/<演员>/<番号>` 目录和变空的演员目录。"""

    def __init__(self, source_root: str, organized_root: str) -> None:
        for root in (source_root, organized_root):
            # 空串或相对路径会落到当前工作目录
            if not os.path.isabs(root):
                raise GuardError(f"删除根目录必须是绝对路径：{root!r}")
        self.source_root = source_root
        self.organized_root = organized_root

    def delete_source_strm(self, path: str) -> str:
        """删 `source_root` 下的一个 `.strm` 普通文件，返回 deleted；不存在返回 missing。"""
        rule = f"只能删 {self.source_root} 下的 .strm 文件"
        target = _locate(path, self.source_root, depth=None, rule=rule)
        if not target.lower().endswith(".strm"):
            raise GuardError(f"{rule}：{path}")
        if not os.path.lexists(target):
            return "missing"
        if not os.path.isfile(target):
            raise GuardError(f"不是普通文件，拒绝删除：{path}")
        os.remove(target)
        return "deleted"

    def delete_source_dir(self, path: str) -> str:
        """整个删除 `source_root` 下至少一层的目录，返回 deleted；不存在返回 missing。"""
        rule = f"只能删 {self.source_root} 下的目录"
        target = _locate(path, self.source_root, depth=None, rule=rule)
        if not os.path.lexists(target):
            return "missing"
        if not os.path.isdir(target):
            raise GuardError(f"不是目录，拒绝删除：{path}")
        # rmtree 遇到目录里的链接只删链接本身，不进入链接目标
        shutil.rmtree(target)
        return "deleted"

    def delete_source_sidecar(self, path: str) -> str:
        """删 `source_root` 下的一个 nfo / 图片 / 字幕普通文件，返回 deleted；不存在返回 missing。"""
        rule = f"只能删 {self.source_root} 下的 nfo、图片、字幕"
        target = _locate(path, self.source_root, depth=None, rule=rule)
        if os.path.splitext(target)[1].lower() not in SIDECAR_EXTS:
            raise GuardError(f"{rule}：{path}")
        if not os.path.lexists(target):
            return "missing"
        if not os.path.isfile(target):
            raise GuardError(f"不是普通文件，拒绝删除：{path}")
        os.remove(target)
        return "deleted"

    def check_film_dir(self, path: str) -> str:
        """只校验不删除：path 必须是现存的 `organized_root/<演员>/<番号>` 目录且不经过链接，返回规整后的路径。

        规则与 delete_film_dir 相同；不存在也算不合格，抛 GuardError。
        """
        rule = f"番号目录必须恰好是 {self.organized_root}/<演员>/<番号>"
        target = _locate(path, self.organized_root, depth=2, rule=rule)
        if not os.path.isdir(target):
            raise GuardError(f"番号目录不存在或不是目录：{path}")
        return target

    def delete_film_dir(self, path: str) -> str:
        """整个删除 `organized_root/<演员>/<番号>` 目录，返回 deleted；不存在返回 missing。"""
        rule = f"番号目录必须恰好是 {self.organized_root}/<演员>/<番号>"
        target = _locate(path, self.organized_root, depth=2, rule=rule)
        if not os.path.lexists(target):
            return "missing"
        if not os.path.isdir(target):
            raise GuardError(f"番号目录不是目录，拒绝删除：{path}")
        # rmtree 遇到目录里的链接只删链接本身，不进入链接目标
        shutil.rmtree(target)
        return "deleted"

    def remove_actor_dir_if_empty(self, path: str) -> bool:
        """`organized_root/<演员>` 是空目录时删掉并返回 True，否则（含不存在）返回 False；不往上递归。"""
        rule = f"演员目录必须恰好是 {self.organized_root}/<演员>"
        target = _locate(path, self.organized_root, depth=1, rule=rule)
        if not os.path.isdir(target) or os.listdir(target):
            return False
        os.rmdir(target)
        return True


def read_strm_url(path: str) -> str | None:
    """STRM 文件第一行非空内容（去掉首尾空白和 BOM）；文件读不了或没有内容返回 None。"""
    try:
        with open(path, encoding="utf-8-sig") as file:
            for line in file:
                if line.strip():
                    return line.strip()
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _raise(exc: OSError) -> None:
    raise exc


def build_url_index(root: str) -> dict[str, list[str]]:
    """`root` 下全部 `.strm`：规整后的地址 → 路径列表（排序）。

    读不到地址的 STRM 跳过；`root` 或其中目录读不了时抛 OSError，
    不能把「目录不在」当成「没有对应 STRM」而漏删。不进入指向目录的链接。
    """
    index: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(root, onerror=_raise):
        for name in filenames:
            if not name.lower().endswith(".strm"):
                continue
            path = os.path.join(dirpath, name)
            url = read_strm_url(path)
            if url is not None:
                index.setdefault(normalize_stream_url(url), []).append(path)
    for paths in index.values():
        paths.sort()
    return index
