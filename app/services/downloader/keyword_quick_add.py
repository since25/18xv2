"""下载器收件箱：把搜索词一键加入白名单 / 黑名单，并立即重算受影响的资源包。

预览（dry_run）与正式执行走同一套流程，预览最后回滚，保证预览数字与实际一致。
"""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.downloader import DownloaderPackage
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.downloader.sync_service import _load_terms, _match_package
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

_TYPE_LABELS = {"whitelist": "白名单", "blacklist": "黑名单"}
_SAMPLE_LIMIT = 5


class KeywordQuickAddError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _find_entry_ignore_case(db: Session, normalized: str) -> KeywordEntry | None:
    """按正名或别名查找关键词，忽略大小写（下载器匹配本身就不分大小写）。"""
    lowered = normalized.lower()
    return db.scalar(
        select(KeywordEntry)
        .where(
            or_(
                func.lower(KeywordEntry.canonical_name_normalized) == lowered,
                KeywordEntry.aliases.any(func.lower(KeywordAlias.alias_normalized) == lowered),
            )
        )
        .order_by(KeywordEntry.id)
        .limit(1)
    )


def quick_add_keyword(
    db: Session,
    *,
    keyword: str,
    list_type: Literal["whitelist", "blacklist"],
    dry_run: bool,
) -> dict[str, Any]:
    """加入关键词并重算标题包含该词的资源包。

    约定：调用方会话不能有未提交改动，dry_run 会整体回滚。
    """
    normalized = normalize_keyword_text(keyword)
    if len(normalized) < 2:
        raise KeywordQuickAddError("关键词至少需要 2 个字符", 400)

    registry = KeywordRegistryService(db)
    existing = _find_entry_ignore_case(db, normalized)
    if existing is not None and existing.keyword_type != list_type:
        current = _TYPE_LABELS.get(existing.keyword_type, existing.keyword_type)
        raise KeywordQuickAddError(
            f"「{existing.canonical_name}」已在{current}中，请到关键词页修改类型", 409
        )
    if existing is not None and existing.status != "active":
        raise KeywordQuickAddError(f"「{existing.canonical_name}」已停用，请到关键词页启用", 409)

    try:
        if existing is None:
            entry = registry.create_entry_no_commit(
                canonical_name=keyword.strip(),
                keyword_type=list_type,
                merge_policy="normal",
                note="下载器收件箱一键加入",
                source="downloader_quick_add",
            )
            entry_status = "created"
        else:
            entry = existing
            entry_status = "existing"
        db.flush()
        entry_id = entry.id

        whitelist_terms, blacklist_terms = _load_terms(db)
        term = normalized.casefold()
        affected = [
            package
            for package in db.scalars(select(DownloaderPackage).order_by(DownloaderPackage.id)).all()
            if term in normalize_keyword_text(package.title or "").casefold()
        ]
        created = dismissed = 0
        for package in affected:
            created_now, dismissed_now = _match_package(db, package, whitelist_terms, blacklist_terms)
            created += created_now
            dismissed += dismissed_now
        sample_titles = [package.title for package in affected[:_SAMPLE_LIMIT]]
    except Exception:
        db.rollback()
        raise

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "keyword": keyword.strip(),
        "list_type": list_type,
        "entry_status": entry_status,
        "keyword_entry_id": None if dry_run else entry_id,
        "packages_affected": len(affected),
        "candidates_created": created,
        "candidates_dismissed": dismissed,
        "sample_titles": sample_titles,
    }
