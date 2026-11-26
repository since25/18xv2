"""女优头像：按档案名到 Gfriends 找图，上传为 Jellyfin 人物主图，并在档案上记状态。

已有主图的人物一律不动；uploaded / present 的女优以后不再回查（尊重用户在 Jellyfin 里的手动删图）；
not_found / no_person 满 7 天后重查。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import time
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.actresses import Actress
from app.services.actresses.gfriends import GfriendsError, gfriends_image_url
from app.services.jellyfin.client import JellyfinError

RECHECK_AFTER = timedelta(days=7)
_RECHECK_STATES = ("not_found", "no_person")
_TODO_STATES = ("pending", "error", *_RECHECK_STATES)


class _Index(Protocol):
    used_name_map: bool

    def find(self, names: list[str]) -> str | None: ...


class _Client(Protocol):
    def get_person(self, name: str) -> dict[str, Any] | None: ...

    def upload_person_image(self, person_id: str, content: bytes, content_type: str) -> None: ...


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 读回来的时间不带时区，按 UTC 补上再比较。"""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class AvatarService:
    def run(
        self,
        db: Session,
        *,
        index: _Index,
        client: _Client,
        fetch_image: Callable[[str], tuple[bytes, str]],
        now: datetime,
        limit: int,
        actress_ids: list[int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        interval: float = 0.5,
    ) -> dict[str, int]:
        """处理一批女优，返回各结果的人数。给了 actress_ids 时只处理她们，不看当前状态。"""
        summary = {key: 0 for key in ("processed", "uploaded", "present", "not_found", "no_person", "error")}
        summary["used_name_map"] = int(bool(index.used_name_map))
        downloaded_last = False
        for actress in self._select(db, now=now, limit=limit, actress_ids=actress_ids):
            if downloaded_last:
                sleep(interval)
            state, source, note, downloaded_last = self._process(actress, index, client, fetch_image)
            actress.avatar_state = state
            actress.avatar_source = source
            actress.avatar_note = note
            actress.avatar_checked_at = now
            db.commit()
            summary["processed"] += 1
            summary[state] += 1
        return summary

    @staticmethod
    def _select(db: Session, *, now: datetime, limit: int, actress_ids: list[int] | None) -> list[Actress]:
        """挑出这次要处理的人：按片数从多到少，再按 id，最多 limit 人。"""
        query = select(Actress).options(selectinload(Actress.aliases)).order_by(
            Actress.film_count.desc(), Actress.id
        )
        if actress_ids is not None:
            return list(db.scalars(query.where(Actress.id.in_(actress_ids))).all())[:limit]
        rows = db.scalars(query.where(Actress.avatar_state.in_(_TODO_STATES))).all()
        due = [
            actress
            for actress in rows
            if actress.avatar_state not in _RECHECK_STATES
            or actress.avatar_checked_at is None
            or _aware(actress.avatar_checked_at) <= now - RECHECK_AFTER
        ]
        return due[:limit]

    @staticmethod
    def _process(
        actress: Actress,
        index: _Index,
        client: _Client,
        fetch_image: Callable[[str], tuple[bytes, str]],
    ) -> tuple[str, str | None, str | None, bool]:
        """返回（状态, 命中的 Gfriends 路径, 说明, 是否下载过图）。"""
        names = [actress.canonical_name, *(alias.alias for alias in sorted(actress.aliases, key=lambda a: a.id))]
        source = index.find(names)
        if source is None:
            return "not_found", None, "Gfriends 里找不到", False
        try:
            persons = [person for person in (client.get_person(name) for name in names) if person is not None]
        except JellyfinError as exc:
            return "error", source, f"查 Jellyfin 人物失败：{exc}", False
        if not persons:
            return "no_person", source, "Jellyfin 里没有这个人物", False
        missing = list(dict.fromkeys(person["id"] for person in persons if not person["has_primary"]))
        if not missing:
            return "present", source, None, False
        try:
            content, content_type = fetch_image(gfriends_image_url(source))
        except GfriendsError as exc:
            return "error", source, str(exc), True
        try:
            for person_id in missing:
                client.upload_person_image(person_id, content, content_type)
        except JellyfinError as exc:
            return "error", source, f"上传 Jellyfin 失败：{exc}", True
        return "uploaded", source, None, True
