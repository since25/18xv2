from __future__ import annotations

from unittest.mock import Mock

from app.services.importer.remote_tree_service import RemoteTreeFetchService


def test_export_root_cid_uses_integer_zero(db_session, monkeypatch) -> None:
    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 123}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "1", "pick_code": "pick-code"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Response:
        content = b"|\xe2\x80\x94\xe2\x80\x94\xe2\x80\x94\xe2\x80\x94 \xe6\xa0\xb9\xe7\x9b\xae\xe5\xbd\x95\n"

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *args, **kwargs: _Response())

    service.fetch_subtree(cid="0", path_label="根目录", depth_limit=3)

    payload = fake_client.fs_export_dir.call_args.args[0]
    assert payload["file_ids"] == 0


def test_root_cid_falls_back_to_recursive_listing_when_export_dir_rejects_root(db_session, monkeypatch) -> None:
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

    result = service.fetch_subtree(cid="0", path_label="根目录", depth_limit=2)

    assert result.source_type == "remote_115"
    assert result.status == "completed"
    assert "folders=2" in (result.note or "")
    assert fake_client.fs_files.call_count == 2
