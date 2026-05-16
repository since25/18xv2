from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.schemas.local_cleanup import (
    LocalCleanupDeleteItemResponse,
    LocalCleanupDeleteResponse,
    LocalCleanupScanCandidateResponse,
    LocalCleanupScanResponse,
)


@dataclass(slots=True)
class _EntryDecision:
    entry_type: str
    path: str
    name: str
    size_bytes: int | None
    delete_hits: list[str]

    @property
    def decision(self) -> str:
        if self.delete_hits:
            return "delete"
        return "skip"

    @property
    def reasons(self) -> list[str]:
        return self.delete_hits


class LocalCleanupService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def scan(
        self,
        root_path: str,
        blacklist_keywords: list[str],
        fuzzy_match: bool = True,
        suffix_filter: list[str] | None = None,
        max_file_size_mb: float = 0,
        include_files: bool = True,
        include_directories: bool = True,
        max_results: int = 500,
    ) -> LocalCleanupScanResponse:
        resolved_root = self._resolve_root(root_path)
        suffixes = self._normalize_suffixes(suffix_filter or [])
        blacklist = self._normalize_keywords(blacklist_keywords)
        max_size_bytes = int(max_file_size_mb * 1024 * 1024) if max_file_size_mb > 0 else 0

        candidates: list[_EntryDecision] = []
        seen_paths: set[str] = set()
        skipped_count = 0

        for current_root, dirnames, filenames in os.walk(resolved_root):
            current_root_path = Path(current_root)

            if include_directories:
                for dirname in dirnames:
                    dir_path = current_root_path / dirname
                    decision = self._build_directory_decision(
                        dir_path=dir_path,
                        blacklist=blacklist,
                        fuzzy_match=fuzzy_match,
                    )
                    if decision.decision == "skip":
                        skipped_count += 1
                        continue
                    normalized_path = str(dir_path.resolve())
                    if normalized_path in seen_paths:
                        continue
                    seen_paths.add(normalized_path)
                    candidates.append(decision)

            if include_files:
                for filename in filenames:
                    file_path = current_root_path / filename
                    decision = self._build_file_decision(
                        file_path=file_path,
                        blacklist=blacklist,
                        fuzzy_match=fuzzy_match,
                        suffixes=suffixes,
                        max_size_bytes=max_size_bytes,
                    )
                    if decision.decision == "skip":
                        skipped_count += 1
                        continue
                    normalized_path = str(file_path.resolve())
                    if normalized_path in seen_paths:
                        continue
                    seen_paths.add(normalized_path)
                    candidates.append(decision)

        # Keep the response reviewable even for large roots.
        candidates.sort(key=lambda item: (item.decision != "delete", item.entry_type, item.path))
        truncated = max(0, len(candidates) - max_results)
        candidates = candidates[:max_results]

        delete_count = sum(1 for item in candidates if item.decision == "delete")
        return LocalCleanupScanResponse(
            root_path=str(resolved_root),
            total_candidates=len(candidates),
            total_delete_candidates=delete_count,
            total_keep_candidates=0,
            skipped_count=skipped_count + truncated,
            items=[
                LocalCleanupScanCandidateResponse(
                    entry_type=item.entry_type,
                    path=item.path,
                    name=item.name,
                    size_bytes=item.size_bytes,
                    decision=item.decision,
                    reasons=item.reasons,
                )
                for item in candidates
            ],
        )

    def delete(
        self,
        root_path: str,
        paths: list[str],
        dry_run: bool = True,
        confirm_delete: bool = False,
        remove_empty_dirs: bool = True,
    ) -> LocalCleanupDeleteResponse:
        resolved_root = self._resolve_root(root_path)
        cleaned_paths = self._normalize_delete_paths(resolved_root, paths)

        if not dry_run and not confirm_delete:
            raise ValueError("confirm_delete must be true for real deletion")

        items: list[LocalCleanupDeleteItemResponse] = []
        for target_path in cleaned_paths:
            if dry_run:
                items.append(
                    LocalCleanupDeleteItemResponse(path=target_path, entry_type=self._entry_type(target_path), success=True, status="dry_run")
                )
                continue

            try:
                if not os.path.exists(target_path):
                    items.append(
                        LocalCleanupDeleteItemResponse(
                            path=target_path,
                            entry_type=self._entry_type(target_path),
                            success=False,
                            status="not_found",
                            error_message="path not found",
                        )
                    )
                    continue

                self._ensure_delete_allowed(resolved_root, target_path)
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                    entry_type = "dir"
                else:
                    os.remove(target_path)
                    entry_type = "file"

                items.append(LocalCleanupDeleteItemResponse(path=target_path, entry_type=entry_type, success=True, status="deleted"))
            except Exception as exc:  # noqa: BLE001
                items.append(
                    LocalCleanupDeleteItemResponse(
                        path=target_path,
                        entry_type=self._entry_type(target_path),
                        success=False,
                        status="blocked",
                        error_message=str(exc),
                    )
                )

        removed_empty_dirs = 0
        if remove_empty_dirs:
            removed_empty_dirs = self._remove_empty_folders(resolved_root, dry_run=dry_run)

        return LocalCleanupDeleteResponse(
            root_path=str(resolved_root),
            dry_run=dry_run,
            total_requested=len(cleaned_paths),
            total_processed=len(items),
            removed_empty_dirs=removed_empty_dirs,
            items=items,
        )

    def _build_directory_decision(
        self,
        dir_path: Path,
        blacklist: list[str],
        fuzzy_match: bool,
    ) -> _EntryDecision:
        name = dir_path.name
        delete_hits = self._match_keywords(
            name=name,
            full_path=str(dir_path),
            keywords=blacklist,
            fuzzy_match=fuzzy_match,
            prefix="blacklist",
        )
        return _EntryDecision(
            entry_type="dir",
            path=str(dir_path.resolve()),
            name=name,
            size_bytes=None,
            delete_hits=delete_hits,
        )

    def _build_file_decision(
        self,
        file_path: Path,
        blacklist: list[str],
        fuzzy_match: bool,
        suffixes: set[str],
        max_size_bytes: int,
    ) -> _EntryDecision:
        name = file_path.name
        full_path = str(file_path.resolve())
        size_bytes = file_path.stat().st_size if file_path.exists() else None
        delete_hits: list[str] = []
        if self._suffix_allowed(name, suffixes) and self._size_allowed(size_bytes, max_size_bytes):
            delete_hits.extend(
                self._match_keywords(
                    name=name,
                    full_path=full_path,
                    keywords=blacklist,
                    fuzzy_match=fuzzy_match,
                    prefix="blacklist",
                )
            )

        return _EntryDecision(
            entry_type="file",
            path=full_path,
            name=name,
            size_bytes=size_bytes,
            delete_hits=delete_hits,
        )

    @staticmethod
    def _normalize_keywords(keywords: list[str]) -> list[str]:
        return [item.strip().lower() for item in keywords if item and item.strip()]

    @staticmethod
    def _normalize_suffixes(suffixes: list[str]) -> set[str]:
        normalized: set[str] = set()
        for item in suffixes:
            value = item.strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value = f".{value}"
            normalized.add(value)
        return normalized

    @staticmethod
    def _suffix_allowed(name: str, suffixes: set[str]) -> bool:
        return not suffixes or any(name.lower().endswith(suffix) for suffix in suffixes)

    @staticmethod
    def _size_allowed(size_bytes: int | None, max_size_bytes: int) -> bool:
        if size_bytes is None or max_size_bytes <= 0:
            return True
        return size_bytes <= max_size_bytes

    @staticmethod
    def _match_keywords(name: str, full_path: str, keywords: list[str], fuzzy_match: bool, prefix: str) -> list[str]:
        lowered_name = name.lower()
        lowered_path = full_path.lower()
        hits: list[str] = []
        for keyword in keywords:
            if fuzzy_match:
                matched = keyword in lowered_name or keyword in lowered_path
            else:
                matched = keyword == lowered_name or keyword == lowered_path
            if matched:
                hits.append(f"{prefix}:{keyword}")
        return hits

    @staticmethod
    def _resolve_root(root_path: str) -> Path:
        candidate = Path(root_path).expanduser().resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"root_path does not exist or is not a directory: {root_path}")
        if candidate == Path(candidate.anchor):
            raise ValueError("root_path cannot be filesystem root")
        return candidate

    @staticmethod
    def _entry_type(path: str) -> str:
        if os.path.isdir(path):
            return "dir"
        if os.path.isfile(path):
            return "file"
        return "unknown"

    def _ensure_delete_allowed(self, resolved_root: Path, target_path: str) -> None:
        target = Path(target_path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError as exc:
            raise PermissionError(f"path is outside root_path: {target_path}") from exc

        # Local cleanup is scoped by the explicit root_path in the request.
        # Keep the boundary strict to that subtree instead of reusing the 115 remote-delete allowlist.

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False

    def _normalize_delete_paths(self, resolved_root: Path, paths: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        resolved_candidates = []
        for item in paths:
            if not item or not item.strip():
                continue
            resolved = str(Path(item).expanduser().resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_candidates.append(resolved)

        for resolved in sorted(resolved_candidates, key=lambda value: (value.count(os.sep), value)):
            if not self._is_relative_to(Path(resolved), resolved_root):
                raise ValueError(f"path is outside root_path: {resolved}")
            if any(resolved == parent or resolved.startswith(f"{parent}{os.sep}") for parent in deduped):
                continue
            deduped.append(resolved)

        return deduped

    @staticmethod
    def _remove_empty_folders(root_path: Path, dry_run: bool) -> int:
        removed = 0
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
            if dirnames or filenames:
                continue
            path = Path(dirpath)
            if path == root_path:
                continue
            if dry_run:
                removed += 1
                continue
            try:
                path.rmdir()
                removed += 1
            except OSError:
                continue
        return removed
