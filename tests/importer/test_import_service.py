from __future__ import annotations

import pytest
from app.services.importer.import_service import TreeImportService


TREE_WITH_NESTED_FOLDERS = b"""\
|---- root
| |- parent
| | |- child
"""


def test_batch_insert_sets_parent_id_correctly(db_session):
    """批量插入后 parent_id 应正确回填，child.parent_id == parent.id。"""
    svc = TreeImportService(db_session)
    result = svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)

    from app.models.tree import TreeNode
    from sqlalchemy import select
    nodes = db_session.scalars(
        select(TreeNode).where(TreeNode.import_id == result.id)
    ).all()
    by_name = {n.raw_name: n for n in nodes}

    assert by_name["child"].parent_id == by_name["parent"].id
    assert by_name["parent"].parent_id == by_name["root"].id
    assert by_name["root"].parent_id is None


def test_batch_insert_single_flush_not_n_flushes(db_session, monkeypatch):
    """验证不再发生 N 次 flush：flush 调用次数应 ≤ 2。"""
    flush_count = 0
    original_flush = db_session.flush

    def counting_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", counting_flush)

    svc = TreeImportService(db_session)
    svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)

    # 原来 N 个 folder 就有 N 次 flush；现在最多 2 次（阶段1 + 可选阶段2）
    assert flush_count <= 2


def test_import_result_status_is_completed(db_session):
    svc = TreeImportService(db_session)
    result = svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)
    assert result.status == "completed"
    assert "folders=3" in (result.note or "")
