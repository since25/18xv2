from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.keywords import KeywordEntry
from app.services.keywords.registry_service import normalize_keyword_text


def build_keyword_index(db: Session) -> dict[str, int]:
    """构建当前启用白名单关键词的无歧义归一化索引。"""
    entries = db.scalars(
        select(KeywordEntry)
        .where(KeywordEntry.keyword_type == "whitelist", KeywordEntry.status == "active")
        .options(selectinload(KeywordEntry.aliases))
    ).all()
    candidates: dict[str, set[int]] = {}
    for entry in entries:
        terms = [entry.canonical_name, entry.canonical_name_normalized]
        terms.extend(alias.alias for alias in entry.aliases)
        terms.extend(alias.alias_normalized for alias in entry.aliases)
        for raw_term in terms:
            normalized = normalize_keyword_text(raw_term)
            if not normalized:
                continue
            candidates.setdefault(normalized, set()).add(entry.id)
    return {term: next(iter(entry_ids)) for term, entry_ids in candidates.items() if len(entry_ids) == 1}


def split_folder_terms(folder_name: str) -> list[str]:
    """按双下划线拆分原始目录名，并去除空段。"""
    return [term for term in folder_name.split("__") if term]


def match_local_folder(folder_name: str, index: dict[str, int]) -> list[tuple[int, str]]:
    """精确匹配本地目录的关键词，按目录段顺序去重。"""
    matches: list[tuple[int, str]] = []
    seen_ids: set[int] = set()
    for raw_term in split_folder_terms(folder_name):
        keyword_entry_id = index.get(normalize_keyword_text(raw_term))
        if keyword_entry_id is None or keyword_entry_id in seen_ids:
            continue
        seen_ids.add(keyword_entry_id)
        matches.append((keyword_entry_id, raw_term))
    return matches


def match_strm_item(
    actor_names: list[str] | None,
    folder_name: str,
    index: dict[str, int],
) -> tuple[list[tuple[int, str, str]], str]:
    """先匹配 NFO 演员，未命中时回退到顶层目录。"""
    if actor_names is not None:
        actor_matches: list[tuple[int, str, str]] = []
        seen_ids: set[int] = set()
        for raw_actor in actor_names:
            keyword_entry_id = index.get(normalize_keyword_text(raw_actor))
            if keyword_entry_id is None or keyword_entry_id in seen_ids:
                continue
            seen_ids.add(keyword_entry_id)
            actor_matches.append((keyword_entry_id, raw_actor, "nfo_actor"))
        if actor_matches:
            return actor_matches, "matched"

    fallback = [
        (keyword_entry_id, raw_term, "folder_fallback")
        for keyword_entry_id, raw_term in match_local_folder(folder_name, index)
    ]
    if actor_names is None:
        return fallback, "nfo_error"
    if fallback:
        return fallback, "matched"
    return [], "unmatched"
