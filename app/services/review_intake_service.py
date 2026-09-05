from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import PurePath
import re
import unicodedata

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordHit
from app.models.review_intake import ReviewIntakeItem
from app.schemas.review_intake import ReviewKeywordCandidate
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text
from app.services.review_intake_candidates import extract_raw_candidates

VALID_BUCKETS = {"whitelist", "blacklist"}
VALID_STATUSES = {"pending", "approved", "dismissed"}

# 落库的候选数量上限：候选组承担"点它就能批准"的作用，提示组只负责
# 告诉用户"这条可以跳过"或"点了会被拒"，两者分开限量。
PICK_LIMIT = 9
HINT_LIMIT = 3
TOTAL_LIMIT = PICK_LIMIT + HINT_LIMIT


def _normalize_path(raw_path: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_path.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _path_hash(normalized_path: str) -> str:
    return hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()


def parse_keyword_candidates(payload: str | None) -> list[ReviewKeywordCandidate]:
    if not payload:
        return []
    try:
        raw_items = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_items, list):
        return []
    candidates: list[ReviewKeywordCandidate] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            candidates.append(ReviewKeywordCandidate.model_validate(item))
        except ValueError:
            continue
    return candidates


class ReviewIntakeService:
    def __init__(self, db: Session):
        self.db = db

    def create_or_update(
        self,
        *,
        bucket: str,
        raw_path: str,
        source: str,
        note: str | None,
        pattern: str,
        flags: str,
        group_index: int,
        limit: int,
    ) -> ReviewIntakeItem:
        bucket = self._validate_bucket(bucket)
        cleaned_path = raw_path.strip()
        if not cleaned_path:
            raise ValueError("raw_path is required")

        normalized_path = _normalize_path(cleaned_path)
        path_hash = _path_hash(normalized_path)
        candidates = self._extract_and_resolve_keywords(
            bucket=bucket,
            raw_path=cleaned_path,
            pattern=pattern,
            flags=flags,
            group_index=group_index,
            limit=limit,
        )
        candidates_json = json.dumps(
            [item.model_dump() for item in candidates],
            ensure_ascii=False,
        )

        item = self.db.scalar(
            select(ReviewIntakeItem).where(
                ReviewIntakeItem.bucket == bucket,
                ReviewIntakeItem.path_hash == path_hash,
            )
        )
        if item is None:
            item = ReviewIntakeItem(
                bucket=bucket,
                raw_path=cleaned_path,
                normalized_path=normalized_path,
                path_hash=path_hash,
                source=source,
                note=note,
                extracted_keywords_json=candidates_json,
                status="pending",
            )
            self.db.add(item)
        else:
            item.raw_path = cleaned_path
            item.normalized_path = normalized_path
            item.source = source
            if note is not None:
                item.note = note
            item.extracted_keywords_json = candidates_json
            if item.status == "dismissed":
                item.status = "pending"
                item.reviewed_at = None

        self.db.commit()
        self.db.refresh(item)
        return item

    def list_items(
        self,
        *,
        bucket: str | None,
        status: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ReviewIntakeItem], int]:
        stmt = select(ReviewIntakeItem)
        if bucket:
            stmt = stmt.where(ReviewIntakeItem.bucket == self._validate_bucket(bucket))
        if status:
            if status not in VALID_STATUSES:
                raise ValueError("status must be pending, approved, or dismissed")
            stmt = stmt.where(ReviewIntakeItem.status == status)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    ReviewIntakeItem.raw_path.ilike(pattern),
                    ReviewIntakeItem.approved_keyword.ilike(pattern),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = list(
            self.db.scalars(
                stmt.order_by(ReviewIntakeItem.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            ).all()
        )
        return items, total

    def summary(self) -> dict[str, int]:
        rows = self.db.execute(
            select(ReviewIntakeItem.bucket, ReviewIntakeItem.status, func.count())
            .group_by(ReviewIntakeItem.bucket, ReviewIntakeItem.status)
        ).all()
        result = {
            "whitelist_pending": 0,
            "blacklist_pending": 0,
            "whitelist_approved": 0,
            "blacklist_approved": 0,
            "whitelist_dismissed": 0,
            "blacklist_dismissed": 0,
        }
        for bucket, status, count in rows:
            key = f"{bucket}_{status}"
            if key in result:
                result[key] = int(count)
        return result

    def approve(self, *, item_id: int, keyword: str, note: str | None) -> ReviewIntakeItem:
        item = self.db.get(ReviewIntakeItem, item_id)
        if item is None:
            raise LookupError("待审核项不存在")
        if item.status == "approved":
            raise ValueError("待审核项已批准")

        cleaned_keyword = keyword.strip()
        normalized_keyword = normalize_keyword_text(cleaned_keyword)
        if len(normalized_keyword) < 2:
            raise ValueError("关键词太短")

        registry = KeywordRegistryService(self.db)
        existing = registry.find_entry_by_keyword(normalized_keyword)
        if existing is not None and existing.keyword_type != item.bucket:
            raise ValueError(
                f"关键词已存在于 {existing.keyword_type}，不能直接归入 {item.bucket}"
            )
        if existing is None:
            entry = registry.create_entry(
                canonical_name=cleaned_keyword,
                keyword_type=item.bucket,
                note=note,
                source="review_intake",
            )
        else:
            entry = existing

        source_folder_name = PurePath(item.normalized_path).name or item.normalized_path
        self.db.add(
            KeywordHit(
                raw_keyword=cleaned_keyword,
                normalized_keyword=normalized_keyword,
                keyword_entry_id=entry.id,
                canonical_name_snapshot=entry.canonical_name,
                source_path=item.raw_path,
                source_folder_name=source_folder_name,
                import_id=None,
                match_rule=None,
                match_source="review_intake",
            )
        )
        item.status = "approved"
        item.approved_keyword = cleaned_keyword
        item.approved_keyword_entry_id = entry.id
        item.reviewed_at = datetime.now(UTC)
        if note is not None:
            item.note = note
        self.db.commit()
        registry.sync_legacy_library()
        self.db.refresh(item)
        return item

    def dismiss(self, *, item_id: int, note: str | None) -> ReviewIntakeItem:
        item = self.db.get(ReviewIntakeItem, item_id)
        if item is None:
            raise LookupError("待审核项不存在")
        if item.status == "approved":
            raise ValueError("已批准的待审核项不能忽略")
        item.status = "dismissed"
        item.reviewed_at = datetime.now(UTC)
        if note is not None:
            item.note = note
        self.db.commit()
        self.db.refresh(item)
        return item

    def restore(self, *, item_id: int) -> ReviewIntakeItem:
        item = self.db.get(ReviewIntakeItem, item_id)
        if item is None:
            raise LookupError("待审核项不存在")
        if item.status == "approved":
            raise ValueError("已批准的待审核项不能恢复为待审")
        item.status = "pending"
        item.reviewed_at = None
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, *, item_id: int) -> bool:
        item = self.db.get(ReviewIntakeItem, item_id)
        if item is None:
            return False
        self.db.delete(item)
        self.db.commit()
        return True

    def _load_ignore_tokens(self, registry: KeywordRegistryService) -> set[str]:
        """一次性取出全部"忽略"类关键词，避免逐候选查库。"""
        entries, _total = registry.list_entries(keyword_type="ignore", status="active", limit=5000)
        return {entry.canonical_name_normalized for entry in entries}

    def _extract_and_resolve_keywords(
        self,
        *,
        bucket: str,
        raw_path: str,
        pattern: str,
        flags: str,
        group_index: int,
        limit: int,
    ) -> list[ReviewKeywordCandidate]:
        """切出候选词并标注它们与关键词库的关系。

        pattern / flags / group_index 为保持接口兼容而保留，已不再使用；
        limit 用作落库候选总数上限。
        """
        raw_candidates = extract_raw_candidates(raw_path)
        registry = KeywordRegistryService(self.db)
        ignore_tokens = self._load_ignore_tokens(registry)

        similar_map: dict[str, object] = {}
        pending_for_similar = [
            item.text
            for item in raw_candidates
            if normalize_keyword_text(item.text) not in ignore_tokens
        ]
        if pending_for_similar:
            for suggestion in registry.suggest_similar(
                pending_for_similar,
                threshold=0.75,
                limit=len(pending_for_similar),
                keyword_types=[bucket, "tag"],
            ):
                similar_map.setdefault(suggestion.keyword, suggestion)

        picks: list[ReviewKeywordCandidate] = []
        hints: list[ReviewKeywordCandidate] = []
        greyed: list[ReviewKeywordCandidate] = []

        for item in raw_candidates:
            normalized = normalize_keyword_text(item.text)

            if normalized in ignore_tokens:
                greyed.append(
                    ReviewKeywordCandidate(
                        keyword=item.text,
                        count=1,
                        source=item.source,
                        examples=[],
                        match_status="ignored",
                    )
                )
                continue

            existing = registry.find_entry_by_keyword(normalized)
            if existing is not None:
                status = "existing" if existing.keyword_type == bucket else "conflict"
                hints.append(
                    ReviewKeywordCandidate(
                        keyword=item.text,
                        count=1,
                        source=item.source,
                        examples=[],
                        match_status=status,
                        matched_entry_id=existing.id,
                        matched_canonical_name=existing.canonical_name,
                        matched_keyword_type=existing.keyword_type,
                    )
                )
                continue

            suggestion = similar_map.get(item.text)
            picks.append(
                ReviewKeywordCandidate(
                    keyword=item.text,
                    count=1,
                    source=item.source,
                    examples=[],
                    match_status="similar" if suggestion else "new",
                    matched_entry_id=getattr(suggestion, "matched_entry_id", None),
                    matched_canonical_name=getattr(suggestion, "matched_canonical_name", None),
                    similar_score=getattr(suggestion, "score", None),
                )
            )

        total_cap = max(1, min(limit, TOTAL_LIMIT))
        # 落库顺序必须是"候选组在前"：find_first_actionable_keyword 与前端
        # defaultKeyword 都取第一个可用词，提示组排前面会预填一个已存在的词。
        # 提示组排在灰标签之前，避免被大量已忽略片段挤掉冲突警告
        ordered = picks[:PICK_LIMIT] + hints[:HINT_LIMIT] + greyed
        return ordered[:total_cap]

    def _validate_bucket(self, bucket: str) -> str:
        if bucket not in VALID_BUCKETS:
            raise ValueError("bucket must be whitelist or blacklist")
        return bucket


def find_first_actionable_keyword(item: ReviewIntakeItem) -> str | None:
    candidates = parse_keyword_candidates(item.extracted_keywords_json)
    for candidate in candidates:
        if candidate.match_status in {"new", "similar", "existing"}:
            return candidate.keyword
    return candidates[0].keyword if candidates else None
