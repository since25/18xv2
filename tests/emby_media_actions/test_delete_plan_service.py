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
