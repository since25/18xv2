from __future__ import annotations

from pathlib import Path

import pytest

from app.models.emby_media_actions import EmbyMediaMapping, EmbyMediaMappingPath
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService


def _mapping(db_session, tmp_path: Path) -> EmbyMediaMapping:
    source_root = tmp_path / "source"
    organized_root = tmp_path / "organized"
    source_root.mkdir()
    organized_root.mkdir()
    source = source_root / "a.strm"
    organized = organized_root / "a.strm"
    source.write_text("url", encoding="utf-8")
    organized.write_text("url", encoding="utf-8")
    mapping = EmbyMediaMapping(
        emby_item_id="item-1",
        emby_item_type="Movie",
        emby_title="测试电影",
        alist_url="http://example.test/d/115_OPEN/a.mkv",
        alist_mount_name="115_OPEN",
        remote_provider="115",
        remote_path="/a.mkv",
        remote_file_id="remote-1",
    )
    mapping.paths.extend(
        [
            EmbyMediaMappingPath(path_role="source_strm", path=str(source), root_name="source", root_path=str(source_root)),
            EmbyMediaMappingPath(path_role="organized_strm", path=str(organized), root_name="organized", root_path=str(organized_root)),
        ]
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


class Tracking115Client(Fake115Client):
    def __init__(self) -> None:
        super().__init__()
        self.deleted_file_ids: list[str] = []

    def delete_node(self, file_id: str, dry_run: bool = True):
        self.deleted_file_ids.append(file_id)
        return super().delete_node(file_id, dry_run=dry_run)


def test_create_plan_from_mapping_groups_items(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    service = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    assert plan.status == "draft"
    assert plan.total_items == 3
    assert [item.group for item in sorted(plan.items, key=lambda item: item.group)] == [
        "emby_library",
        "remote_115",
        "source_strm",
    ]


def test_execute_plan_requires_confirm(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    plan = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=mapping.id,
        scope="movie",
        source="test",
    )

    with pytest.raises(ValueError, match="confirm must be true"):
        EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)]).execute_plan(plan.id, confirm=False)


def test_execute_plan_deletes_local_and_remote(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    fake = Fake115Client()
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/a.mkv", parent_id="0", is_file=True))
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])
    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    summary = service.execute_plan(plan.id, confirm=True)

    assert summary.deleted == 3
    assert summary.failed == 0
    assert "remote-1" not in fake.nodes


def test_retry_failed_plan_processes_only_pending_items(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    fake = Tracking115Client()
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])
    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    first_summary = service.execute_plan(plan.id, confirm=True)

    assert first_summary.deleted == 2
    assert first_summary.failed == 1
    assert fake.deleted_file_ids == ["remote-1"]

    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/a.mkv", parent_id="0", is_file=True))
    for item in plan.items:
        if item.group == "remote_115":
            item.status = "pending"
            item.error_message = None
    db_session.commit()

    retry_summary = service.execute_plan(plan.id, confirm=True)

    assert retry_summary.deleted == 1
    assert retry_summary.failed == 0
    assert fake.deleted_file_ids == ["remote-1", "remote-1"]
    assert {item.group: item.status for item in plan.items} == {
        "source_strm": "deleted",
        "emby_library": "deleted",
        "remote_115": "deleted",
    }


def test_create_plan_blocks_unsupported_remote_provider(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    mapping.remote_provider = "webdav"
    db_session.commit()
    fake = Tracking115Client()
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/a.mkv", parent_id="0", is_file=True))
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    remote_item = next(item for item in plan.items if item.group == "remote_115")
    summary = service.execute_plan(plan.id, confirm=True)

    assert remote_item.status == "blocked"
    assert remote_item.blocked_reason == "unsupported_remote_provider"
    assert summary.deleted == 2
    assert summary.blocked == 1
    assert fake.deleted_file_ids == []
    assert "remote-1" in fake.nodes


def test_create_plan_blocks_local_paths_outside_allowed_roots(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    blocked_root = tmp_path / "blocked"
    blocked_root.mkdir()
    blocked_file = blocked_root / "outside.strm"
    blocked_file.write_text("url", encoding="utf-8")
    mapping.paths[0].path = str(blocked_file)
    mapping.paths[0].root_path = str(blocked_root)
    db_session.commit()
    fake = Fake115Client()
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/a.mkv", parent_id="0", is_file=True))
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path / "organized")])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    blocked_item = next(item for item in plan.items if item.group == "source_strm")
    summary = service.execute_plan(plan.id, confirm=True)

    assert blocked_item.status == "blocked"
    assert blocked_item.blocked_reason == "path_outside_allowed_roots"
    assert blocked_file.exists()
    assert summary.blocked == 1
