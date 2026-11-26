"""删片规则：一部片什么时候应该删，什么时候受保护。

应删 = 有黑名单演员、没有受保护演员、没标为保留、有演员；
「片子仍有效」由 `load_films` 只返回有效条目保证。
受保护 = 演员对应到白名单女优，或命中启用中的关键词白名单 / Emby 白名单：
演员能对上档案时，这位女优的规范名和任一别名命中都算；对不上档案时只比演员名本身。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import Actress, ActressKeptFilm
from app.services.actresses.films import Film
from app.services.actresses.names import build_name_index, build_protected_terms, normalize_actress_name


@dataclass(frozen=True)
class Verdict:
    """一部片的判断结果；名字都是 NFO 里的原样写法。"""

    deletable: bool
    # 演员里黑名单的人
    black_names: tuple[str, ...]
    # 演员里受白名单保护的人
    protected_by: tuple[str, ...]
    # 番号目录在保留名单里
    kept: bool


@dataclass
class RuleContext:
    """判断所需的档案状态、受保护名字和保留名单，一次读库，可对多部片反复判断。"""

    # 归一化名字（规范名和别名）→ 女优 id
    name_index: dict[str, int]
    status_by_id: dict[int, str]
    # 启用中的关键词白名单 / Emby 白名单的名字（归一化后）
    protected_terms: set[str]
    kept_dirs: set[str]

    @classmethod
    def load(cls, db: Session) -> RuleContext:
        return cls(
            name_index=build_name_index(db),
            status_by_id=dict(db.execute(select(Actress.id, Actress.status)).all()),
            protected_terms=build_protected_terms(db),
            kept_dirs=set(db.scalars(select(ActressKeptFilm.film_dir))),
        )

    @cached_property
    def _keyword_protected_ids(self) -> set[int]:
        """规范名或任一别名命中关键词白名单 / Emby 白名单的女优 id。"""
        return {self.name_index[term] for term in self.protected_terms if term in self.name_index}

    def actor_status(self, raw_name: str) -> str:
        """演员在档案里的状态；档案里没有的算未标（none）。"""
        actress_id = self.name_index.get(normalize_actress_name(raw_name))
        return self.status_by_id.get(actress_id, "none")

    def verdict(self, film: Film) -> Verdict:
        black_names: list[str] = []
        protected_by: list[str] = []
        for raw_name in film.actor_names:
            normalized = normalize_actress_name(raw_name)
            actress_id = self.name_index.get(normalized)
            status = self.status_by_id.get(actress_id, "none")
            if status == "blacklist":
                black_names.append(raw_name)
            # 宁可少删：同一个人既在档案黑名单、又命中关键词白名单时，按受保护算
            if (
                status == "whitelist"
                or normalized in self.protected_terms
                or actress_id in self._keyword_protected_ids
            ):
                protected_by.append(raw_name)
        kept = film.film_dir in self.kept_dirs
        return Verdict(
            deletable=bool(film.actor_names) and bool(black_names) and not protected_by and not kept,
            black_names=tuple(black_names),
            protected_by=tuple(protected_by),
            kept=kept,
        )


def skip_reason(verdict: Verdict) -> str:
    """执行删除时这部片被跳过的中文原因；可删的片子返回空串。"""
    if verdict.protected_by:
        return f"已受白名单保护：{'、'.join(verdict.protected_by)}"
    if verdict.kept:
        return "已标为保留"
    if not verdict.black_names:
        return "没有黑名单演员"
    return ""
