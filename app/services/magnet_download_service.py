from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import PurePosixPath
import re
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.keywords import KeywordAlias, KeywordEntry
from app.models.tasks import MagnetDownloadTask
from app.models.tree import NodeFile, TreeImport, TreeNode
from app.schemas.magnet_tasks import (
    ArticleCandidateResponse,
    DuplicateCheckItemRequest,
    DuplicateCheckItemResponse,
    MagnetTaskCreateItem,
)
from app.services.client_115.client import Client115Error, Fake115Client, Real115Client
from app.services.client_115.schemas import NodePayload
from app.services.source_article_db import ArticleRecord, SourceArticleDatabaseService
from app.services.tasks.organize_task_service import OrganizeTaskService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DuplicateCheckResult:
    status: str
    reason: str | None
    search_terms: list[str]
    matched_terms: list[str]
    matched_import_id: int | None
    matched_import_label: str | None
    matched_nodes: list[NodePayload]


@dataclass(slots=True)
class _LocalTreeMatch:
    score: float
    matched_terms: list[str]
    matched_import_id: int
    matched_import_label: str
    matched_nodes: list[NodePayload]
    reason: str


@dataclass(slots=True)
class _LocalTreeEntry:
    entry_id: int
    raw_name: str
    raw_path: str
    is_file: bool
    code_terms: frozenset[str]
    text_terms: frozenset[str]


@dataclass(slots=True)
class _LocalTreeIndex:
    import_id: int
    import_label: str
    entries: list[_LocalTreeEntry]
    code_lookup: dict[str, set[int]]
    text_lookup: dict[str, set[int]]


