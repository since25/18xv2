"""标题和种子文件名的黑名单命中。"""

from __future__ import annotations

import re
import unicodedata


# (显示词, 归一后的词)
Term = tuple[str, str]

_SPACE_RE = re.compile(r"[ \t　]+")


def normalize(text: str) -> str:
    """NFKC（全角转半角）→ 去掉半角/全角空格和制表符 → 不分大小写。"""
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", text or "")).casefold()


def find_hit(text: str, terms: list[Term]) -> str | None:
    """返回命中的黑名单词（显示形式）；多个命中取最长的，同样长取靠前的。"""
    normalized = normalize(text)
    best: Term | None = None
    for display, term in terms:
        if not term or term not in normalized:
            continue
        if best is None or len(term) > len(best[1]):
            best = (display, term)
    return best[0] if best is not None else None
