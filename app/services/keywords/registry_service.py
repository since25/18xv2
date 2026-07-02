from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import itertools
import json
import re
import unicodedata
from typing import Tuple

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.keywords import KeywordAlias, KeywordEntry, KeywordHit, KeywordLibraryEntry, KeywordOperationLog
from app.models.whitelist import WhitelistCandidate


def normalize_keyword_text(raw: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw or "")
    normalized = normalized.strip().replace("/", " ")
    normalized = re.sub(r"[_\-]+", " ", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff\s·]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def similarity_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    a = normalize_keyword_text(left).casefold()
    b = normalize_keyword_text(right).casefold()
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    # 子串包含补分：短串是长串子串时，按长度比给分
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 2 and shorter in longer:
        contain = len(shorter) / len(longer)
        return max(seq, contain)
    return seq


@dataclass(slots=True)
class SimilarKeywordSuggestion:
    keyword: str
    matched_entry_id: int
    matched_canonical_name: str
    score: float


@dataclass(slots=True)
class KeywordTreeHitSummary:
    keyword_entry_id: int
    canonical_name: str
    keyword_type: str
    status: str
    hit_count: int
    sample_paths: list[str]


class KeywordRegistryService:
    def __init__(self, db: Session):
        self.db = db

    def _log_operation(
        self,
        *,
        action: str,
        keyword_entry_id: int | None = None,
        related_keyword_entry_id: int | None = None,
        detail: dict | None = None,
    ) -> None:
        self.db.add(
            KeywordOperationLog(
                action=action,
                keyword_entry_id=keyword_entry_id,
                related_keyword_entry_id=related_keyword_entry_id,
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
            )
        )

    def _base_query(self) -> Select[tuple[KeywordEntry]]:
        return select(KeywordEntry).options(selectinload(KeywordEntry.aliases)).order_by(KeywordEntry.canonical_name.asc())

    def list_entries(self, *, keyword_type: str | None = None, status: str | None = None, query: str | None = None, skip: int = 0, limit: int = 20) -> tuple[list[KeywordEntry], int]:
        stmt = self._base_query()
        if keyword_type:
                    stmt = stmt.where(KeywordEntry.keyword_type == keyword_type)
        if status:
            stmt = stmt.where(KeywordEntry.status == status)
        if query:
            normalized = normalize_keyword_text(query)
            stmt = stmt.where(
                or_(
                    KeywordEntry.canonical_name_normalized.contains(normalized),
                    KeywordEntry.aliases.any(KeywordAlias.alias_normalized.contains(normalized)),
                )
            )

        # Get total count before applying limit and offset
        total_count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = self.db.scalar(total_count_stmt) or 0

        # Apply limit and offset for pagination
        stmt = stmt.offset(skip).limit(limit)

        return list(self.db.scalars(stmt).all()), total_count

    def create_entry(
        self,
        *,
        canonical_name: str,
        keyword_type: str,
        note: str | None = None,
        aliases: list[str] | None = None,
        source: str = "manual",
    ) -> KeywordEntry:
        entry = self.create_entry_no_commit(
            canonical_name=canonical_name,
            keyword_type=keyword_type,
            note=note,
            aliases=aliases,
            source=source,
        )
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def create_entry_no_commit(
        self,
        *,
        canonical_name: str,
        keyword_type: str,
        note: str | None = None,
        aliases: list[str] | None = None,
        source: str = "manual",
    ) -> KeywordEntry:
        normalized = normalize_keyword_text(canonical_name)
        existing = self.find_entry_by_keyword(normalized)
        if existing is not None:
            if aliases:
                self._add_aliases_no_commit(existing.id, aliases, source=source)
                self.db.flush()
            return existing
        entry = KeywordEntry(
            canonical_name=canonical_name.strip(),
            canonical_name_normalized=normalized,
            keyword_type=keyword_type,
            note=note,
        )
        self.db.add(entry)
        self.db.flush()
        self.db.add(
            KeywordAlias(
                keyword_entry_id=entry.id,
                alias=entry.canonical_name,
                alias_normalized=normalized,
                source="canonical",
                note="Auto-created from canonical name.",
            )
        )
        self.db.flush()
        if aliases:
            self._add_aliases_no_commit(entry.id, aliases, source=source)
        self._log_operation(
            action="create_entry",
            keyword_entry_id=entry.id,
            detail={
                "canonical_name": entry.canonical_name,
                "keyword_type": entry.keyword_type,
                "aliases": aliases or [],
                "source": source,
            },
        )
        self.db.flush()
        return entry

    def _add_aliases_no_commit(self, entry_id: int, aliases: list[str], *, source: str = "manual") -> list[KeywordAlias]:
        entry = self.db.get(KeywordEntry, entry_id)
        if entry is None:
            raise ValueError(f"KeywordEntry {entry_id} not found")
        created: list[KeywordAlias] = []
        for raw_alias in aliases:
            normalized = normalize_keyword_text(raw_alias)
            if len(normalized) < 2:
                continue
            existing = self.db.scalar(select(KeywordAlias).where(KeywordAlias.alias_normalized == normalized))
            if existing is not None:
                continue
            alias = KeywordAlias(
                keyword_entry_id=entry.id,
                alias=raw_alias.strip(),
                alias_normalized=normalized,
                source=source,
            )
            self.db.add(alias)
            created.append(alias)
        if created:
            self._log_operation(
                action="add_aliases",
                keyword_entry_id=entry.id,
                detail={"aliases": [alias.alias for alias in created], "source": source},
            )
            self.db.flush()
        return created

    def update_entry(
        self,
        entry_id: int,
        *,
        canonical_name: str | None = None,
        keyword_type: str | None = None,
        status: str | None = None,
        note: str | None = None,
    ) -> KeywordEntry:
        entry = self.db.scalar(select(KeywordEntry).where(KeywordEntry.id == entry_id).options(selectinload(KeywordEntry.aliases)))
        if entry is None:
            raise ValueError(f"KeywordEntry {entry_id} not found")
        if canonical_name:
            normalized = normalize_keyword_text(canonical_name)
            conflict = self.db.scalar(
                select(KeywordEntry).where(
                    KeywordEntry.canonical_name_normalized == normalized,
                    KeywordEntry.id != entry_id,
                )
            )
            if conflict is not None:
                raise ValueError(f"Canonical name already exists: {canonical_name}")
            entry.canonical_name = canonical_name.strip()
            entry.canonical_name_normalized = normalized
            existing_alias = self.db.scalar(select(KeywordAlias).where(KeywordAlias.alias_normalized == normalized))
            if existing_alias is None:
                self.db.add(
                    KeywordAlias(
                        keyword_entry_id=entry.id,
                        alias=entry.canonical_name,
                        alias_normalized=normalized,
                        source="canonical_update",
                    )
                )
            self.db.query(KeywordHit).filter(KeywordHit.keyword_entry_id == entry.id).update(
                {KeywordHit.canonical_name_snapshot: entry.canonical_name},
                synchronize_session=False,
            )
        if keyword_type:
            entry.keyword_type = keyword_type
        if status:
            entry.status = status
        if note is not None:
            entry.note = note
        self._log_operation(
            action="update_entry",
            keyword_entry_id=entry.id,
            detail={
                "canonical_name": entry.canonical_name,
                "keyword_type": entry.keyword_type,
                "status": entry.status,
                "note_updated": note is not None,
            },
        )
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def add_aliases(self, entry_id: int, aliases: list[str], *, source: str = "manual") -> list[KeywordAlias]:
        created = self._add_aliases_no_commit(entry_id, aliases, source=source)
        self.db.commit()
        return created

    def merge_entries(self, canonical_entry_id: int, merge_entry_ids: list[int], *, note: str | None = None) -> KeywordEntry:
        canonical = self.db.scalar(
            select(KeywordEntry).where(KeywordEntry.id == canonical_entry_id).options(selectinload(KeywordEntry.aliases))
        )
        if canonical is None:
            raise ValueError(f"KeywordEntry {canonical_entry_id} not found")
        merge_ids = [entry_id for entry_id in merge_entry_ids if entry_id != canonical_entry_id]
        entries = list(
            self.db.scalars(
                select(KeywordEntry).where(KeywordEntry.id.in_(merge_ids)).options(selectinload(KeywordEntry.aliases))
            ).all()
        )
        if len(entries) != len(merge_ids):
            raise ValueError("Some merge entries do not exist")
        existing_aliases = {alias.alias_normalized for alias in canonical.aliases}
        for entry in entries:
            moved_aliases: list[str] = []
            for alias in list(entry.aliases):
                if alias.alias_normalized in existing_aliases:
                    self.db.delete(alias)
                    continue
                canonical.aliases.append(alias)
                moved_aliases.append(alias.alias)
                existing_aliases.add(alias.alias_normalized)
            self.db.query(KeywordHit).filter(KeywordHit.keyword_entry_id == entry.id).update(
                {
                    KeywordHit.keyword_entry_id: canonical.id,
                    KeywordHit.canonical_name_snapshot: canonical.canonical_name,
                },
                synchronize_session=False,
            )
            if entry.note:
                suffix = f"\nMerged from #{entry.id}: {entry.canonical_name}"
                canonical.note = (canonical.note or note or "").rstrip() + suffix
            self._log_operation(
                action="merge_entry",
                keyword_entry_id=canonical.id,
                related_keyword_entry_id=entry.id,
                detail={
                    "canonical_name": canonical.canonical_name,
                    "merged_entry_name": entry.canonical_name,
                    "moved_aliases": moved_aliases,
                    "moved_alias_count": len(moved_aliases),
                },
            )
            self.db.delete(entry)
        if note:
            canonical.note = note
        self.db.commit()
        self.db.refresh(canonical)
        return canonical

    def record_hits(
        self,
        *,
        keywords: list[str],
        import_id: int | None,
        examples_by_keyword: dict[str, list[str]],
        source_folder_name_by_keyword: dict[str, str],
        match_rule: str | None,
        match_source: str,
        keyword_type: str,
    ) -> list[KeywordEntry]:
        entries: list[KeywordEntry] = []
        for raw_keyword in keywords:
            normalized = normalize_keyword_text(raw_keyword)
            if len(normalized) < 2:
                continue
            entry = self.find_entry_by_keyword(normalized)
            if entry is None:
                entry = self.create_entry(
                    canonical_name=raw_keyword,
                    keyword_type=keyword_type,
                    source=match_source,
                )
            examples = examples_by_keyword.get(raw_keyword) or []
            source_folder_name = source_folder_name_by_keyword.get(raw_keyword) or raw_keyword
            for path in examples:
                hit = KeywordHit(
                    raw_keyword=raw_keyword,
                    normalized_keyword=normalized,
                    keyword_entry_id=entry.id,
                    canonical_name_snapshot=entry.canonical_name,
                    source_path=path,
                    source_folder_name=source_folder_name,
                    import_id=import_id,
                    match_rule=match_rule,
                    match_source=match_source,
                )
                self.db.add(hit)
            entries.append(entry)
        self.db.commit()
        return entries

    def list_operation_logs(self, *, keyword_entry_id: int | None = None, limit: int = 100) -> list[KeywordOperationLog]:
        stmt = select(KeywordOperationLog).order_by(KeywordOperationLog.id.desc()).limit(limit)
        if keyword_entry_id is not None:
            stmt = stmt.where(
                or_(
                    KeywordOperationLog.keyword_entry_id == keyword_entry_id,
                    KeywordOperationLog.related_keyword_entry_id == keyword_entry_id,
                )
            )
        return list(self.db.scalars(stmt).all())

    def find_entry_by_keyword(self, keyword: str) -> KeywordEntry | None:
        normalized = normalize_keyword_text(keyword)
        return self.db.scalar(
            select(KeywordEntry)
            .where(
                or_(
                    KeywordEntry.canonical_name_normalized == normalized,
                    KeywordEntry.aliases.any(KeywordAlias.alias_normalized == normalized),
                )
            )
            .options(selectinload(KeywordEntry.aliases))
        )

    def list_hits(
        self,
        *,
        import_id: int | None = None,
        keyword_entry_id: int | None = None,
        limit: int = 100,
    ) -> list[KeywordHit]:
        stmt = select(KeywordHit).order_by(KeywordHit.id.desc()).limit(limit)
        if import_id is not None:
            stmt = stmt.where(KeywordHit.import_id == import_id)
        if keyword_entry_id is not None:
            stmt = stmt.where(KeywordHit.keyword_entry_id == keyword_entry_id)
        return list(self.db.scalars(stmt).all())

    def suggest_similar(
        self,
        keywords: list[str],
        *,
        threshold: float = 0.75,
        limit: int = 20,
        keyword_types: list[str] | None = None,
    ) -> list[SimilarKeywordSuggestion]:
        entries, _total = self.list_entries(status="active")
        if keyword_types:
            entries = [entry for entry in entries if entry.keyword_type in set(keyword_types)]
        suggestions: list[SimilarKeywordSuggestion] = []
        for keyword in keywords:
            normalized = normalize_keyword_text(keyword)
            if len(normalized) < 2:
                continue
            for entry in entries:
                score = similarity_score(normalized, entry.canonical_name_normalized)
                if score >= threshold and entry.canonical_name_normalized != normalized:
                    suggestions.append(
                        SimilarKeywordSuggestion(
                            keyword=keyword,
                            matched_entry_id=entry.id,
                            matched_canonical_name=entry.canonical_name,
                            score=score,
                        )
                    )
        suggestions.sort(key=lambda item: (-item.score, item.keyword, item.matched_canonical_name))
        return suggestions[:limit]

    def summarize_tree_hits(
        self,
        *,
        import_id: int | None = None,
        tree_path: str | None = None,
        keyword_type: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[KeywordTreeHitSummary]:
        stmt = (
            select(KeywordHit)
            .join(KeywordEntry, KeywordEntry.id == KeywordHit.keyword_entry_id)
            .options(selectinload(KeywordHit.entry))
            .order_by(KeywordHit.id.desc())
        )
        if import_id is not None:
            stmt = stmt.where(KeywordHit.import_id == import_id)
        if tree_path:
            normalized_tree_path = tree_path.strip().strip("/")
            if normalized_tree_path:
                stmt = stmt.where(KeywordHit.source_path.startswith(normalized_tree_path))
        if keyword_type:
            stmt = stmt.where(KeywordEntry.keyword_type == keyword_type)
        if status:
            stmt = stmt.where(KeywordEntry.status == status)
        if query:
            normalized = normalize_keyword_text(query)
            stmt = stmt.where(
                or_(
                    KeywordEntry.canonical_name_normalized.contains(normalized),
                    KeywordEntry.aliases.any(KeywordAlias.alias_normalized.contains(normalized)),
                )
            )

        grouped: dict[int, KeywordTreeHitSummary] = {}
        for hit in self.db.scalars(stmt).all():
            if hit.keyword_entry_id is None or hit.entry is None:
                continue
            summary = grouped.get(hit.keyword_entry_id)
            if summary is None:
                grouped[hit.keyword_entry_id] = KeywordTreeHitSummary(
                    keyword_entry_id=hit.keyword_entry_id,
                    canonical_name=hit.entry.canonical_name,
                    keyword_type=hit.entry.keyword_type,
                    status=hit.entry.status,
                    hit_count=1,
                    sample_paths=[hit.source_path],
                )
                continue
            summary.hit_count += 1
            if hit.source_path not in summary.sample_paths and len(summary.sample_paths) < 3:
                summary.sample_paths.append(hit.source_path)

        items = list(grouped.values())
        items.sort(key=lambda item: (-item.hit_count, item.canonical_name))
        return items[:limit]

    def sync_legacy_library(self) -> None:
        entries, _ = self.list_entries(limit=5000)
        expected_keys: set[tuple[str, str]] = set()
        existing_rows = list(self.db.scalars(select(KeywordLibraryEntry)).all())
        existing = {(item.list_type, item.keyword_normalized): item for item in existing_rows}
        for entry in entries:
            list_type = entry.keyword_type if entry.keyword_type in {"whitelist", "blacklist", "ignore"} else "tag"
            key = (list_type, entry.canonical_name_normalized)
            expected_keys.add(key)
            if key in existing:
                existing[key].keyword = entry.canonical_name
                existing[key].note = entry.note
                continue
            self.db.add(
                KeywordLibraryEntry(
                    keyword=entry.canonical_name,
                    keyword_normalized=entry.canonical_name_normalized,
                    list_type=list_type,
                    source="registry_sync",
                    note="Synced from keyword_entries.",
                )
            )
        for key, row in existing.items():
            if key not in expected_keys:
                self.db.delete(row)
        self.db.commit()

    def delete_entry(self, entry_id: int) -> bool:
        entry = self.db.get(KeywordEntry, entry_id)
        if entry is None:
            return False
        self._log_operation(
            action="delete_entry",
            keyword_entry_id=entry.id,
            detail={"canonical_name": entry.canonical_name, "keyword_type": entry.keyword_type},
        )
        self.db.query(KeywordHit).filter(KeywordHit.keyword_entry_id == entry_id).update(
            {
                KeywordHit.keyword_entry_id: None,
                KeywordHit.canonical_name_snapshot: entry.canonical_name,
            },
            synchronize_session=False,
        )
        self.db.query(WhitelistCandidate).filter(
            WhitelistCandidate.matched_keyword_entry_id == entry_id
        ).delete(synchronize_session=False)
        self.db.delete(entry)
        self.db.commit()
        return True

    def scan_duplicate_keywords(
        self,
        *,
        keyword_type: str | None = None,
        status: str | None = "active",
        threshold: float = 0.85,
    ) -> list[tuple[KeywordEntry, KeywordEntry, float]]:
        entries, _ = self.list_entries(keyword_type=keyword_type, status=status, limit=5000)
        results: list[tuple[KeywordEntry, KeywordEntry, float]] = []
        for a, b in itertools.combinations(entries, 2):
            score = self._entry_similarity_score(a, b)
            if score >= threshold:
                results.append((a, b, score))
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    @staticmethod
    def _entry_similarity_terms(entry: KeywordEntry) -> list[str]:
        terms = [entry.canonical_name_normalized]
        terms.extend(alias.alias_normalized for alias in entry.aliases)

        deduped: list[str] = []
        seen: set[str] = set()
        for term in terms:
            normalized = normalize_keyword_text(term)
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _entry_similarity_score(self, left: KeywordEntry, right: KeywordEntry) -> float:
        left_terms = self._entry_similarity_terms(left)
        right_terms = self._entry_similarity_terms(right)
        if not left_terms or not right_terms:
            return 0.0
        # 任意归一化词相同 → 完全匹配
        if set(left_terms) & set(right_terms):
            return 1.0
        return max(
            similarity_score(left_term, right_term)
            for left_term in left_terms
            for right_term in right_terms
        )
