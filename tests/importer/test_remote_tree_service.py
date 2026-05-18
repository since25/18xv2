from __future__ import annotations

from unittest.mock import Mock

from app.services.importer.remote_tree_service import RemoteTreeFetchService


def test_export_root_cid_uses_integer_zero(db_session, monkeypatch) -> None:
    from app.models.tree import TreeImport

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 123}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "1", "pick_code": "pick-code"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Response:
        content = b"|\xe2\x80\x94\xe2\x80\x94\xe2\x80\x94\xe2\x80\x94 \xe6\xa0\xb9\xe7\x9b\xae\xe5\xbd\x95\n"

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *args, **kwargs: _Response())

    # 创建占位记录
    placeholder = TreeImport(
        status="pending",
        source_filename="remote:根目录",
        source_type="remote_115",
        note="cid=0 depth_limit=3",
    )
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    service.fetch_subtree(cid="0", path_label="根目录", depth_limit=3, import_id=placeholder.id)

    payload = fake_client.fs_export_dir.call_args.args[0]
    assert payload["file_ids"] == 0


def test_root_cid_falls_back_to_recursive_listing_when_export_dir_rejects_root(db_session, monkeypatch) -> None:
    from app.models.tree import TreeImport

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {
        "state": False,
        "errno": 90008,
        "error": "文件（夹）不存在或已经删除。",
    }
    fake_client.fs_files.side_effect = [
        {
            "count": 2,
            "data": [
                {"fid": "10", "fn": "Movies", "fc": "0"},
                {"fid": "11", "fn": "README.txt", "fc": "1"},
            ],
        },
        {
            "count": 1,
            "data": [
                {"fid": "12", "fn": "Action", "fc": "0"},
            ],
        },
        {"count": 0, "data": []},
    ]

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)

    # 创建占位记录
    placeholder = TreeImport(
        status="pending",
        source_filename="remote:根目录",
        source_type="remote_115",
        note="cid=0 depth_limit=3",
    )
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    result = service.fetch_subtree(cid="0", path_label="根目录", depth_limit=2, import_id=placeholder.id)

    assert result.source_type == "remote_115"
    assert result.status == "completed"
    assert "folders=2" in (result.note or "")
    assert fake_client.fs_files.call_count == 2


def test_persist_tree_import_updates_existing_record_not_insert(db_session, monkeypatch) -> None:
    """fetch_subtree 完成后 DB 中只有 1 条 TreeImport 记录，不产生第二条。"""
    from app.models.tree import TreeImport, TreeNode
    from sqlalchemy import select, func

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 99}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "1", "pick_code": "pc1"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- 根目录\n| |- 子目录\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:根目录",
                              source_type="remote_115", note="cid=1 depth_limit=3")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    result = service.fetch_subtree(cid="1", path_label="根目录", depth_limit=3,
                                   import_id=placeholder.id)

    total_imports = db_session.scalar(select(func.count()).select_from(TreeImport))
    assert total_imports == 1, f"期望 1 条 TreeImport 记录，实际 {total_imports} 条"
    assert result.id == placeholder.id
    assert result.status == "completed"


def test_persist_tree_import_backfills_parent_id(db_session, monkeypatch) -> None:
    """_persist_tree_import 完成后子节点的 parent_id 应正确指向父节点。"""
    from app.models.tree import TreeImport, TreeNode
    from sqlalchemy import select

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 88}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "2", "pick_code": "pc2"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- root\n| |- parent\n| | |- child\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:root",
                              source_type="remote_115", note="cid=2 depth_limit=3")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    result = service.fetch_subtree(cid="2", path_label="root", depth_limit=3,
                                   import_id=placeholder.id)

    nodes = db_session.scalars(
        select(TreeNode).where(TreeNode.import_id == result.id)
    ).all()
    by_name = {n.raw_name: n for n in nodes}
    assert by_name["child"].parent_id == by_name["parent"].id
    assert by_name["parent"].parent_id == by_name["root"].id


def test_progress_cb_called_with_expected_stages(db_session, monkeypatch) -> None:
    """fetch_subtree 应按顺序调用 progress_cb，包含 '轮询导出状态' 和 '写入数据库'。"""
    from app.models.tree import TreeImport

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 77}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "3", "pick_code": "pc3"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- root\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:root",
                              source_type="remote_115", note="cid=3 depth_limit=1")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    stages: list[str] = []
    def cb(stage: str, current: int, total: int) -> None:
        stages.append(stage)

    service.fetch_subtree(cid="3", path_label="root", depth_limit=1,
                          import_id=placeholder.id, progress_cb=cb)

    assert "轮询导出状态" in stages
    assert "写入数据库" in stages
