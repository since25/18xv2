"""女优档案：建档、片数、改状态、别名与合并。

女优名只写进女优自己的表，不碰关键词库（keyword_entries / keyword_aliases）。
改状态与合并之后不在这里重算待删清单，由调用方接着调用清单服务的 reconcile。
"""

from __future__ import annotations

import os

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.actresses import Actress, ActressAlias, ActressMark, JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.films import load_films
from app.services.actresses.names import build_name_index, normalize_actress_name

ACTRESS_STATUSES = ("none", "blacklist", "whitelist")

# 名字列宽，超长写入会让 PostgreSQL 报错
_NAME_MAX_LENGTH = 255


class ActressError(ValueError):
    """女优档案的业务错误，接口层转成 400。"""


def _normalize(raw: str) -> str:
    """与扫描写演员行一致：归一化后截到列宽。"""
    return normalize_actress_name(raw)[:_NAME_MAX_LENGTH]


def _new_actress(raw_name: str, normalized: str) -> Actress:
    return Actress(
        canonical_name=raw_name.strip()[:_NAME_MAX_LENGTH],
        canonical_name_normalized=normalized,
        status="none",
        film_count=0,
    )


class ArchiveService:
    """女优档案的增改操作，每个方法自己 commit。"""

    def refresh(self, db: Session, *, strm_roots: list[str]) -> dict[str, int]:
        """给有效片子里还对不上档案的演员名建档（未标），并重算全部女优的片数。"""
        actresses = list(db.scalars(select(Actress)))
        by_id = {actress.id: actress for actress in actresses}
        owner_by_name = {name: by_id[actress_id] for name, actress_id in build_name_index(db).items()}
        film_counts: dict[Actress, int] = {}
        created = 0

        for film in load_films(db, strm_roots=strm_roots):
            film_actresses: set[Actress] = set()
            for raw_name in film.actor_names:
                normalized = _normalize(raw_name)
                if not normalized:
                    continue
                actress = owner_by_name.get(normalized)
                if actress is None:
                    # 规范名取首次出现的原样写法
                    actress = _new_actress(raw_name, normalized)
                    db.add(actress)
                    actresses.append(actress)
                    owner_by_name[normalized] = actress
                    created += 1
                film_actresses.add(actress)
            for actress in film_actresses:
                film_counts[actress] = film_counts.get(actress, 0) + 1

        for actress in actresses:
            actress.film_count = film_counts.get(actress, 0)
        db.commit()
        return {"created": created, "actresses": len(actresses)}

    def ensure_actresses(self, db: Session, raw_names: list[str]) -> list[Actress]:
        """按顺序返回每个名字对应的女优，档案里没有的当场建档（未标）。"""
        normalized_names = [_normalize(raw_name) for raw_name in raw_names]
        for raw_name, normalized in zip(raw_names, normalized_names):
            if not normalized:
                raise ActressError(f"演员名「{raw_name}」为空或只含空格和标点")

        index = build_name_index(db)
        created: dict[str, Actress] = {}
        result: list[Actress] = []
        for raw_name, normalized in zip(raw_names, normalized_names):
            actress_id = index.get(normalized)
            if actress_id is not None:
                result.append(db.get(Actress, actress_id))
                continue
            actress = created.get(normalized)
            if actress is None:
                actress = _new_actress(raw_name, normalized)
                db.add(actress)
                created[normalized] = actress
            result.append(actress)
        db.commit()
        return result

    def set_status(
        self,
        db: Session,
        actress_ids: list[int],
        status: str,
        *,
        source: str,
        media_item_id: int | None = None,
    ) -> int:
        """把这些女优改成 status；只有状态真有变化的才写标记记录，返回变化人数。"""
        if status not in ACTRESS_STATUSES:
            raise ActressError(f"未知状态：{status}")
        actresses = [self._get(db, actress_id) for actress_id in dict.fromkeys(actress_ids)]
        changed = 0
        for actress in actresses:
            if actress.status == status:
                continue
            db.add(
                ActressMark(
                    actress_id=actress.id,
                    from_status=actress.status,
                    to_status=status,
                    source=source,
                    media_item_id=media_item_id,
                )
            )
            actress.status = status
            changed += 1
        db.commit()
        return changed

    def add_alias(self, db: Session, actress_id: int, alias: str) -> ActressAlias:
        """给女优加一个别名；别名已是任何女优（含她自己）的规范名或别名时拒绝。"""
        actress = self._get(db, actress_id)
        alias_text = alias.strip()[:_NAME_MAX_LENGTH]
        normalized = _normalize(alias)
        if not normalized:
            raise ActressError("别名为空或只含空格和标点")
        owner = self._find_owner(db, normalized)
        if owner is not None:
            if owner.id == actress.id:
                raise ActressError(f"「{alias_text}」已经是 {owner.canonical_name} 的名字")
            raise ActressError(f"「{alias_text}」已属于 {owner.canonical_name}，请用合并")
        row = ActressAlias(alias=alias_text, alias_normalized=normalized)
        actress.aliases.append(row)
        db.commit()
        return row

    def remove_alias(self, db: Session, actress_id: int, alias_id: int) -> None:
        """删掉女优的一个别名；别名不属于她时报错。"""
        actress = self._get(db, actress_id)
        row = next((alias for alias in actress.aliases if alias.id == alias_id), None)
        if row is None:
            raise ActressError(f"{actress.canonical_name} 没有这个别名")
        # 从集合移除即由 delete-orphan 删除这一行
        actress.aliases.remove(row)
        db.commit()

    def merge(self, db: Session, source_id: int, target_id: int) -> Actress:
        """把 source 合并进 target：名字变成 target 的别名，标记记录转给 target，删除 source。"""
        if source_id == target_id:
            raise ActressError("不能把女优合并到她自己")
        source = self._get(db, source_id)
        target = self._get(db, target_id)
        if {source.status, target.status} == {"blacklist", "whitelist"}:
            raise ActressError(
                f"{source.canonical_name} 和 {target.canonical_name} 一个是黑名单、一个是白名单，请先改状态再合并"
            )

        # source 的别名整行转给 target，source 的规范名成为 target 的新别名
        for row in list(source.aliases):
            row.actress = target
        target.aliases.append(
            ActressAlias(alias=source.canonical_name, alias_normalized=source.canonical_name_normalized)
        )
        db.execute(update(ActressMark).where(ActressMark.actress_id == source.id).values(actress_id=target.id))

        new_status = target.status if target.status != "none" else source.status
        db.add(
            ActressMark(
                actress_id=target.id,
                from_status=target.status,
                to_status=new_status,
                source="merge",
                note=f"合并 {source.canonical_name}",
            )
        )
        target.status = new_status
        db.delete(source)
        db.flush()
        target.film_count = self._count_films(db, target)
        db.commit()
        return target

    @staticmethod
    def _get(db: Session, actress_id: int) -> Actress:
        actress = db.get(Actress, actress_id)
        if actress is None:
            raise ActressError(f"女优不存在：{actress_id}")
        return actress

    @staticmethod
    def _find_owner(db: Session, normalized: str) -> Actress | None:
        """找规范名或别名（归一化后）等于 normalized 的女优。"""
        actress = db.scalar(select(Actress).where(Actress.canonical_name_normalized == normalized))
        if actress is not None:
            return actress
        return db.scalar(
            select(Actress).join(ActressAlias, ActressAlias.actress_id == Actress.id).where(
                ActressAlias.alias_normalized == normalized
            )
        )

    @staticmethod
    def _count_films(db: Session, actress: Actress) -> int:
        """按演员行统计她出现在多少个有效番号目录里（STRM 条目的上一级目录去重）。

        合并接口拿不到 strm 根目录，这里不校验目录层级；每日刷新会按 load_films 的严格规则重算。
        """
        names = {actress.canonical_name_normalized, *(alias.alias_normalized for alias in actress.aliases)}
        paths = db.scalars(
            select(func.distinct(JellyfinMediaItem.path))
            .join(JellyfinMediaActor, JellyfinMediaActor.media_item_id == JellyfinMediaItem.id)
            .where(
                JellyfinMediaItem.source == "strm_115",
                JellyfinMediaItem.active.is_(True),
                JellyfinMediaActor.name_normalized.in_(names),
            )
        ).all()
        return len({os.path.dirname(path) for path in paths})
