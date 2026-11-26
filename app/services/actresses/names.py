"""女优名字的归一化与比对。"""

from __future__ import annotations

from app.services.keywords.registry_service import normalize_keyword_text


def normalize_actress_name(raw: str) -> str:
    """在关键词归一化（全半角统一、去标点）的基础上再去掉全部空格。

    「三上 悠亜」和「三上悠亜」视为同一个人。
    """
    return normalize_keyword_text(raw).replace(" ", "")
