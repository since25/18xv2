"""把 Jellyfin 扫描到的 115 STRM 条目按番号目录归成「片子」，并读取片子的 NFO 标题。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem


@dataclass(frozen=True)
class Film:
    """一部片 = `<strm 根>/<演员>/<番号>` 这个番号目录，目录里的分段 STRM 同属一部片。"""

    # 番号目录的完整路径
    film_dir: str
    # 番号目录名
    number: str
    # 演员目录的完整路径（番号目录的上一级）
    actor_dir: str
    # 各分段 STRM 的完整路径，按路径排序
    strm_paths: tuple[str, ...]
    # 与 strm_paths 一一对应的扫描条目 id
    media_item_ids: tuple[int, ...]
    # 已解析到 Jellyfin 条目的那些分段的 Jellyfin id
    jellyfin_item_ids: tuple[str, ...]
    # 全部分段 NFO 演员的原样名字，按归一化去重，保持首次出现顺序
    actor_names: tuple[str, ...]


@dataclass
class _Part:
    """片子的一个分段（一个 STRM 条目）及其演员行。"""

    media_item_id: int
    path: str
    jellyfin_item_id: str | None
    actors: list[tuple[str, str]]


def load_films(db: Session, *, strm_roots: list[str], film_dirs: set[str] | None = None) -> list[Film]:
    """按番号目录归组有效的 115 STRM 条目，返回按番号目录路径排序的片子列表。

    只取 `source == "strm_115"`、`active` 且路径恰好是 `<某个 strm 根>/<演员>/<番号>/<文件>.strm` 的条目；
    扫描在文件消失时只把条目置为无效、不删演员行，所以必须按 `active` 过滤。
    `film_dirs` 给定时只返回这些番号目录。
    """
    # 与扫描一致：根目录取绝对路径，条目路径是 normpath 之后存的
    roots = [os.path.abspath(root) for root in strm_roots if root]
    wanted = None if film_dirs is None else {os.path.normpath(film_dir) for film_dir in film_dirs}
    if not roots or wanted == set():
        return []

    rows = db.execute(
        select(
            JellyfinMediaItem.id,
            JellyfinMediaItem.path,
            JellyfinMediaItem.jellyfin_item_id,
            JellyfinMediaItem.resolve_state,
            JellyfinMediaActor.raw_name,
            JellyfinMediaActor.name_normalized,
        )
        .outerjoin(JellyfinMediaActor, JellyfinMediaActor.media_item_id == JellyfinMediaItem.id)
        .where(JellyfinMediaItem.source == "strm_115", JellyfinMediaItem.active.is_(True))
        .order_by(JellyfinMediaItem.id, JellyfinMediaActor.position)
    ).all()

    parts_by_dir: dict[str, dict[int, _Part]] = {}
    for item_id, path, jellyfin_item_id, resolve_state, raw_name, name_normalized in rows:
        film_dir = _film_dir_of(path, roots)
        if film_dir is None or (wanted is not None and film_dir not in wanted):
            continue
        parts = parts_by_dir.setdefault(film_dir, {})
        part = parts.get(item_id)
        if part is None:
            resolved = resolve_state == "resolved" and bool(jellyfin_item_id)
            part = _Part(item_id, path, jellyfin_item_id if resolved else None, [])
            parts[item_id] = part
        # 没有演员行（NFO 缺失或解析失败）的分段，外连接得到的演员列为空
        if raw_name is not None:
            part.actors.append((raw_name, name_normalized))

    return [_build_film(film_dir, list(parts.values())) for film_dir, parts in sorted(parts_by_dir.items())]


def _film_dir_of(path: str, roots: list[str]) -> str | None:
    """路径恰好是 `<根>/<演员>/<番号>/<文件>.strm` 时返回番号目录，否则返回 None。"""
    for root in roots:
        prefix = root if root.endswith(os.sep) else root + os.sep
        if not path.startswith(prefix):
            continue
        segments = path[len(prefix) :].split(os.sep)
        if len(segments) == 3 and all(segments) and os.path.splitext(segments[2])[1].lower() == ".strm":
            return os.path.join(root, segments[0], segments[1])
    return None


def _build_film(film_dir: str, parts: list[_Part]) -> Film:
    parts.sort(key=lambda part: part.path)
    actor_names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for raw_name, name_normalized in part.actors:
            if name_normalized in seen:
                continue
            seen.add(name_normalized)
            actor_names.append(raw_name)
    return Film(
        film_dir=film_dir,
        number=os.path.basename(film_dir),
        actor_dir=os.path.dirname(film_dir),
        strm_paths=tuple(part.path for part in parts),
        media_item_ids=tuple(part.media_item_id for part in parts),
        jellyfin_item_ids=tuple(part.jellyfin_item_id for part in parts if part.jellyfin_item_id),
        actor_names=tuple(actor_names),
    )


def read_nfo_title(film: Film) -> str | None:
    """读番号目录里（按文件名排序）第一个 `.nfo` 的 `<title>`；没有、读不了或解析失败都返回 None。"""
    try:
        nfo_names = sorted(name for name in os.listdir(film.film_dir) if name.lower().endswith(".nfo"))
        if not nfo_names:
            return None
        xml_text = Path(film.film_dir, nfo_names[0]).read_text(encoding="utf-8")
        title = (ET.fromstring(xml_text).findtext("title") or "").strip()
        return title or None
    except Exception:
        return None