class MagnetDownloadService:
    code_pattern = re.compile(r"\b([A-Za-z]{2,10})[-_ ]?(\d{2,5})\b")
    token_pattern = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
    stop_terms = {
        "the",
        "and",
        "for",
        "with",
        "vol",
        "volume",
        "part",
        "cd",
        "collection",
        "complete",
        "newcomer",
        "sample",
        "中字",
        "中字版",
        "中文字幕",
        "完整版",
        "合集",
        "新作",
        "流出",
        "破解",
        "uncensored",
        "1080p",
        "720p",
        "2160p",
        "4k",
    }

    def __init__(
        self,
        db: Session,
        *,
        article_db: SourceArticleDatabaseService | None = None,
        client_115: Real115Client | Fake115Client | None = None,
    ) -> None:
        self.db = db
        self.article_db = article_db or SourceArticleDatabaseService()
        self.client_115 = client_115
        self.settings = get_settings()
        self._local_tree_index_cache: dict[int, _LocalTreeIndex | None] = {}
        self._local_tree_match_cache: dict[tuple[int, tuple[str, ...]], DuplicateCheckResult] = {}

    def build_candidates(
        self,
        *,
        query: str,
        keyword_entry_id: int | None = None,
        limit: int | None = None,
    ) -> list[ArticleCandidateResponse]:
        matched_keyword: str | None = None
        matched_alias: str | None = None
        search_terms = [query]
        if keyword_entry_id is not None:
            entry = self.db.scalar(select(KeywordEntry).where(KeywordEntry.id == keyword_entry_id))
            if entry is None:
                raise ValueError(f"KeywordEntry {keyword_entry_id} not found")
            matched_keyword = entry.canonical_name
            alias = self.db.scalar(
                select(KeywordAlias)
                .where(KeywordAlias.keyword_entry_id == keyword_entry_id)
                .where(KeywordAlias.alias_normalized == normalize_keyword_text(query))
            )
            matched_alias = alias.alias if alias is not None else (query if query != entry.canonical_name else None)
            search_terms = [term for term in [query, entry.canonical_name] if term]

        scored_by_tid: dict[int, tuple[ArticleRecord, float]] = {}
        for term in search_terms:
            scored = self.article_db.score_articles(
                term,
                matched_keyword=matched_keyword,
                matched_alias=matched_alias,
                limit=limit,
            )
            for record, score in scored:
                existing = scored_by_tid.get(record.tid)
                if existing is None or score > existing[1]:
                    scored_by_tid[record.tid] = (record, score)
        merged_scored = sorted(scored_by_tid.values(), key=lambda item: (item[1], item[0].tid), reverse=True)
        if limit is not None:
            merged_scored = merged_scored[:limit]
        return [
            ArticleCandidateResponse(
                source_tid=record.tid,
                source_title=record.title,
                source_magnet=record.magnet,
                source_detail_url=record.detail_url,
                source_section=record.section,
                source_category=record.category,
                source_sub_type=record.sub_type,
                source_size=record.size,
                matched_keyword=matched_keyword or query,
                matched_alias=matched_alias,
                match_score=round(score, 4),
            )
            for record, score in merged_scored
        ]

    def build_candidates_for_keyword_entry(
        self,
        *,
        keyword_entry: KeywordEntry,
        limit: int | None = None,
    ) -> list[ArticleCandidateResponse]:
        terms: list[tuple[str, str | None]] = [(keyword_entry.canonical_name, None)]
        aliases = self.db.scalars(
            select(KeywordAlias)
            .where(KeywordAlias.keyword_entry_id == keyword_entry.id)
            .order_by(KeywordAlias.id.asc())
        ).all()
        seen_terms = {normalize_keyword_text(keyword_entry.canonical_name)}
        for alias in aliases:
            normalized = normalize_keyword_text(alias.alias)
            if not normalized or normalized in seen_terms:
                continue
            seen_terms.add(normalized)
            terms.append((alias.alias, alias.alias))

        scored_by_tid: dict[int, tuple[ArticleRecord, float, str | None]] = {}
        for term, alias_value in terms:
            scored = self.article_db.score_articles(
                term,
                matched_keyword=keyword_entry.canonical_name,
                matched_alias=alias_value,
                limit=limit,
            )
            for record, score in scored:
                existing = scored_by_tid.get(record.tid)
                if existing is None or score > existing[1]:
                    scored_by_tid[record.tid] = (record, score, alias_value)

        merged_scored = sorted(scored_by_tid.values(), key=lambda item: (item[1], item[0].tid), reverse=True)
        if limit is not None:
            merged_scored = merged_scored[:limit]
        return [
            ArticleCandidateResponse(
                source_tid=record.tid,
                source_title=record.title,
                source_magnet=record.magnet,
                source_detail_url=record.detail_url,
                source_section=record.section,
                source_category=record.category,
                source_sub_type=record.sub_type,
                source_size=record.size,
                matched_keyword=keyword_entry.canonical_name,
                matched_alias=matched_alias,
                match_score=round(score, 4),
            )
            for record, score, matched_alias in merged_scored
        ]

    def check_duplicates(
        self,
        items: list[DuplicateCheckItemRequest],
        *,
        tree_import_id: int | None = None,
    ) -> list[DuplicateCheckItemResponse]:
        return [
            DuplicateCheckItemResponse(
                source_tid=item.source_tid,
                duplicate_status=result.status,
                duplicate_reason=result.reason,
                search_terms=result.search_terms,
                matched_terms=result.matched_terms,
                matched_import_id=result.matched_import_id,
                matched_import_label=result.matched_import_label,
                matched_nodes=result.matched_nodes,
            )
            for item in items
            for result in [self.check_single_duplicate(item, tree_import_id=tree_import_id)]
        ]

    def check_single_duplicate(
        self,
        item: DuplicateCheckItemRequest,
        *,
        tree_import_id: int | None = None,
    ) -> DuplicateCheckResult:
        existing_task = self.db.scalar(select(MagnetDownloadTask).where(MagnetDownloadTask.source_tid == item.source_tid))
        if existing_task is not None:
            return DuplicateCheckResult(
                status="task_exists",
                reason=f"Task #{existing_task.id} already exists with status {existing_task.status}.",
                search_terms=[],
                matched_terms=[],
                matched_import_id=None,
                matched_import_label=None,
                matched_nodes=[],
            )

        search_terms = self._build_search_terms(item.source_title, item.matched_alias, item.matched_keyword)

        if tree_import_id is None:
            return DuplicateCheckResult(
                status="clear",
                reason="未选择目录树批次，已跳过重复检查。当前仅支持本地目录树匹配，不再调用 115 搜索接口。",
                search_terms=search_terms,
                matched_terms=[],
                matched_import_id=None,
                matched_import_label=None,
                matched_nodes=[],
            )

        return self._check_duplicate_local(search_terms, tree_import_id)

    def _check_duplicate_local(self, search_terms: list[str], tree_import_id: int) -> DuplicateCheckResult:
        tree_index = self._get_local_tree_index(tree_import_id)
        if tree_index is None:
            return DuplicateCheckResult(
                status="clear",
                reason=f"本地目录树 #{tree_import_id} 不存在",
                search_terms=search_terms,
                matched_terms=[],
                matched_import_id=None,
                matched_import_label=None,
                matched_nodes=[],
            )

        cache_key = (tree_import_id, tuple(search_terms))
        cached = self._local_tree_match_cache.get(cache_key)
        if cached is not None:
            return cached

        code_terms = self._extract_code_terms(search_terms)
        text_terms = self._extract_text_terms(search_terms)
        candidate_indexes: set[int] = set()
        for code in code_terms:
            candidate_indexes.update(tree_index.code_lookup.get(code, set()))
        for term in text_terms:
            candidate_indexes.update(tree_index.text_lookup.get(term, set()))

        if not code_terms and len(text_terms) < 2:
            candidate_indexes = set()

        matches: list[_LocalTreeMatch] = []
        for entry_index in sorted(candidate_indexes):
            match = self._score_local_index_entry(
                entry=tree_index.entries[entry_index],
                code_terms=code_terms,
                text_terms=text_terms,
                import_id=tree_index.import_id,
                import_label=tree_index.import_label,
            )
            if match is not None:
                matches.append(match)

        if not matches:
            result = DuplicateCheckResult(
                status="clear",
                reason=None,
                search_terms=search_terms,
                matched_terms=[],
                matched_import_id=None,
                matched_import_label=None,
                matched_nodes=[],
            )
            self._local_tree_match_cache[cache_key] = result
            return result

        matches.sort(key=lambda item: (-item.score, item.matched_nodes[0].path))
        best = matches[0]
        merged_nodes: list[NodePayload] = []
        seen_paths: set[str] = set()
        for match in matches[:5]:
            node = match.matched_nodes[0]
            if node.path in seen_paths:
                continue
            seen_paths.add(node.path)
            merged_nodes.append(node)

        result = DuplicateCheckResult(
            status="duplicate_found",
            reason=best.reason,
            search_terms=search_terms,
            matched_terms=best.matched_terms,
            matched_import_id=best.matched_import_id,
            matched_import_label=best.matched_import_label,
            matched_nodes=merged_nodes,
        )
        self._local_tree_match_cache[cache_key] = result
        return result

    def _build_search_terms(self, title: str, matched_alias: str | None, matched_keyword: str | None) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for matched in self.code_pattern.findall(title):
            candidate = f"{matched[0].upper()}-{matched[1]}"
            if candidate not in seen:
                seen.add(candidate)
                terms.append(candidate)
        for candidate in [matched_alias, matched_keyword, title]:
            if candidate:
                cleaned = candidate.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    terms.append(cleaned)
        return terms[:5]

    def _extract_code_terms(self, search_terms: list[str]) -> list[str]:
        codes: list[str] = []
        seen: set[str] = set()
        for term in search_terms:
            for prefix, number in self.code_pattern.findall(term):
                candidate = f"{prefix.upper()}-{number}"
                if candidate not in seen:
                    seen.add(candidate)
                    codes.append(candidate)
        return codes

    def _extract_text_terms(self, search_terms: list[str]) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for term in search_terms:
            normalized = self._normalize_match_text(term)
            for token in self.token_pattern.findall(normalized):
                if not self._is_meaningful_token(token):
                    continue
                if token not in seen:
                    seen.add(token)
                    tokens.append(token)
        return tokens

    def _normalize_match_text(self, value: str) -> str:
        from app.services.classifier.keyword_classifier import normalize_folder_name

        return normalize_folder_name(value).replace("-", " ").replace("_", " ")

    def _is_meaningful_token(self, token: str) -> bool:
        cleaned = token.strip().lower()
        if len(cleaned) < 2:
            return False
        if cleaned in self.stop_terms:
            return False
        if cleaned.isdigit() and len(cleaned) < 3:
            return False
        return True

    def _build_local_tree_entry(
        self,
        *,
        entry_id: int,
        raw_name: str,
        normalized_name: str,
        raw_path: str,
        is_file: bool,
    ) -> _LocalTreeEntry:
        haystack = " ".join(
            [
                self._normalize_match_text(normalized_name or raw_name),
                self._normalize_match_text(raw_path),
            ]
        ).strip()
        code_terms = frozenset(self._extract_code_terms([raw_name, normalized_name, raw_path]))
        text_terms = frozenset(
            token
            for token in self.token_pattern.findall(haystack)
            if self._is_meaningful_token(token)
        )
        return _LocalTreeEntry(
            entry_id=entry_id,
            raw_name=raw_name,
            raw_path=raw_path,
            is_file=is_file,
            code_terms=code_terms,
            text_terms=text_terms,
        )

    def _score_local_index_entry(
        self,
        *,
        entry: _LocalTreeEntry,
        code_terms: list[str],
        text_terms: list[str],
        import_id: int,
        import_label: str,
    ) -> _LocalTreeMatch | None:
        matched_codes = [code for code in code_terms if code in entry.code_terms]
        matched_text_terms = [term for term in text_terms if term in entry.text_terms]

        score = 0.0
        if matched_codes:
            score += 6.0 + len(matched_codes)
        for term in matched_text_terms:
            score += 1.5 if len(term) >= 4 else 1.0

        has_strong_text_match = len(matched_text_terms) >= 2 and score >= 2.5
        if not matched_codes and not has_strong_text_match:
            return None

        matched_terms = list(dict.fromkeys([*matched_codes, *matched_text_terms]))
        entry_kind = "文件" if entry.is_file else "目录"
        return _LocalTreeMatch(
            score=score,
            matched_terms=matched_terms,
            matched_import_id=import_id,
            matched_import_label=import_label,
            matched_nodes=[
                NodePayload(
                    id=str(entry.entry_id),
                    name=entry.raw_name,
                    path=entry.raw_path,
                    parent_id=None,
                    is_file=entry.is_file,
                )
            ],
            reason=(
                f"本地目录树 #{import_id}（{import_label}）命中{entry_kind}：{entry.raw_path}；"
                f"匹配词：{', '.join(matched_terms)}"
            ),
        )

    def _get_local_tree_index(self, tree_import_id: int) -> _LocalTreeIndex | None:
        cached = self._local_tree_index_cache.get(tree_import_id)
        if isinstance(cached, _LocalTreeIndex):
            return cached
        if cached is None and tree_import_id in self._local_tree_index_cache:
            return None

        tree_import = self.db.get(TreeImport, tree_import_id)
        if tree_import is None:
            self._local_tree_index_cache[tree_import_id] = None
            return None

        nodes = self.db.scalars(
            select(TreeNode).where(TreeNode.import_id == tree_import_id).order_by(TreeNode.depth.asc(), TreeNode.id.asc())
        ).all()
        files = self.db.scalars(
            select(NodeFile).where(NodeFile.import_id == tree_import_id).order_by(NodeFile.depth.asc(), NodeFile.id.asc())
        ).all()

        entries: list[_LocalTreeEntry] = []
        code_lookup: dict[str, set[int]] = {}
        text_lookup: dict[str, set[int]] = {}
        for item in [*nodes, *files]:
            entry = self._build_local_tree_entry(
                entry_id=item.id,
                raw_name=item.raw_name,
                normalized_name=item.normalized_name,
                raw_path=item.raw_path,
                is_file=isinstance(item, NodeFile),
            )
            entry_index = len(entries)
            entries.append(entry)
            for code in entry.code_terms:
                code_lookup.setdefault(code, set()).add(entry_index)
            for term in entry.text_terms:
                text_lookup.setdefault(term, set()).add(entry_index)

        tree_index = _LocalTreeIndex(
            import_id=tree_import.id,
            import_label=tree_import.source_filename,
            entries=entries,
            code_lookup=code_lookup,
            text_lookup=text_lookup,
        )
        self._local_tree_index_cache[tree_import_id] = tree_index
        logger.info(
            "Built local tree index for import_id=%s entries=%s codes=%s terms=%s",
            tree_import_id,
            len(entries),
            len(code_lookup),
            len(text_lookup),
        )
        return tree_index

    def create_and_submit_tasks(
        self,
        *,
        items: list[MagnetTaskCreateItem],
        target_cid: str | None = None,
        force_submit: bool = False,
        tree_import_id: int | None = None,
    ) -> list[MagnetDownloadTask]:
        created: list[MagnetDownloadTask] = []
        batch_id = f"magnet-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        target_cid_cache: dict[str, str] = {}
        for index, item in enumerate(items):
            duplicate_input = DuplicateCheckItemRequest(
                source_tid=item.source_tid,
                source_title=item.source_title,
                source_magnet=item.source_magnet,
                matched_keyword=item.matched_keyword,
                matched_alias=item.matched_alias,
            )
            duplicate_result = self.check_single_duplicate(duplicate_input, tree_import_id=tree_import_id)
            task = MagnetDownloadTask(
                batch_id=batch_id,
                keyword_entry_id=item.keyword_entry_id,
                source_tid=item.source_tid,
                source_title=item.source_title,
                source_magnet=item.source_magnet,
                source_detail_url=item.source_detail_url,
                source_section=item.source_section,
                matched_keyword=item.matched_keyword,
                matched_alias=item.matched_alias,
                match_score=f"{item.match_score:.4f}",
                duplicate_status=duplicate_result.status,
                duplicate_detail=json.dumps(
                    {
                        "reason": duplicate_result.reason,
                        "search_terms": duplicate_result.search_terms,
                        "matched_terms": duplicate_result.matched_terms,
                        "matched_import_id": duplicate_result.matched_import_id,
                        "matched_import_label": duplicate_result.matched_import_label,
                        "matched_nodes": [node.model_dump() for node in duplicate_result.matched_nodes],
                    },
                    ensure_ascii=False,
                ),
                status="pending",
                target_cid=item.target_cid or target_cid or self.settings.offline_default_target_cid,
            )
            self.db.add(task)
            self.db.flush()

            if duplicate_result.status == "duplicate_found" and not force_submit:
                task.status = "duplicate_skipped"
                task.failure_reason = duplicate_result.reason
                task.operation_log = "Skipped submit because duplicate check found existing content."
            elif duplicate_result.status == "task_exists" and not force_submit:
                task.status = "duplicate_skipped"
                task.failure_reason = duplicate_result.reason
                task.operation_log = "Skipped submit because same source tid already exists in task table."
            else:
                attempted_submit = False
                try:
                    attempted_submit = True
                    resolved_target_cid = self._resolve_submit_target_cid(
                        item=item,
                        fallback_target_cid=task.target_cid,
                        cid_cache=target_cid_cache,
                    )
                    task.target_cid = resolved_target_cid
                    result = self.client_115.submit_magnet_download(item.source_magnet, target_cid=resolved_target_cid)
                    task.status = "submitted"
                    task.task_id_115 = result.task_id
                    task.submitted_to_115_at = datetime.now(timezone.utc)
                    target_note = item.target_path or resolved_target_cid or "default"
                    task.operation_log = f"Submitted magnet to 115 offline download. target={target_note}"
                except Client115Error as exc:
                    task.status = "failed"
                    task.failure_reason = str(exc)
                    task.operation_log = "115 offline download submission failed."
                if attempted_submit and index < len(items) - 1:
                    time.sleep(max(0, self.settings.offline_submit_interval_seconds))
            created.append(task)

        self.db.commit()
        for task in created:
            self.db.refresh(task)
        return created

    def _load_whitelist_entries(self, keyword_entry_ids: list[int] | None = None) -> list[KeywordEntry]:
        stmt = (
            select(KeywordEntry)
            .where(KeywordEntry.keyword_type == "whitelist")
            .where(KeywordEntry.status == "active")
            .order_by(KeywordEntry.id.asc())
        )
        normalized_ids = [entry_id for entry_id in (keyword_entry_ids or []) if entry_id > 0]
        if normalized_ids:
            stmt = stmt.where(KeywordEntry.id.in_(normalized_ids))
        entries = list(self.db.scalars(stmt).all())
        if not entries:
            raise ValueError("No active whitelist keywords found")
        return entries

    def _resolve_submit_target_cid(
        self,
        *,
        item: MagnetTaskCreateItem,
        fallback_target_cid: str | None,
        cid_cache: dict[str, str],
    ) -> str | None:
        if item.target_cid:
            return item.target_cid
        if not item.target_path:
            return fallback_target_cid
        normalized_path = self._normalize_display_path(item.target_path)
        if normalized_path in cid_cache:
            return cid_cache[normalized_path]
        resolved = self._ensure_directory(item.target_path)
        cid_cache[normalized_path] = resolved
        return resolved

    def _ensure_directory(self, path: str) -> str:
        if self.client_115 is None:
            raise Client115Error("115 client is not configured")
        parts = self._client_path_parts(path)
        current_id = "0"
        for part in parts:
            matched_id = self._find_child(current_id, part, directories_only=True)
            if matched_id is not None:
                current_id = matched_id
                continue
            created_result = self.client_115.create_folder(current_id, part)
            current_id = str(created_result.payload["file_id"])
        return current_id

    def _find_child(self, parent_id: str, name: str, *, directories_only: bool = False) -> str | None:
        if self.client_115 is None:
            raise Client115Error("115 client is not configured")
        offset = 0
        limit = 500
        normalized_name = self._normalize_folder_name(name)
        while True:
            listing = self.client_115.list_files(cid=parent_id, limit=limit, offset=offset, show_dir=1)
            data = listing.get("data", [])
            for row in data:
                row_name = self._normalize_folder_name(str(row.get("fn", "")))
                if row_name != normalized_name:
                    continue
                if directories_only and row.get("fc") != "0":
                    continue
                return str(row.get("fid"))
            count = int(listing.get("count") or len(data) or 0)
            offset += len(data)
            if not data or offset >= count:
                break
        return None

    def _client_path_parts(self, path: str) -> list[str]:
        if self.client_115 is not None and hasattr(self.client_115, "path_parts_for_display_path"):
            return self.client_115.path_parts_for_display_path(path)
        cleaned = path.strip().strip("/")
        if not cleaned:
            return []
        parts = [part for part in cleaned.split("/") if part]
        if parts and parts[0] == "根目录":
            parts = parts[1:]
        return parts

    @staticmethod
    def _normalize_folder_name(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _normalize_display_path(path: str) -> str:
        cleaned = path.strip()
        if not cleaned:
            return "/"
        parts = [part.strip() for part in cleaned.strip("/").split("/") if part.strip()]
        if parts and parts[0] == "根目录":
            parts = parts[1:]
        return "/" + "/".join(parts)

    @classmethod
    def build_target_path(cls, *, keyword_dir: str, source_title: str) -> str:
        safe_leaf = cls._sanitize_target_name(source_title)
        return str(PurePosixPath("/已整理") / keyword_dir / safe_leaf)

    @staticmethod
    def _sanitize_target_name(name: str) -> str:
        cleaned = re.sub(r'[\\\\/:*?"<>|]+', "_", name.strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" .")
        cleaned = re.sub(r"_+", "_", cleaned)
        return cleaned or "未命名磁力"


def normalize_keyword_text(raw: str) -> str:
    from app.services.keywords.registry_service import normalize_keyword_text as _normalize_keyword_text

    return _normalize_keyword_text(raw)
