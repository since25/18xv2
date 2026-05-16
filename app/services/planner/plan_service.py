from __future__ import annotations

from collections import Counter
from collections import defaultdict
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.keywords import KeywordEntry, KeywordHit
from app.models.organization import OrganizationPlan, OrganizationPlanItem
from app.models.tasks import OrganizeTask
from app.models.tree import NodeTag, TreeNode
from app.services.classifier.clusterer import cluster_nodes
from app.services.classifier.keyword_classifier import KeywordClassifier, normalize_folder_name
from app.services.planner.conflict_detector import ConflictDetector


class PlanService:
    def __init__(self, db: Session, classifier: KeywordClassifier):
        self.db = db
        self.classifier = classifier
        self.conflict_detector = ConflictDetector()
        self.settings = get_settings()

    def _load_nodes(self, import_id: int, node_ids: list[int] | None = None) -> list[TreeNode]:
        query = (
            select(TreeNode)
            .where(TreeNode.import_id == import_id)
            .where(TreeNode.node_type == "folder")
            .where(TreeNode.depth > 0)
            .options(selectinload(TreeNode.tags))
        )
        if node_ids:
            query = query.where(TreeNode.id.in_(node_ids))
        return list(self.db.scalars(query).all())

    def analyze(self, import_id: int, node_ids: list[int] | None = None) -> list[TreeNode]:
        nodes = self._load_nodes(import_id=import_id, node_ids=node_ids)
        for node in nodes:
            match = self.classifier.classify(node.raw_name, node.parent_path)
            node.tags.clear()
            node.tags.append(NodeTag(tag=match.tag, score=match.score, source="rule"))
        self.db.commit()
        return nodes

    def generate_plan(self, import_id: int, strategy_version: str, dry_run: bool, node_ids: list[int] | None = None) -> OrganizationPlan:
        nodes = self._load_nodes(import_id=import_id, node_ids=node_ids)
        if not nodes:
            raise ValueError("No folder nodes found for planning")

        plan = OrganizationPlan(
            strategy_version=strategy_version,
            scope_desc=f"import_id={import_id}, node_count={len(nodes)}",
            status="draft",
            dry_run=dry_run,
        )
        self.db.add(plan)
        self.db.flush()

        clusters = cluster_nodes(nodes)
        target_paths: list[str] = []
        prepared_items: list[tuple[TreeNode, str, float, str]] = []
        for node in nodes:
            match = self.classifier.classify(node.raw_name, node.parent_path)
            normalized_name = normalize_folder_name(node.raw_name).replace("/", " ").strip() or node.raw_name
            target_name = match.target_template.format(normalized_name=normalized_name)
            target_path = f"{match.target_root.rstrip('/')}/{target_name}".replace("//", "/")
            confidence = min(0.99, match.score + (0.05 if len(clusters.get(normalized_name, [])) > 1 else 0.0))
            target_paths.append(target_path)
            prepared_items.append((node, target_path, confidence, match.tag))

        counts = Counter(target_paths)
        for node, target_path, confidence, tag in prepared_items:
            conflict_status, reason = self.conflict_detector.detect(node.raw_path, target_path, counts)
            action_type = "noop" if conflict_status == "noop" else "move"
            item = OrganizationPlanItem(
                plan_id=plan.id,
                node_id=node.id,
                source_path=node.raw_path,
                suggested_target_path=target_path,
                action_type=action_type,
                confidence=confidence,
                conflict_status=conflict_status,
                reason=reason or f"inferred_tag={tag}",
            )
            self.db.add(item)

        self.db.commit()
        self.db.refresh(plan)
        return plan

    def generate_keyword_move_plan(
        self,
        import_id: int,
        keyword: str | None,
        target_path: str,
        dry_run: bool,
        keyword_entry_id: int | None = None,
        case_sensitive: bool = False,
        node_ids: list[int] | None = None,
    ) -> OrganizationPlan:
        nodes = self._load_nodes(import_id=import_id, node_ids=node_ids)
        if not nodes:
            raise ValueError("No folder nodes found for planning")

        matched_nodes: list[TreeNode]
        keyword_label: str
        if keyword_entry_id is not None:
            matched_nodes, keyword_label = self._load_nodes_by_keyword_hits(
                import_id=import_id,
                keyword_entry_id=keyword_entry_id,
                node_ids=node_ids,
            )
        else:
            if not keyword:
                raise ValueError("keyword or keyword_entry_id is required")
            matched_nodes = [
                node for node in nodes if self._matches_keyword(node.raw_name, keyword=keyword, case_sensitive=case_sensitive)
            ]
            keyword_label = keyword
        if not matched_nodes:
            raise ValueError(f"No folder nodes matched keyword: {keyword_label}")

        normalized_target_root = self._normalize_target_path(target_path)
        plan = OrganizationPlan(
            strategy_version=f"keyword-move:{keyword_label}",
            scope_desc=f"import_id={import_id}, keyword={keyword_label}, target_path={normalized_target_root}, node_count={len(matched_nodes)}",
            status="draft",
            dry_run=dry_run,
        )
        self.db.add(plan)
        self.db.flush()

        target_paths = [self._join_target(normalized_target_root, node.raw_name) for node in matched_nodes]
        counts = Counter(target_paths)

        for node, candidate_target in zip(matched_nodes, target_paths, strict=True):
            conflict_status, reason = self.conflict_detector.detect(node.raw_path, candidate_target, counts)
            item = OrganizationPlanItem(
                plan_id=plan.id,
                node_id=node.id,
                source_path=node.raw_path,
                suggested_target_path=candidate_target,
                action_type="noop" if conflict_status == "noop" else "move",
                confidence=0.99,
                conflict_status=conflict_status,
                reason=reason or f"keyword={keyword_label}",
            )
            self.db.add(item)

        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _load_nodes_by_keyword_hits(
        self,
        *,
        import_id: int,
        keyword_entry_id: int,
        node_ids: list[int] | None = None,
    ) -> tuple[list[TreeNode], str]:
        entry = self.db.scalar(select(KeywordEntry).where(KeywordEntry.id == keyword_entry_id))
        if entry is None:
            raise ValueError(f"KeywordEntry {keyword_entry_id} not found")

        node_query = (
            select(TreeNode)
            .join(KeywordHit, KeywordHit.source_path == TreeNode.raw_path)
            .where(TreeNode.import_id == import_id)
            .where(TreeNode.node_type == "folder")
            .where(KeywordHit.import_id == import_id)
            .where(KeywordHit.keyword_entry_id == keyword_entry_id)
            .order_by(TreeNode.id.asc())
            .distinct()
        )
        if node_ids:
            node_query = node_query.where(TreeNode.id.in_(node_ids))
        nodes = list(self.db.scalars(node_query).all())
        return nodes, entry.canonical_name

    def generate_plan_from_tasks(
        self,
        *,
        import_id: int,
        dry_run: bool,
        keyword_entry_id: int | None = None,
        task_ids: list[int] | None = None,
    ) -> list[OrganizationPlan]:
        task_query = select(OrganizeTask).where(OrganizeTask.import_id == import_id).where(OrganizeTask.status == "pending")
        if keyword_entry_id is not None:
            task_query = task_query.where(OrganizeTask.keyword_entry_id == keyword_entry_id)
        if task_ids:
            task_query = task_query.where(OrganizeTask.id.in_(task_ids))
        tasks = list(self.db.scalars(task_query.order_by(OrganizeTask.id.asc())).all())
        if not tasks:
            raise ValueError("No organize tasks found for planning")

        max_items = max(1, self.settings.executor_max_items_per_run)
        grouped_tasks: dict[str, list[OrganizeTask]] = defaultdict(list)
        for task in tasks:
            group_key = task.matched_canonical_name or f"keyword_id:{task.keyword_entry_id or 'unknown'}"
            grouped_tasks[group_key].append(task)

        plan_specs: list[tuple[str, list[OrganizeTask]]] = []
        for group_key in sorted(grouped_tasks):
            group_tasks = grouped_tasks[group_key]
            for index in range(0, len(group_tasks), max_items):
                chunk = group_tasks[index : index + max_items]
                plan_specs.append((group_key, chunk))

        plans: list[OrganizationPlan] = []
        group_offsets: dict[str, int] = defaultdict(int)
        for group_key, chunk in plan_specs:
            scope_parts = [f"import_id={import_id}", f"task_count={len(chunk)}", f"group={group_key}"]
            strategy_version = "organize-task-plan"
            if len(grouped_tasks) > 1 or len(plan_specs) > 1:
                strategy_version = f"organize-task-plan:{group_key}"
            if len(grouped_tasks[group_key]) > max_items:
                chunk_index = group_offsets[group_key] + 1
                strategy_version = f"{strategy_version}:batch-{chunk_index}"
                scope_parts.append(f"batch={chunk_index}")
                group_offsets[group_key] += 1

            plan = OrganizationPlan(
                strategy_version=strategy_version,
                scope_desc=", ".join(scope_parts),
                status="draft",
                dry_run=dry_run,
            )
            self.db.add(plan)
            self.db.flush()

            target_paths = [task.target_path for task in chunk]
            counts = Counter(target_paths)
            for task in chunk:
                conflict_status, reason = self.conflict_detector.detect(task.source_path, task.target_path, counts)
                item = OrganizationPlanItem(
                    plan_id=plan.id,
                    node_id=task.node_id,
                    source_path=task.source_path,
                    suggested_target_path=task.target_path,
                    action_type="noop" if conflict_status == "noop" else "move",
                    confidence=0.99,
                    conflict_status=conflict_status,
                    reason=reason or f"organize_task_id={task.id}",
                )
                self.db.add(item)
            plans.append(plan)

        self.db.commit()
        for plan in plans:
            self.db.refresh(plan)
        return plans

    @staticmethod
    def _matches_keyword(name: str, keyword: str, case_sensitive: bool) -> bool:
        if case_sensitive:
            return keyword in name
        return keyword.lower() in name.lower()

    @staticmethod
    def _normalize_target_path(target_path: str) -> str:
        cleaned = target_path.strip()
        if not cleaned:
            raise ValueError("target_path cannot be empty")
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned.rstrip("/")

    @staticmethod
    def _join_target(target_root: str, raw_name: str) -> str:
        return str(PurePosixPath(target_root) / raw_name)
