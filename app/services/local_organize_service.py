from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.keywords import KeywordEntry
from app.schemas.local_organize import (
    LocalOrganizeCandidateResponse,
    LocalOrganizeDebugResponse,
    LocalOrganizeDebugRuleMatchResponse,
    LocalOrganizeExecuteItemResponse,
    LocalOrganizeExecuteResponse,
    LocalOrganizeScanResponse,
)
from app.services.keywords.registry_service import normalize_keyword_text


@dataclass(slots=True)
class _OrganizeDecision:
    source_path: str
    source_name: str
    matched_keywords: list[str]
    target_path: str | None
    status: str
    reasons: list[str]


@dataclass(slots=True)
class _WhitelistRule:
    group_key: str
    keyword_entry_id: int | None
    canonical_name: str
    match_terms: list[str]


class LocalOrganizeService:
    def __init__(self, db: Session):
        self.db = db

    def scan(
        self,
        *,
        root_path: str,
        target_root: str,
        whitelist_keywords: list[str],
        fuzzy_match: bool = True,
        max_results: int = 500,
    ) -> LocalOrganizeScanResponse:
        resolved_root = self._resolve_dir(root_path, field_name="root_path")
        resolved_target = self._resolve_target(target_root)
        rules = self._build_request_rules(whitelist_keywords) or self._load_default_whitelist_rules()
        if not rules:
            raise ValueError("No active whitelist keywords found in request or database")

        items: list[_OrganizeDecision] = []
        skipped_count = 0

        for current_root, dirnames, _ in os.walk(resolved_root):
            for dirname in dirnames:
                dir_path = Path(current_root) / dirname
                if dir_path == resolved_target or self._is_relative_to(dir_path, resolved_target):
                    continue
                decision = self._match_directory(
                    dir_path=dir_path,
                    target_root=resolved_target,
                    rules=rules,
                    fuzzy_match=fuzzy_match,
                )
                if decision.status == "skip":
                    skipped_count += 1
                    continue
                items.append(decision)

        items.sort(key=lambda item: (item.status != "move", item.source_path))
        truncated = max(0, len(items) - max_results)
        items = items[:max_results]

        return LocalOrganizeScanResponse(
            root_path=str(resolved_root),
            target_root=str(resolved_target),
            total_candidates=len(items),
            total_move_candidates=sum(1 for item in items if item.status == "move"),
            total_ambiguous=sum(1 for item in items if item.status == "ambiguous"),
            skipped_count=skipped_count,
            truncated_count=truncated,
            items=[
                LocalOrganizeCandidateResponse(
                    source_path=item.source_path,
                    source_name=item.source_name,
                    matched_keyword=item.matched_keywords[0] if item.matched_keywords else "",
                    target_path=item.target_path or "",
                    status=item.status,
                    reasons=item.reasons,
                )
                for item in items
            ],
        )

    def execute(
        self,
        *,
        root_path: str,
        target_root: str,
        items: list[LocalOrganizeCandidateResponse],
        dry_run: bool = True,
        confirm_execute: bool = False,
    ) -> LocalOrganizeExecuteResponse:
        resolved_root = self._resolve_dir(root_path, field_name="root_path")
        resolved_target = self._resolve_target(target_root)
        if not dry_run and not confirm_execute:
            raise ValueError("confirm_execute must be true for real execution")

        deduped = self._dedupe_items(items)
        results: list[LocalOrganizeExecuteItemResponse] = []

        for item in deduped:
            source = Path(item.source_path).expanduser().resolve()
            target = Path(item.target_path).expanduser().resolve()
            if item.status != "move":
                results.append(
                    LocalOrganizeExecuteItemResponse(
                        source_path=str(source),
                        target_path=str(target),
                        success=False,
                        status="skipped",
                        error_message=f"item status is {item.status}",
                    )
                )
                continue

            try:
                self._ensure_source_allowed(resolved_root, source)
                self._ensure_target_allowed(resolved_target, target)
                if dry_run:
                    results.append(
                        LocalOrganizeExecuteItemResponse(
                            source_path=str(source),
                            target_path=str(target),
                            success=True,
                            status="dry_run",
                        )
                    )
                    continue

                if not source.exists() or not source.is_dir():
                    raise FileNotFoundError("source directory not found")
                if target.exists():
                    raise FileExistsError("target path already exists")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                results.append(
                    LocalOrganizeExecuteItemResponse(
                        source_path=str(source),
                        target_path=str(target),
                        success=True,
                        status="moved",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    LocalOrganizeExecuteItemResponse(
                        source_path=str(source),
                        target_path=str(target),
                        success=False,
                        status="blocked",
                        error_message=str(exc),
                    )
                )

        return LocalOrganizeExecuteResponse(
            root_path=str(resolved_root),
            target_root=str(resolved_target),
            dry_run=dry_run,
            total_requested=len(deduped),
            total_processed=len(results),
            items=results,
        )

    def debug_match(
        self,
        *,
        folder_name: str,
        whitelist_keywords: list[str],
        fuzzy_match: bool = True,
    ) -> LocalOrganizeDebugResponse:
        rules = self._build_request_rules(whitelist_keywords) or self._load_default_whitelist_rules()
        if not rules:
            raise ValueError("No active whitelist keywords found in request or database")

        matched_rules: list[LocalOrganizeDebugRuleMatchResponse] = []
        normalized_folder_name = normalize_keyword_text(folder_name)
        for rule in rules:
            matched_terms = [term for term in rule.match_terms if self._matches(term, folder_name, fuzzy_match=fuzzy_match)]
            if not matched_terms:
                continue
            matched_rules.append(
                LocalOrganizeDebugRuleMatchResponse(
                    keyword_entry_id=rule.keyword_entry_id,
                    canonical_name=rule.canonical_name,
                    matched_terms=matched_terms,
                    all_terms=rule.match_terms,
                )
            )

        status = "skip"
        if len(matched_rules) == 1:
            status = "move"
        elif len(matched_rules) > 1:
            status = "ambiguous"

        matched_rules.sort(key=lambda item: (-len(item.canonical_name), item.canonical_name))
        return LocalOrganizeDebugResponse(
            folder_name=folder_name,
            normalized_folder_name=normalized_folder_name,
            status=status,
            matched_rule_count=len(matched_rules),
            matched_rules=matched_rules,
        )

    def _match_directory(
        self,
        *,
        dir_path: Path,
        target_root: Path,
        rules: list[_WhitelistRule],
        fuzzy_match: bool,
    ) -> _OrganizeDecision:
        full_path = str(dir_path.resolve())
        matched_rules: list[_WhitelistRule] = []
        for rule in rules:
            if any(self._matches(term, dir_path.name, fuzzy_match=fuzzy_match) for term in rule.match_terms):
                matched_rules.append(rule)

        if not matched_rules:
            return _OrganizeDecision(
                source_path=full_path,
                source_name=dir_path.name,
                matched_keywords=[],
                target_path=None,
                status="skip",
                reasons=[],
            )

        unique_rules = {rule.group_key: rule for rule in matched_rules}
        if len(unique_rules) > 1:
            canonical_names = sorted({rule.canonical_name for rule in unique_rules.values()}, key=lambda item: (-len(item), item))
            return _OrganizeDecision(
                source_path=full_path,
                source_name=dir_path.name,
                matched_keywords=canonical_names,
                target_path=None,
                status="ambiguous",
                reasons=[f"matched:{item}" for item in canonical_names],
            )

        matched_rule = next(iter(unique_rules.values()))
        matched_keyword = matched_rule.canonical_name
        keyword_dir = self._safe_dir_name(matched_keyword)
        target_path = target_root / keyword_dir / dir_path.name
        return _OrganizeDecision(
            source_path=full_path,
            source_name=dir_path.name,
            matched_keywords=[matched_keyword],
            target_path=str(target_path.resolve()),
            status="move",
            reasons=[f"matched:{matched_keyword}"],
        )

    @staticmethod
    def _normalize_keywords(keywords: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in keywords:
            cleaned = normalize_keyword_text(item).casefold()
            if cleaned:
                normalized.append(cleaned)
        return sorted(set(normalized), key=lambda item: (-len(item), item))

    def _build_request_rules(self, whitelist_keywords: list[str]) -> list[_WhitelistRule]:
        normalized = self._normalize_keywords(whitelist_keywords)
        return [
            _WhitelistRule(group_key=keyword, keyword_entry_id=None, canonical_name=keyword, match_terms=[keyword])
            for keyword in normalized
        ]

    def _load_default_whitelist_rules(self) -> list[_WhitelistRule]:
        entries = list(
            self.db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "whitelist")
                .where(KeywordEntry.status == "active")
                .options(selectinload(KeywordEntry.aliases))
                .order_by(KeywordEntry.id.asc())
            ).all()
        )
        rules: list[_WhitelistRule] = []
        for entry in entries:
            terms = [entry.canonical_name]
            # Include every alias on the entry. Some historical rows keep useful match terms
            # under source="canonical" after canonical-name adjustments.
            terms.extend(alias.alias for alias in entry.aliases)
            normalized_terms = self._normalize_keywords(terms)
            if not normalized_terms:
                continue
            rules.append(
                _WhitelistRule(
                    group_key=f"entry:{entry.id}",
                    keyword_entry_id=entry.id,
                    canonical_name=normalize_keyword_text(entry.canonical_name) or entry.canonical_name,
                    match_terms=normalized_terms,
                )
            )
        return rules

    @staticmethod
    def _matches(keyword: str, dir_name: str, *, fuzzy_match: bool) -> bool:
        lowered_name = normalize_keyword_text(dir_name).casefold()
        if fuzzy_match:
            return keyword in lowered_name
        return keyword == lowered_name

    @staticmethod
    def _safe_dir_name(keyword: str) -> str:
        safe = keyword.replace("/", " ").strip()
        return safe or "未分类"

    @staticmethod
    def _resolve_dir(path_value: str, *, field_name: str) -> Path:
        candidate = Path(path_value).expanduser().resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"{field_name} does not exist or is not a directory: {path_value}")
        return candidate

    @staticmethod
    def _resolve_target(path_value: str) -> Path:
        candidate = Path(path_value).expanduser().resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False

    def _ensure_source_allowed(self, root_path: Path, source: Path) -> None:
        if not self._is_relative_to(source, root_path):
            raise PermissionError(f"source is outside root_path: {source}")

    def _ensure_target_allowed(self, target_root: Path, target: Path) -> None:
        if not self._is_relative_to(target, target_root):
            raise PermissionError(f"target is outside target_root: {target}")

    def _dedupe_items(self, items: list[LocalOrganizeCandidateResponse]) -> list[LocalOrganizeCandidateResponse]:
        seen: set[str] = set()
        deduped: list[LocalOrganizeCandidateResponse] = []
        for item in sorted(items, key=lambda current: current.source_path.count(os.sep)):
            source = str(Path(item.source_path).expanduser().resolve())
            if any(source == parent or source.startswith(f"{parent}{os.sep}") for parent in seen):
                continue
            seen.add(source)
            deduped.append(item)
        return deduped
