"""女优名字的归一化与比对。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import Actress, ActressAlias
from app.services.keywords.registry_service import normalize_keyword_text


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
