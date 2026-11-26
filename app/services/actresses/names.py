"""女优名字的归一化与比对。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import Actress, ActressAlias
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.keywords.registry_service import normalize_keyword_text

# 演员名命中这两类启用中的关键词（规范名或别名）就受保护，不进删除候选
PROTECTED_KEYWORD_TYPES = ("whitelist", "emby_whitelist")


def normalize_actress_name(raw: str) -> str:
    """在关键词归一化（全半角统一、去标点）的基础上再去掉全部空格。

    「甲 乙」和「甲乙」视为同一个人。
    """
    return normalize_keyword_text(raw).replace(" ", "")


def build_name_index(db: Session) -> dict[str, int]:
    """全部女优的规范名和别名（都是归一化后的写法）→ 女优 id。"""
    index: dict[str, int] = {}
    for actress_id, normalized in db.execute(select(Actress.id, Actress.canonical_name_normalized)):
        index[normalized] = actress_id
    for actress_id, normalized in db.execute(select(ActressAlias.actress_id, ActressAlias.alias_normalized)):
        # 档案服务保证名字在全部女优之间唯一；万一撞名，以规范名为准
        index.setdefault(normalized, actress_id)
    return index


def build_protected_terms(db: Session) -> set[str]:
    """启用中的 `whitelist` / `emby_whitelist` 关键词的规范名和别名，按女优名规则归一化后的集合。

    关键词表只读，不在这里写入任何东西。
    """
    protected_entry = (KeywordEntry.keyword_type.in_(PROTECTED_KEYWORD_TYPES), KeywordEntry.status == "active")
    names = list(db.scalars(select(KeywordEntry.canonical_name).where(*protected_entry)))
    names += db.scalars(
        select(KeywordAlias.alias).join(KeywordEntry, KeywordEntry.id == KeywordAlias.keyword_entry_id).where(
            *protected_entry
        )
    )
    return {normalized for normalized in map(normalize_actress_name, names) if normalized}
