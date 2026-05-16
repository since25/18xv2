from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models.keywords import KeywordEntry, KeywordHit
from app.models.tree import NodeFile, TreeImport, TreeNode
from app.services.keywords.registry_service import normalize_keyword_text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KeywordHitRebuildResult:
    import_id: int
    deleted_count: int
    created_count: int
    scanned_folder_count: int
    scanned_file_count: int
    matched_keyword_count: int


@dataclass(slots=True)
class _ResourceItem:
    raw_name: str
    raw_path: str
    kind: str


@dataclass(slots=True)
class _AliasMatcher:
    entry_id: int
    canonical_name: str
    alias: str
    normalized_alias: str


class KeywordHitRebuildService:
    MATCH_SOURCE = "registry_rebuild"
    INSERT_BATCH_SIZE = 1000
    LOG_PROGRESS_EVERY = 2000

    def __init__(self, db: Session):
        self.db = db

    def rebuild_import_hits(
        self,
        *,
        import_id: int,
        include_files: bool = True,
        include_folders: bool = True,
        replace_existing: bool = True,
    ) -> KeywordHitRebuildResult:
        tree_import = self.db.get(TreeImport, import_id)
        if tree_import is None:
            raise ValueError(f"TreeImport {import_id} not found")
        if not include_files and not include_folders:
            raise ValueError("At least one of include_files/include_folders must be enabled")

        deleted_count = 0
        if replace_existing:
            deleted_count = self._delete_existing_hits(import_id=import_id)

        entries = list(
            self.db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.status == "active")
                .where(KeywordEntry.keyword_type != "ignore")
                .options(selectinload(KeywordEntry.aliases))
                .order_by(KeywordEntry.id.asc())
            ).all()
        )
        matchers, combined_pattern = self._build_matchers(entries)
        logger.info(
            "keyword hit rebuild started: import_id=%s include_folders=%s include_files=%s entries=%s aliases=%s",
            import_id,
            include_folders,
            include_files,
            len(entries),
            len(matchers),
        )

        resources: list[_ResourceItem] = []
        scanned_folder_count = 0
        scanned_file_count = 0

        if include_folders:
            folder_rows = list(
                self.db.scalars(
                    select(TreeNode)
                    .where(TreeNode.import_id == import_id)
                    .where(TreeNode.node_type == "folder")
                    .order_by(TreeNode.id.asc())
                ).all()
            )
            scanned_folder_count = len(folder_rows)
            resources.extend(_ResourceItem(raw_name=row.raw_name, raw_path=row.raw_path, kind="folder") for row in folder_rows)

        if include_files:
            file_rows = list(
                self.db.scalars(select(NodeFile).where(NodeFile.import_id == import_id).order_by(NodeFile.id.asc())).all()
            )
            scanned_file_count = len(file_rows)
            resources.extend(_ResourceItem(raw_name=row.raw_name, raw_path=row.raw_path, kind="file") for row in file_rows)

        created_count = 0
        matched_keyword_ids: set[int] = set()
        pending_rows: list[dict[str, object]] = []

        for index, resource in enumerate(resources, start=1):
            normalized_name = self._normalize_match_text(resource.raw_name)
            matched = self._find_matched_aliases(
                combined_pattern=combined_pattern,
                matchers=matchers,
                normalized_name=normalized_name,
            )
            for entry_id, matcher in matched.items():
                matched_keyword_ids.add(entry_id)
                pending_rows.append(
                    {
                        "raw_keyword": matcher.alias,
                        "normalized_keyword": normalize_keyword_text(matcher.alias),
                        "keyword_entry_id": matcher.entry_id,
                        "canonical_name_snapshot": matcher.canonical_name,
                        "source_path": resource.raw_path,
                        "source_folder_name": resource.raw_name,
                        "import_id": import_id,
                        "match_rule": f"{resource.kind}:contains:{matcher.alias}",
                        "match_source": self.MATCH_SOURCE,
                    }
                )
                created_count += 1
            if pending_rows and len(pending_rows) >= self.INSERT_BATCH_SIZE:
                self._flush_hits(pending_rows)
                pending_rows.clear()
            if index % self.LOG_PROGRESS_EVERY == 0:
                logger.info(
                    "keyword hit rebuild progress: import_id=%s processed=%s/%s created=%s matched_keywords=%s",
                    import_id,
                    index,
                    len(resources),
                    created_count,
                    len(matched_keyword_ids),
                )

        if pending_rows:
            self._flush_hits(pending_rows)
        self.db.commit()
        logger.info(
            "keyword hit rebuild finished: import_id=%s created=%s deleted=%s scanned_folders=%s scanned_files=%s matched_keywords=%s",
            import_id,
            created_count,
            deleted_count,
            scanned_folder_count,
            scanned_file_count,
            len(matched_keyword_ids),
        )
        return KeywordHitRebuildResult(
            import_id=import_id,
            deleted_count=deleted_count,
            created_count=created_count,
            scanned_folder_count=scanned_folder_count,
            scanned_file_count=scanned_file_count,
            matched_keyword_count=len(matched_keyword_ids),
        )

    def _delete_existing_hits(self, *, import_id: int) -> int:
        existing_ids = list(
            self.db.scalars(
                select(KeywordHit.id)
                .where(KeywordHit.import_id == import_id)
                .where(KeywordHit.match_source == self.MATCH_SOURCE)
            ).all()
        )
        if not existing_ids:
            return 0
        self.db.execute(delete(KeywordHit).where(KeywordHit.id.in_(existing_ids)))
        self.db.flush()
        return len(existing_ids)

    def _flush_hits(self, rows: list[dict[str, object]]) -> None:
        self.db.bulk_insert_mappings(KeywordHit, rows)
        self.db.flush()

    @staticmethod
    def _normalize_match_text(raw: str) -> str:
        return unicodedata.normalize("NFKC", raw or "").casefold()

    @staticmethod
    def _build_matchers(entries: list[KeywordEntry]) -> tuple[dict[str, _AliasMatcher], re.Pattern[str] | None]:
        matchers: dict[str, _AliasMatcher] = {}
        candidates: list[str] = []
        for entry in entries:
            raw_candidates = [entry.canonical_name]
            raw_candidates.extend(alias.alias for alias in entry.aliases)
            for alias in raw_candidates:
                normalized_alias = KeywordHitRebuildService._normalize_match_text(alias)
                if len(normalized_alias) < 2 or normalized_alias in matchers:
                    continue
                matchers[normalized_alias] = _AliasMatcher(
                    entry_id=entry.id,
                    canonical_name=entry.canonical_name,
                    alias=alias,
                    normalized_alias=normalized_alias,
                )
                candidates.append(normalized_alias)
        if not candidates:
            return matchers, None
        candidates.sort(key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(item) for item in candidates))
        return matchers, pattern

    @staticmethod
    def _find_matched_aliases(
        *,
        combined_pattern: re.Pattern[str] | None,
        matchers: dict[str, _AliasMatcher],
        normalized_name: str,
    ) -> dict[int, _AliasMatcher]:
        if combined_pattern is None:
            return {}
        matched_by_entry: dict[int, _AliasMatcher] = {}
        if not normalized_name:
            return matched_by_entry
        for match in combined_pattern.finditer(normalized_name):
            normalized_alias = match.group(0)
            matcher = matchers.get(normalized_alias)
            if matcher is None:
                continue
            existing = matched_by_entry.get(matcher.entry_id)
            if existing is None or len(matcher.normalized_alias) > len(existing.normalized_alias):
                matched_by_entry[matcher.entry_id] = matcher
        return matched_by_entry

    @staticmethod
    def _find_matched_alias(entry: KeywordEntry, *, normalized_name: str, normalized_path: str) -> str | None:
        candidates = [entry.canonical_name]
        candidates.extend(alias.alias for alias in entry.aliases)
        normalized_candidates: list[tuple[str, str]] = []
        for alias in candidates:
            normalized_alias = KeywordHitRebuildService._normalize_match_text(alias)
            if len(normalized_alias) < 2:
                continue
            normalized_candidates.append((alias, normalized_alias))
        normalized_candidates.sort(key=lambda item: len(item[1]), reverse=True)
        for alias, normalized_alias in normalized_candidates:
            if normalized_alias in normalized_name or normalized_alias in normalized_path:
                return alias
        return None
