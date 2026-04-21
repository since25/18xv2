from __future__ import annotations

from dataclasses import dataclass
import csv
import io
from pathlib import PurePosixPath
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry, KeywordHit
from app.models.tasks import OrganizeTask
from app.models.tree import TreeNode


@dataclass(slots=True)
class OrganizeTaskBatchResult:
    import_id: int
    keyword_entry_id: int | None
    deleted_count: int
    created_count: int
    skipped_ambiguous_count: int
    tasks: list[OrganizeTask]


@dataclass(slots=True)
class AmbiguousKeywordOption:
    id: int
    name: str


@dataclass(slots=True)
class AmbiguousKeywordConflict:
    source_path: str
    keywords: list[str]              # 保留，TSV export 继续使用
    keyword_options: list[AmbiguousKeywordOption]  # 新增，JSON 接口使用

    @property
    def keyword_count(self) -> int:
        return len(self.keywords)


class OrganizeTaskService:
    DEFAULT_TARGET_ROOT = "/根目录/已整理"

    def __init__(self, db: Session):
        self.db = db

    def generate_tasks_from_keyword_hits(
        self,
        *,
        import_id: int,
        keyword_entry_id: int,
        target_root: str,
        replace_existing: bool = True,
    ) -> OrganizeTaskBatchResult:
        entry = self.db.scalar(select(KeywordEntry).where(KeywordEntry.id == keyword_entry_id))
        if entry is None:
            raise ValueError(f"KeywordEntry {keyword_entry_id} not found")

        deleted_count = 0
        if replace_existing:
            existing_ids = list(
                self.db.scalars(
                    select(OrganizeTask.id)
                    .where(OrganizeTask.import_id == import_id)
                    .where(OrganizeTask.keyword_entry_id == keyword_entry_id)
                ).all()
            )
            if existing_ids:
                self.db.execute(delete(OrganizeTask).where(OrganizeTask.id.in_(existing_ids)))
                self.db.flush()
                deleted_count = len(existing_ids)

        hits = list(
            self.db.scalars(
                select(KeywordHit)
                .where(KeywordHit.import_id == import_id)
                .where(KeywordHit.keyword_entry_id == keyword_entry_id)
                .order_by(KeywordHit.id.asc())
            ).all()
        )

        normalized_root = self._normalize_target_root(target_root)
        seen_paths: set[str] = set()
        created_tasks: list[OrganizeTask] = []
        for hit in hits:
            if hit.source_path in seen_paths:
                continue
            node = self.db.scalar(
                select(TreeNode)
                .where(TreeNode.import_id == import_id)
                .where(TreeNode.raw_path == hit.source_path)
                .where(TreeNode.node_type == "folder")
            )
            if node is None:
                continue
            seen_paths.add(hit.source_path)
            task = OrganizeTask(
                import_id=import_id,
                node_id=node.id,
                keyword_entry_id=keyword_entry_id,
                source_path=node.raw_path,
                target_path=str(PurePosixPath(normalized_root) / node.raw_name),
                matched_canonical_name=entry.canonical_name,
                status="pending",
                operation_log=f"Generated from keyword_hits for keyword #{keyword_entry_id}.",
            )
            self.db.add(task)
            created_tasks.append(task)

        self.db.commit()
        for task in created_tasks:
            self.db.refresh(task)

        return OrganizeTaskBatchResult(
            import_id=import_id,
            keyword_entry_id=keyword_entry_id,
            deleted_count=deleted_count,
            created_count=len(created_tasks),
            skipped_ambiguous_count=0,
            tasks=created_tasks,
        )

    def generate_tasks_from_import_hits(
        self,
        *,
        import_id: int,
        replace_existing: bool = True,
    ) -> OrganizeTaskBatchResult:
        whitelist_entries = list(
            self.db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "whitelist")
                .where(KeywordEntry.status == "active")
                .order_by(KeywordEntry.id.asc())
            ).all()
        )
        if not whitelist_entries:
            raise ValueError("No active whitelist keywords found")

        whitelist_ids = [entry.id for entry in whitelist_entries]
        deleted_count = 0
        if replace_existing:
            existing_ids = list(
                self.db.scalars(select(OrganizeTask.id).where(OrganizeTask.import_id == import_id)).all()
            )
            if existing_ids:
                self.db.execute(delete(OrganizeTask).where(OrganizeTask.id.in_(existing_ids)))
                self.db.flush()
                deleted_count = len(existing_ids)

        directory_names = self._build_keyword_directory_names(whitelist_entries)
        hits = list(
            self.db.scalars(
                select(KeywordHit)
                .where(KeywordHit.import_id == import_id)
                .where(KeywordHit.keyword_entry_id.in_(whitelist_ids))
                .order_by(KeywordHit.id.asc())
            ).all()
        )

        path_to_keywords: dict[str, set[int]] = {}
        for hit in hits:
            if hit.keyword_entry_id is None:
                continue
            node = self.db.scalar(
                select(TreeNode)
                .where(TreeNode.import_id == import_id)
                .where(TreeNode.raw_path == hit.source_path)
                .where(TreeNode.node_type == "folder")
            )
            if node is None:
                continue
            path_to_keywords.setdefault(hit.source_path, set()).add(hit.keyword_entry_id)

        entry_by_id = {entry.id: entry for entry in whitelist_entries}
        created_tasks: list[OrganizeTask] = []
        skipped_ambiguous_count = 0
        for source_path, keyword_ids in path_to_keywords.items():
            if len(keyword_ids) != 1:
                skipped_ambiguous_count += 1
                continue
            keyword_entry_id = next(iter(keyword_ids))
            entry = entry_by_id[keyword_entry_id]
            node = self.db.scalar(
                select(TreeNode)
                .where(TreeNode.import_id == import_id)
                .where(TreeNode.raw_path == source_path)
                .where(TreeNode.node_type == "folder")
            )
            if node is None:
                continue
            task = OrganizeTask(
                import_id=import_id,
                node_id=node.id,
                keyword_entry_id=keyword_entry_id,
                source_path=node.raw_path,
                target_path=str(PurePosixPath(self.DEFAULT_TARGET_ROOT) / directory_names[keyword_entry_id] / node.raw_name),
                matched_canonical_name=entry.canonical_name,
                status="pending",
                operation_log=f"Generated from active whitelist hits for keyword #{keyword_entry_id}.",
            )
            self.db.add(task)
            created_tasks.append(task)

        self.db.commit()
        for task in created_tasks:
            self.db.refresh(task)

        return OrganizeTaskBatchResult(
            import_id=import_id,
            keyword_entry_id=None,
            deleted_count=deleted_count,
            created_count=len(created_tasks),
            skipped_ambiguous_count=skipped_ambiguous_count,
            tasks=created_tasks,
        )

    def list_ambiguous_conflicts(self, *, import_id: int) -> list[AmbiguousKeywordConflict]:
        whitelist_entries = list(
            self.db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "whitelist")
                .where(KeywordEntry.status == "active")
                .order_by(KeywordEntry.id.asc())
            ).all()
        )
        if not whitelist_entries:
            return []

        whitelist_ids = [entry.id for entry in whitelist_entries]
        entry_by_id = {entry.id: entry for entry in whitelist_entries}
        hits = list(
            self.db.scalars(
                select(KeywordHit)
                .where(KeywordHit.import_id == import_id)
                .where(KeywordHit.keyword_entry_id.in_(whitelist_ids))
                .order_by(KeywordHit.id.asc())
            ).all()
        )

        path_to_keywords: dict[str, set[int]] = {}
        for hit in hits:
            if hit.keyword_entry_id is None:
                continue
            node = self.db.scalar(
                select(TreeNode)
                .where(TreeNode.import_id == import_id)
                .where(TreeNode.raw_path == hit.source_path)
                .where(TreeNode.node_type == "folder")
            )
            if node is None:
                continue
            path_to_keywords.setdefault(hit.source_path, set()).add(hit.keyword_entry_id)

        conflicts: list[AmbiguousKeywordConflict] = []
        for source_path, keyword_ids in path_to_keywords.items():
            if len(keyword_ids) <= 1:
                continue
            sorted_options = sorted(
                [AmbiguousKeywordOption(id=kid, name=entry_by_id[kid].canonical_name) for kid in keyword_ids],
                key=lambda o: o.name,
            )
            conflicts.append(
                AmbiguousKeywordConflict(
                    source_path=source_path,
                    keywords=[opt.name for opt in sorted_options],
                    keyword_options=sorted_options,
                )
            )
        conflicts.sort(key=lambda item: (-item.keyword_count, item.source_path))
        return conflicts

    def apply_ambiguous_resolutions_from_tsv(
        self,
        *,
        import_id: int,
        tsv_text: str,
        replace_existing: bool = True,
    ) -> tuple[list[OrganizeTask], int, int, list[str]]:
        conflict_map = {item.source_path: item for item in self.list_ambiguous_conflicts(import_id=import_id)}
        if not conflict_map:
            return [], 0, 0, []

        whitelist_entries = list(
            self.db.scalars(
                select(KeywordEntry)
                .where(KeywordEntry.keyword_type == "whitelist")
                .where(KeywordEntry.status == "active")
                .order_by(KeywordEntry.id.asc())
            ).all()
        )
        entry_by_id = {entry.id: entry for entry in whitelist_entries}
        entry_by_name = {entry.canonical_name.strip(): entry for entry in whitelist_entries}
        directory_names = self._build_keyword_directory_names(whitelist_entries)

        reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
        created_tasks: list[OrganizeTask] = []
        replaced_count = 0
        skipped_count = 0
        errors: list[str] = []
        seen_paths: set[str] = set()

        for row_index, row in enumerate(reader, start=2):
            source_path = (row.get("source_path") or "").strip()
            if not source_path:
                skipped_count += 1
                continue
            if source_path in seen_paths:
                errors.append(f"line {row_index}: duplicated source_path {source_path}")
                continue
            seen_paths.add(source_path)

            conflict = conflict_map.get(source_path)
            if conflict is None:
                skipped_count += 1
                continue

            selected_keyword_id_raw = (row.get("selected_keyword_id") or "").strip()
            selected_keyword_name = (row.get("selected_keyword") or "").strip()
            if not selected_keyword_id_raw and not selected_keyword_name:
                skipped_count += 1
                continue

            entry: KeywordEntry | None = None
            if selected_keyword_id_raw:
                try:
                    entry = entry_by_id.get(int(selected_keyword_id_raw))
                except ValueError:
                    errors.append(f"line {row_index}: invalid selected_keyword_id={selected_keyword_id_raw}")
                    continue
            if entry is None and selected_keyword_name:
                entry = entry_by_name.get(selected_keyword_name)
            if entry is None:
                errors.append(f"line {row_index}: keyword not found for source_path {source_path}")
                continue
            if entry.canonical_name not in conflict.keywords:
                errors.append(
                    f"line {row_index}: keyword {entry.canonical_name} is not one of conflict options for {source_path}"
                )
                continue

            node = self.db.scalar(
                select(TreeNode)
                .where(TreeNode.import_id == import_id)
                .where(TreeNode.raw_path == source_path)
                .where(TreeNode.node_type == "folder")
            )
            if node is None:
                errors.append(f"line {row_index}: folder node not found for {source_path}")
                continue

            existing_tasks = list(
                self.db.scalars(
                    select(OrganizeTask)
                    .where(OrganizeTask.import_id == import_id)
                    .where(OrganizeTask.source_path == source_path)
                ).all()
            )
            if existing_tasks and replace_existing:
                for task in existing_tasks:
                    self.db.delete(task)
                self.db.flush()
                replaced_count += len(existing_tasks)
            elif existing_tasks:
                skipped_count += 1
                continue

            task = OrganizeTask(
                import_id=import_id,
                node_id=node.id,
                keyword_entry_id=entry.id,
                source_path=node.raw_path,
                target_path=str(PurePosixPath(self.DEFAULT_TARGET_ROOT) / directory_names[entry.id] / node.raw_name),
                matched_canonical_name=entry.canonical_name,
                status="pending",
                operation_log="Generated from ambiguous conflict TSV resolution.",
            )
            self.db.add(task)
            created_tasks.append(task)

        self.db.commit()
        for task in created_tasks:
            self.db.refresh(task)
        return created_tasks, replaced_count, skipped_count, errors

    def apply_ambiguous_resolutions_from_json(
        self,
        *,
        import_id: int,
        resolutions: list[dict],  # [{source_path: str, keyword_entry_id: int}]
        replace_existing: bool = True,
    ) -> tuple[list[OrganizeTask], int, int, list[str]]:
        """JSON 版裁决应用，复用 TSV 版核心逻辑，入参改为 dict 列表。"""
        if not resolutions:
            return [], 0, 0, []

        # 构造等价的 TSV 文本，复用现有方法
        lines = ["source_path\tkeyword_count\tkeywords\tselected_keyword\tselected_keyword_id"]
        for item in resolutions:
            sp = str(item.get("source_path", "")).strip()
            kid = str(item.get("keyword_entry_id", "")).strip()
            lines.append(f"{sp}\t\t\t\t{kid}")
        tsv_text = "\n".join(lines) + "\n"
        return self.apply_ambiguous_resolutions_from_tsv(
            import_id=import_id,
            tsv_text=tsv_text,
            replace_existing=replace_existing,
        )

    @staticmethod
    def _normalize_target_root(target_root: str) -> str:
        cleaned = target_root.strip()
        if not cleaned:
            raise ValueError("target_root cannot be empty")
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned.rstrip("/")

    @classmethod
    def _build_keyword_directory_names(cls, entries: list[KeywordEntry]) -> dict[int, str]:
        by_entry: dict[int, str] = {}
        used: set[str] = set()
        for entry in entries:
            base_name = cls._sanitize_directory_name(entry.canonical_name, entry.id)
            resolved_name = base_name
            if resolved_name in used:
                resolved_name = f"{base_name}__{entry.id}"
            used.add(resolved_name)
            by_entry[entry.id] = resolved_name
        return by_entry

    @staticmethod
    def _sanitize_directory_name(name: str, keyword_entry_id: int) -> str:
        cleaned = re.sub(r'[\\\\/:*?"<>|]+', "_", name.strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" .")
        cleaned = re.sub(r"_+", "_", cleaned)
        return cleaned or f"未命名关键词_{keyword_entry_id}"
