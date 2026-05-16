"""
PlanExecutor dry_run 测试。验证 dry-run 模式不产生真实 115 写操作。
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.organization import OrganizationPlan, OrganizationPlanItem
from app.models.tree import TreeImport, TreeNode
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.executor.executor import PlanExecutor


def _make_tree_import(db: Session) -> TreeImport:
    imp = TreeImport(source_filename="test.txt", status="done")
    db.add(imp)
    db.flush()
    return imp


def _make_tree_node(db: Session, import_id: int, name: str, raw_path: str) -> TreeNode:
    node = TreeNode(
        import_id=import_id,
        raw_name=name,
        normalized_name=name,
        raw_path=raw_path,
        parent_path=None,
        depth=1,
        node_type="folder",
        fingerprint_hint="abc123",
    )
    db.add(node)
    db.flush()
    return node


def _make_plan_with_item(db: Session, node: TreeNode, source: str, target: str) -> OrganizationPlan:
    plan = OrganizationPlan(strategy_version="v1", scope_desc="test", status="draft", dry_run=True)
    db.add(plan)
    db.flush()
    item = OrganizationPlanItem(
        plan_id=plan.id,
        node_id=node.id,
        source_path=source,
        suggested_target_path=target,
        action_type="move",
        confidence=1.0,
        conflict_status="none",
    )
    db.add(item)
    db.commit()
    return plan


class TestDryRun:
    def test_dry_run_succeeds_without_real_calls(self, db_session: Session, fake_client: Fake115Client):
        """dry-run 模式下应当完成并返回 completed 状态，且不调用 115 写 API。"""
        # 准备测试数据：电影目录在根下（parent_id=None），旧名在电影下（parent_id="9"）
        fake_client.add_node(NodePayload(id="9", name="电影", path="电影", parent_id=None, is_file=False))
        fake_client.add_node(NodePayload(id="10", name="旧名", path="电影/旧名", parent_id="9", is_file=False))

        imp = _make_tree_import(db_session)
        node = _make_tree_node(db_session, imp.id, "旧名", "电影/旧名")
        plan = _make_plan_with_item(db_session, node, "电影/旧名", "整理后/旧名")

        executor = PlanExecutor(db=db_session, client=fake_client)
        job = executor.execute_plan(plan.id, dry_run=True)

        assert job.status == "completed"
        assert job.dry_run is True
        assert job.rollback_status == "not_required"

    def test_dry_run_noop_item_returns_noop_status(self, db_session: Session, fake_client: Fake115Client):
        """conflict_status=noop 的条目进入 _execute_item 后，action_type=noop 返回 api_status='noop'。"""
        # 需要把节点加入 fake_client，因为 _execute_item 先做路径解析
        # 电影目录：parent_id=None → 出现在根目录 list_files(cid="0") 的结果中
        fake_client.add_node(NodePayload(id="19", name="电影", path="电影", parent_id=None, is_file=False))
        # 不变：parent_id="19" → 出现在 list_files(cid="19") 的结果中
        fake_client.add_node(NodePayload(id="20", name="不变", path="电影/不变", parent_id="19", is_file=False))

        imp = _make_tree_import(db_session)
        node = _make_tree_node(db_session, imp.id, "不变", "电影/不变")

        plan = OrganizationPlan(strategy_version="v1", scope_desc="test", status="draft", dry_run=True)
        db_session.add(plan)
        db_session.flush()
        item = OrganizationPlanItem(
            plan_id=plan.id,
            node_id=node.id,
            source_path="电影/不变",
            suggested_target_path="电影/不变",
            action_type="noop",
            confidence=1.0,
            conflict_status="noop",
        )
        db_session.add(item)
        db_session.commit()

        executor = PlanExecutor(db=db_session, client=fake_client)
        job = executor.execute_plan(plan.id, dry_run=True)
        assert job.status == "completed"
        # noop action_type：_execute_item 返回 api_status="noop"
        assert job.logs[0].api_status == "noop"

    def test_real_run_requires_confirmation(self, db_session: Session, fake_client: Fake115Client):
        """真实执行时 confirm_real_run=False 应抛 ValueError。"""
        imp = _make_tree_import(db_session)
        node = _make_tree_node(db_session, imp.id, "文件", "电影/文件")
        plan = _make_plan_with_item(db_session, node, "电影/文件", "整理后/文件")

        executor = PlanExecutor(db=db_session, client=fake_client)
        with pytest.raises(ValueError, match="confirm_real_run"):
            executor.execute_plan(plan.id, dry_run=False, confirm_real_run=False)

    def test_blocked_item_marks_job_blocked(self, db_session: Session, fake_client: Fake115Client):
        """执行条目被阻塞时，job.status 也应是 blocked，而不是 completed。"""
        imp = _make_tree_import(db_session)
        node = _make_tree_node(db_session, imp.id, "丢失目录", "电影/丢失目录")
        plan = _make_plan_with_item(db_session, node, "电影/丢失目录", "整理后/丢失目录")

        executor = PlanExecutor(db=db_session, client=fake_client)
        job = executor.execute_plan(plan.id, dry_run=True)

        assert job.status == "blocked"
        assert job.logs[0].api_status == "blocked"
