from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.routes.files_115 import FileInfoRequest, get_file_info
from app.models.tree import NodeFile, TreeImport
from app.services.cleanup.noise_cleanup_service import NoiseCleanupService
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.local_organize_service import LocalOrganizeService


def test_file_info_route_uses_client_file_info() -> None:
    class StubClient:
        def get_file_info(self, *, file_id: str) -> dict:
            return {"file_size": 123, "utime": 456}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(client_115=StubClient())))
    response = get_file_info(FileInfoRequest(cids=["cid-1"]), request)

    assert response.results["cid-1"].size == 123
    assert response.results["cid-1"].modified_at == "456"


def test_noise_cleanup_allowlist_requires_path_boundary(monkeypatch) -> None:
    from app.core.config import Settings

    service = NoiseCleanupService.__new__(NoiseCleanupService)
    service.settings = Settings(TEST_ALLOWED_PATH_PREFIXES=["/根目录/测试"])

    with pytest.raises(PermissionError):
        service._ensure_allowed("/根目录/测试2/file.txt", dry_run=False)
    service._ensure_allowed("/根目录/测试/file.txt", dry_run=False)


def test_noise_cleanup_resolves_children_beyond_first_page() -> None:
    client = Fake115Client()
    for index in range(501):
        client.add_node(
            NodePayload(
                id=str(index + 1), name=f"file-{index}", path=f"file-{index}", parent_id=None, is_file=True
            )
        )

    service = NoiseCleanupService.__new__(NoiseCleanupService)
    service.client = client
    assert service._resolve_path_to_id("file-500") == "501"


def test_local_organize_scan_does_not_create_target(tmp_path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    target = tmp_path / "not-created"

    service = LocalOrganizeService.__new__(LocalOrganizeService)
    service.db = None
    response = service.scan(
        root_path=str(root),
        target_root=str(target),
        whitelist_keywords=["movie"],
    )

    assert response.target_root == str(target.resolve())
    assert not target.exists()


def test_fake_file_info_returns_metadata_shape() -> None:
    client = Fake115Client()
    client.add_node(NodePayload(id="1", name="movie.mp4", path="movie.mp4", parent_id=None, is_file=True))

    info = client.get_file_info("1")
    assert info["file_id"] == "1"
    assert info["file_name"] == "movie.mp4"


def test_background_job_state_survives_new_session(db_session) -> None:
    from app.services.background_job_service import BackgroundJobService

    BackgroundJobService.create(db_session, "job-1", "whitelist:scan")
    BackgroundJobService.update(db_session, "job-1", stage="扫描中", current=2, total=5)

    state = BackgroundJobService.get(db_session, "job-1")
    assert state is not None
    assert state["stage"] == "扫描中"
    assert state["current"] == 2
    assert state["done"] is False


def test_remote_persist_can_store_file_nodes(db_session) -> None:
    from app.services.importer.remote_tree_service import RemoteTreeFetchService

    tree_import = TreeImport(source_filename="remote.txt", status="pending", source_type="remote_115")
    db_session.add(tree_import)
    db_session.commit()
    service = RemoteTreeFetchService(db_session)

    service._persist_tree_import(
        import_id=tree_import.id,
        cid="1",
        depth_limit=2,
        raw_bytes="|---- root\n| |- movie.mp4\n".encode(),
        source_label="root",
        folders_only=False,
    )

    files = db_session.scalars(select(NodeFile).where(NodeFile.import_id == tree_import.id)).all()
    assert [item.raw_name for item in files] == ["movie.mp4"]
