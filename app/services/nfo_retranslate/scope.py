"""范围判断：读 MDC 库副本取字段来源，把 NFO 按「一部片」分组，判断标题、简介要不要重翻。"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
import re
import shutil
import sqlite3
from typing import Literal

from app.services.nfo_retranslate.nfo_file import (
    NfoDoc,
    NfoError,
    plot_body,
    read_nfo,
    strip_num,
    translator_marker,
)

# 中文站来源：这些站给的标题、简介本来就是中文，不重翻
CN_SOURCES: frozenset[str] = frozenset({"airav_io", "sehuatang", "Madou", "Madouqu", "xiao_huang_shu"})
# MDC 任务 target_path 里 302porn_tv1 根目录的写法
MDC_ROOT_PREFIX = "/302video/302porn_tv1"
# 日文假名（平假名、片假名）
_KANA = re.compile("[぀-ヿ]")


@dataclass(frozen=True)
class FieldSources:
    """一个 NFO 的标题、简介各取自哪个站；MDC 没记录时为 None。"""

    title: str | None
    outline: str | None


@dataclass
class FilmGroup:
    """一部片：同一目录、同一番号的 NFO（多段、不同版本），key 为「相对目录|番号」。"""

    key: str
    docs: list[NfoDoc]


def snapshot_mdc_db(db_path: str, workdir: str) -> str:
    """把 MDC 库和存在的 -wal 复制到 workdir，返回副本路径；源库不存在抛 FileNotFoundError。"""
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"MDC 数据库不存在：{db_path}")
    os.makedirs(workdir, exist_ok=True)
    copy = os.path.join(workdir, os.path.basename(db_path))
    # 先删掉上次复制留下的 -wal、-shm，免得旧日志套到新库上
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(copy + suffix)
    shutil.copyfile(db_path, copy)
    with contextlib.suppress(FileNotFoundError):
        shutil.copyfile(db_path + "-wal", copy + "-wal")
    return copy


def _parse_info(text: str | None) -> dict:
    """解析 metadata_provider_info；空值、坏 JSON、不是对象都当作空。"""
    try:
        info = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def _source(info: dict, key: str) -> str | None:
    """取某个字段的来源站名；没有或不是字符串时返回 None。"""
    value = info.get(key)
    return value if isinstance(value, str) and value else None


def load_task_sources(db_copy: str, root: str) -> dict[str, FieldSources]:
    """读 MDC 库副本，返回 {NFO 绝对路径: 字段来源}；分段子任务用主任务的来源，同一路径以 id 大的任务为准。"""
    with contextlib.closing(sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT id, primary_task_id, target_path, metadata_provider_info FROM task ORDER BY id"
        ).fetchall()
    infos = {task_id: _parse_info(info) for task_id, _, _, info in rows}
    root = os.path.abspath(root)
    sources: dict[str, FieldSources] = {}
    for task_id, primary_id, target_path, _ in rows:
        if not target_path or not target_path.startswith(MDC_ROOT_PREFIX + "/"):
            continue
        info = infos[task_id]
        if primary_id is not None:
            info = infos.get(primary_id, info)
        rel = os.path.splitext(target_path[len(MDC_ROOT_PREFIX) + 1 :])[0] + ".nfo"
        sources[os.path.normpath(os.path.join(root, rel))] = FieldSources(
            title=_source(info, "Title"), outline=_source(info, "Outline")
        )
    return sources


def group_films(root: str, *, path_prefix: str | None = None) -> tuple[list[FilmGroup], list[tuple[str, str]]]:
    """遍历 root（或其下 path_prefix 目录）里的 NFO，按「相对目录|番号」分组；返回 (分组, [(读不了的 NFO, 原因)])。"""
    root = os.path.abspath(root)
    start = os.path.join(root, path_prefix.strip("/")) if path_prefix else root
    docs_by_key: dict[str, list[NfoDoc]] = {}
    errors: list[tuple[str, str]] = []
    for dirpath, _, filenames in os.walk(start):
        rel_dir = os.path.relpath(dirpath, root)
        for name in filenames:
            if not name.endswith(".nfo"):
                continue
            path = os.path.join(dirpath, name)
            try:
                doc = read_nfo(path)
            except NfoError as exc:
                errors.append((path, str(exc)))
                continue
            docs_by_key.setdefault(f"{rel_dir}|{doc.num}", []).append(doc)
    groups = [FilmGroup(key, sorted(docs, key=lambda d: d.path)) for key, docs in docs_by_key.items()]
    groups.sort(key=lambda g: g.docs[0].path)
    errors.sort()
    return groups, errors


def has_kana(text: str) -> bool:
    """文本里有没有日文假名。"""
    return _KANA.search(text) is not None


def field_in_scope(field: Literal["title", "plot"], doc: NfoDoc, sources: FieldSources | None) -> bool:
    """这个 NFO 的标题或简介要不要重翻：来源不是中文站，且原文去掉番号后含假名。

    找不到 MDC 任务（sources 为 None）时：标题一律不翻；简介末尾带翻译标记的才翻。
    """
    if field == "title":
        if sources is None or sources.title in CN_SOURCES:
            return False
        return has_kana(strip_num(doc.original_title, doc.num))
    original = strip_num(plot_body(doc.original_plot), doc.num)
    if sources is None:
        return translator_marker(doc.plot) is not None and has_kana(original)
    return sources.outline not in CN_SOURCES and has_kana(original)


def count_orphans(groups: list[FilmGroup], sources: dict[str, FieldSources]) -> int:
    """统计找不到对应 MDC 任务的 NFO 个数。"""
    return sum(1 for group in groups for doc in group.docs if doc.path not in sources)


def group_matches_engine(group: FilmGroup, engine: str) -> bool:
    """组内有没有哪个 NFO 的简介标记是「由 engine 提供翻译」。"""
    return any(translator_marker(doc.plot) == engine for doc in group.docs)
