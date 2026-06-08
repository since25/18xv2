from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import re
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeScanRun
from app.models.tree import NodeFile, TreeImport
from app.services.dedupe.normalization import DedupeRuleSet, normalize_filename


MEDIA_EXTENSIONS = [".mp4", ".mkv", ".avi", ".mov"]
_COPY_MARKER_HINT_RE = re.compile(
    r"(?:\(\s*\d{1,3}\s*\)|（\s*\d{1,3}\s*）|copy|副本|复制)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class DedupeScanOptions:
    tree_import_id: int
    scope_path_prefix: str | None = None
    included_extensions: list[str] = field(default_factory=lambda: MEDIA_EXTENSIONS.copy())
    candidate_threshold: float = 0.82
    high_confidence_threshold: float = 0.92
    rules: DedupeRuleSet = field(default_factory=DedupeRuleSet)


@dataclass(slots=True)
class DedupeScanSummary:
    scan_run_id: int
    total_files: int
    total_groups: int
    total_candidates: int


@dataclass(slots=True)
class _ScannedFile:
    node_file: NodeFile
    normalized_name: str
    tokens: tuple[str, ...]
    applied_rules: tuple[str, ...]


class DedupeScanService:
    def __init__(self, db: Session):
        self.db = db

    def scan(self, options: DedupeScanOptions) -> DedupeScanSummary:
        tree_import = self.db.get(TreeImport, options.tree_import_id)
        if tree_import is None:
            raise ValueError(f"TreeImport {options.tree_import_id} does not exist")

        included_extensions = _normalize_extensions(options.included_extensions)
        scan_run = DedupeScanRun(
            tree_import_id=tree_import.id,
            status="running",
            scope_path_prefix=options.scope_path_prefix,
            included_extensions=",".join(included_extensions),
            candidate_threshold=options.candidate_threshold,
            high_confidence_threshold=options.high_confidence_threshold,
            rules_snapshot_json=json.dumps(asdict(options.rules), ensure_ascii=False, sort_keys=True),
            started_at=_utcnow(),
        )
        self.db.add(scan_run)
        self.db.commit()
        self.db.refresh(scan_run)

        try:
            node_files = self._load_node_files(options, included_extensions)
            scanned_files = [_normalize_node_file(node_file, options.rules) for node_file in node_files]
            groups = self._build_groups(scanned_files, options)
            total_candidates = self._persist_groups(scan_run, groups, options)

            summary = DedupeScanSummary(
                scan_run_id=scan_run.id,
                total_files=len(node_files),
                total_groups=len(groups),
                total_candidates=total_candidates,
            )
            scan_run.status = "completed"
            scan_run.total_files = summary.total_files
            scan_run.total_groups = summary.total_groups
            scan_run.total_candidates = summary.total_candidates
            scan_run.summary_json = json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True)
            scan_run.finished_at = _utcnow()
            self.db.commit()
            return summary
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.get(DedupeScanRun, scan_run.id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                failed_run.finished_at = _utcnow()
                self.db.commit()
            raise

    def _load_node_files(self, options: DedupeScanOptions, included_extensions: list[str]) -> list[NodeFile]:
        query = self.db.query(NodeFile).filter(NodeFile.import_id == options.tree_import_id)
        if included_extensions:
            query = query.filter(func.lower(NodeFile.file_ext).in_(included_extensions))
        if options.scope_path_prefix:
            query = query.filter(NodeFile.raw_path.startswith(options.scope_path_prefix))
        return list(query.order_by(NodeFile.raw_path.asc(), NodeFile.id.asc()).all())

    def _build_groups(
        self,
        scanned_files: list[_ScannedFile],
        options: DedupeScanOptions,
    ) -> list[tuple[list[_ScannedFile], dict[int, float], float]]:
        pair_scores: dict[tuple[int, int], float] = {}
        for bucket in _bucket_files(scanned_files).values():
            if len(bucket) < 2:
                continue
            ordered_bucket = sorted(bucket, key=lambda file: file.node_file.id)
            for index, left in enumerate(ordered_bucket[:-1]):
                for right in ordered_bucket[index + 1 :]:
                    pair_key = (left.node_file.id, right.node_file.id)
                    if pair_key in pair_scores:
                        continue
                    score = _similarity(left.normalized_name, right.normalized_name)
                    if score >= options.candidate_threshold:
                        pair_scores[pair_key] = score

        components = _connected_components(scanned_files, pair_scores)
        groups: list[tuple[list[_ScannedFile], dict[int, float], float]] = []
        for component in components:
            component_ids = {file.node_file.id for file in component}
            scores_by_node = {
                file.node_file.id: max(
                    score
                    for pair, score in pair_scores.items()
                    if file.node_file.id in pair and set(pair).issubset(component_ids)
                )
                for file in component
            }
            score_max = max(scores_by_node.values())
            groups.append((sorted(component, key=lambda file: file.node_file.id), scores_by_node, score_max))
        return sorted(groups, key=lambda group: min(file.node_file.id for file in group[0]))

    def _persist_groups(
        self,
        scan_run: DedupeScanRun,
        groups: list[tuple[list[_ScannedFile], dict[int, float], float]],
        options: DedupeScanOptions,
    ) -> int:
        total_candidates = 0
        for component, scores_by_node, score_max in groups:
            keep_file = min(component, key=_keep_sort_key)
            group = DedupeGroup(
                scan_run_id=scan_run.id,
                tree_import_id=options.tree_import_id,
                group_key=_group_key(component),
                representative_name=keep_file.node_file.raw_name,
                normalized_name=keep_file.normalized_name,
                score_max=score_max,
                confidence_level=(
                    "high_probability" if score_max >= options.high_confidence_threshold else "filename_suspected"
                ),
                status="pending_review",
            )
            self.db.add(group)
            self.db.flush()

            keep_candidate: DedupeCandidate | None = None
            for scanned_file in sorted(component, key=lambda file: _candidate_sort_key(file, keep_file)):
                is_keep = scanned_file.node_file.id == keep_file.node_file.id
                candidate = DedupeCandidate(
                    group_id=group.id,
                    node_file_id=scanned_file.node_file.id,
                    raw_name=scanned_file.node_file.raw_name,
                    raw_path=scanned_file.node_file.raw_path,
                    file_ext=scanned_file.node_file.file_ext,
                    normalized_name=scanned_file.normalized_name,
                    similarity_score=scores_by_node[scanned_file.node_file.id],
                    suggested_action="keep" if is_keep else "delete",
                    suggested_reason=(
                        "Selected as cleaner local copy candidate."
                        if is_keep
                        else "Likely duplicate of kept candidate by filename similarity."
                    ),
                )
                self.db.add(candidate)
                if is_keep:
                    keep_candidate = candidate
                total_candidates += 1

            self.db.flush()
            if keep_candidate is not None:
                group.suggested_keep_candidate_id = keep_candidate.id

        return total_candidates


def _normalize_node_file(node_file: NodeFile, rules: DedupeRuleSet) -> _ScannedFile:
    normalized = normalize_filename(node_file.raw_name, rules)
    return _ScannedFile(
        node_file=node_file,
        normalized_name=normalized.normalized_name,
        tokens=tuple(normalized.tokens),
        applied_rules=tuple(normalized.applied_rules),
    )


def _normalize_extensions(extensions: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for extension in extensions:
        cleaned = str(extension or "").strip().casefold()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _bucket_files(scanned_files: list[_ScannedFile]) -> dict[str, list[_ScannedFile]]:
    buckets: dict[str, list[_ScannedFile]] = defaultdict(list)
    for scanned_file in scanned_files:
        if not scanned_file.normalized_name:
            continue
        for key in _bucket_keys(scanned_file):
            buckets[key].append(scanned_file)
    return buckets


def _bucket_keys(scanned_file: _ScannedFile) -> set[str]:
    keys = {f"exact:{scanned_file.normalized_name}"}
    if len(scanned_file.tokens) == 1:
        keys.add(f"token:{scanned_file.tokens[0]}")
    if len(scanned_file.tokens) >= 2:
        keys.add(f"token2:{scanned_file.tokens[0]}:{scanned_file.tokens[1]}")
    return keys


def _similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _connected_components(
    scanned_files: list[_ScannedFile],
    pair_scores: dict[tuple[int, int], float],
) -> list[list[_ScannedFile]]:
    files_by_id = {file.node_file.id: file for file in scanned_files}
    edges: dict[int, set[int]] = defaultdict(set)
    for left_id, right_id in pair_scores:
        edges[left_id].add(right_id)
        edges[right_id].add(left_id)

    components: list[list[_ScannedFile]] = []
    visited: set[int] = set()
    for node_id in sorted(edges):
        if node_id in visited:
            continue
        stack = [node_id]
        component_ids: set[int] = set()
        while stack:
            current_id = stack.pop()
            if current_id in component_ids:
                continue
            component_ids.add(current_id)
            stack.extend(edges[current_id] - component_ids)
        visited.update(component_ids)
        if len(component_ids) >= 2:
            components.append([files_by_id[component_id] for component_id in sorted(component_ids)])
    return components


def _group_key(component: list[_ScannedFile]) -> str:
    raw_key = ",".join(str(file.node_file.id) for file in sorted(component, key=lambda file: file.node_file.id))
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]
    return f"local-filename-{digest}"


def _keep_sort_key(scanned_file: _ScannedFile) -> tuple[int, int, int, str, int]:
    return (
        _path_penalty(scanned_file.node_file.raw_path),
        _name_penalty(scanned_file),
        len(scanned_file.node_file.raw_name),
        scanned_file.node_file.raw_path.casefold(),
        scanned_file.node_file.id,
    )


def _candidate_sort_key(scanned_file: _ScannedFile, keep_file: _ScannedFile) -> tuple[int, str, int]:
    return (
        0 if scanned_file.node_file.id == keep_file.node_file.id else 1,
        scanned_file.node_file.raw_path.casefold(),
        scanned_file.node_file.id,
    )


def _path_penalty(raw_path: str) -> int:
    segments = {segment.casefold() for segment in raw_path.split("/")}
    penalty = 0
    if "重复" in segments:
        penalty += 20
    if "待整理" in segments:
        penalty += 10
    return penalty


def _name_penalty(scanned_file: _ScannedFile) -> int:
    penalty = len(scanned_file.applied_rules)
    if (
        "copy_marker" in scanned_file.applied_rules
        or _COPY_MARKER_HINT_RE.search(scanned_file.node_file.raw_name)
    ):
        penalty += 3
    return penalty


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
