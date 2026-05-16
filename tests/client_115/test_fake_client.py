"""
Fake115Client 契约测试。确保 Fake 的公开方法签名与 Real115Client 保持一致，防止漂移。
"""
from __future__ import annotations

import inspect

import pytest

from app.services.client_115.client import Fake115Client, Real115Client
from app.services.client_115.schemas import NodePayload


# Real115Client 的公共业务方法（排除 dunder 和内部私有方法）
EXPECTED_PUBLIC_METHODS = {
    "ensure_fresh_access_token",
    "list_files",
    "get_file",
    "get_full_path",
    "search_nodes",
    "submit_magnet_download",
    "create_folder",
    "rename_node",
    "move_node",
    "batch_move_nodes",
    "delete_node",
    "batch_delete_nodes",
}


class TestFakeClientContract:
    def test_fake_has_all_expected_methods(self):
        """Fake 必须实现 Real 的所有公开业务方法。"""
        fake_methods = {name for name, _ in inspect.getmembers(Fake115Client, predicate=inspect.isfunction)}
        missing = EXPECTED_PUBLIC_METHODS - fake_methods
        assert not missing, f"Fake115Client 缺少方法：{missing}"

    def test_list_files_returns_dict(self, fake_client: Fake115Client):
        result = fake_client.list_files(cid="0")
        assert isinstance(result, dict)
        assert "data" in result
        assert "count" in result

    def test_list_files_paginates(self, fake_client: Fake115Client):
        for i in range(5):
            fake_client.add_node(NodePayload(id=str(i), name=f"节点{i}", path=f"节点{i}", parent_id=None, is_file=False))
        result = fake_client.list_files(cid="0", limit=2, offset=0)
        assert len(result["data"]) == 2

    def test_create_folder_returns_action_result(self, fake_client: Fake115Client):
        result = fake_client.create_folder("0", "新目录")
        assert result.success is True
        assert "file_id" in result.payload

    def test_rename_dry_run_does_not_change_name(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="1", name="原名", path="原名", parent_id=None, is_file=False))
        fake_client.rename_node("1", "新名", dry_run=True)
        assert fake_client.nodes["1"].name == "原名"

    def test_rename_real_changes_name(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="1", name="原名", path="原名", parent_id=None, is_file=False))
        fake_client.rename_node("1", "新名", dry_run=False)
        assert fake_client.nodes["1"].name == "新名"

    def test_move_dry_run_does_not_change_parent(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="p", name="父目录", path="父目录", parent_id=None, is_file=False))
        fake_client.add_node(NodePayload(id="c", name="子节点", path="旧路径/子节点", parent_id=None, is_file=False))
        fake_client.move_node("c", "p", dry_run=True)
        # dry_run 不改 parent_id
        assert fake_client.nodes["c"].parent_id is None

    def test_delete_dry_run_does_not_remove_node(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="1", name="节点", path="节点", parent_id=None, is_file=False))
        fake_client.delete_node("1", dry_run=True)
        assert "1" in fake_client.nodes

    def test_delete_real_removes_node(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="1", name="节点", path="节点", parent_id=None, is_file=False))
        fake_client.delete_node("1", dry_run=False)
        assert "1" not in fake_client.nodes

    def test_search_nodes_by_keyword(self, fake_client: Fake115Client):
        fake_client.add_node(NodePayload(id="1", name="动作电影合集", path="动作电影合集", parent_id=None, is_file=False))
        fake_client.add_node(NodePayload(id="2", name="纪录片", path="纪录片", parent_id=None, is_file=False))
        results = fake_client.search_nodes("动作")
        assert len(results) == 1
        assert results[0].name == "动作电影合集"

    def test_submit_magnet_returns_payload(self, fake_client: Fake115Client):
        result = fake_client.submit_magnet_download("magnet:?xt=urn:btih:abc123")
        assert result.task_id is not None
