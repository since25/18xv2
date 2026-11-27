"""判断视频删掉后，同目录里哪些 nfo、图片、字幕可以一起清掉。

只做纯判断，不碰文件系统和 115；真正删除由 FilmDeleteGuard 和 115 客户端执行。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os

# 配套扩展名一律小写比较
IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
SUBTITLE_EXTS: frozenset[str] = frozenset({".srt", ".ass", ".ssa", ".vtt"})
SIDECAR_EXTS: frozenset[str] = IMAGE_EXTS | SUBTITLE_EXTS | {".nfo"}

_IMAGE_STEMS = ("-poster", "-fanart", "-thumb")


def is_sidecar(name: str) -> bool:
    """扩展名（小写）属于 nfo、图片或字幕时返回 True。"""
    return os.path.splitext(name)[1].lower() in SIDECAR_EXTS


def _is_video_sidecar(name: str, video_stem: str) -> bool:
    """name 是否正好是某个视频的配套文件名（大小写敏感，扩展名小写比较）。"""
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if stem == video_stem:
        return ext == ".nfo" or ext in SUBTITLE_EXTS
    return stem in {video_stem + suffix for suffix in _IMAGE_STEMS} and ext in IMAGE_EXTS


def sidecar_names(video_names: Iterable[str], entries: Iterable[tuple[str, bool]]) -> list[str]:
    """entries 里属于某个视频的同名配套文件名字，排序去重；目录一律不认。"""
    stems = {os.path.splitext(name)[0] for name in video_names if name}
    found = {
        name
        for name, is_dir in entries
        if not is_dir and any(_is_video_sidecar(name, stem) for stem in stems)
    }
    return sorted(found)


@dataclass(frozen=True)
class LeftoverPlan:
    """一个目录的清理计划：whole_dir 为 True 时整个删除，否则只删 names 里的同名配套文件。"""

    whole_dir: bool
    names: list[str]


def plan_dir(video_names: Iterable[str], entries: Iterable[tuple[str, bool]]) -> LeftoverPlan:
    """剩下全是配套扩展名且没有子文件夹时整个删；否则退回只删同名配套文件。"""
    entry_list = list(entries)
    if all(not is_dir and is_sidecar(name) for name, is_dir in entry_list):
        return LeftoverPlan(whole_dir=True, names=[])
    return LeftoverPlan(whole_dir=False, names=sidecar_names(video_names, entry_list))
