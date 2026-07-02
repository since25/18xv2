from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.emby_media_actions import EmbyMediaMapping, EmbyMediaMappingPath
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import ClientActionResult, NodePayload
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService


def _mapping(
    db_session,
    tmp_path: Path,
    *,
    item_id: str = "item-1",
    title: str = "测试电影",
    item_type: str = "Movie",
    series_id: str | None = None,
    season_id: str | None = None,
    remote_file_id: str = "remote-1",
    source_path: Path | None = None,
    organized_path: Path | None = None,
) -> EmbyMediaMapping:
    source_root = tmp_path / "source"
    organized_root = tmp_path / "organized"
    source_root.mkdir(exist_ok=True)
    organized_root.mkdir(exist_ok=True)
    source = source_path or source_root / f"{item_id}.source.strm"
    organized = organized_path or organized_root / f"{item_id}.organized.strm"
    source.parent.mkdir(parents=True, exist_ok=True)
    organized.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("url", encoding="utf-8")
    organized.write_text("url", encoding="utf-8")
    mapping = EmbyMediaMapping(
        emby_item_id=item_id,
        emby_item_type=item_type,
        emby_title=title,
        emby_series_id=series_id,
        emby_season_id=season_id,
        emby_episode_id=item_id if item_type == "Episode" else None,
        alist_url=f"http://example.test/d/115_OPEN/{remote_file_id}.mkv",
        alist_mount_name="115_OPEN",
        remote_provider="115",
        remote_path=f"/{remote_file_id}.mkv",
        remote_file_id=remote_file_id,
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
        self.calls: list[tuple[str, bool]] = []

    def delete_node(self, file_id: str, dry_run: bool = True):
        self.calls.append((file_id, dry_run))
        return super().delete_node(file_id, dry_run=dry_run)


class FailingDryRun115Client:
    def delete_node(self, file_id: str, dry_run: bool = True):
        raise RuntimeError(f"dry-run failed for {file_id}")


class ExecuteFailing115Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def delete_node(self, file_id: str, dry_run: bool = True):
        self.calls.append((file_id, dry_run))
        if dry_run:
            return ClientActionResult(success=True, action="delete", message="dry-run", payload={"file_id": file_id})
        raise RuntimeError("remote delete failed")


def _add_remote_nodes(client: Fake115Client, *file_ids: str) -> None:
    for file_id in file_ids:
        client.add_node(NodePayload(id=file_id, name=f"{file_id}.mkv", path=f"/{file_id}.mkv", parent_id="0", is_file=True))


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
    _add_remote_nodes(fake, "remote-1")
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])
    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    summary = service.execute_plan(plan.id, confirm=True)

    assert summary.deleted == 3
    assert summary.failed == 0
    assert "remote-1" not in fake.nodes


def test_episode_scope_targets_only_input_mapping(db_session, tmp_path: Path) -> None:
    first = _mapping(
        db_session,
        tmp_path,
        item_id="episode-1",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-1",
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-2",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-2",
    )
    fake = Fake115Client()
    _add_remote_nodes(fake, "remote-1", "remote-2")

    plan = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=first.id,
        scope="episode",
        source="test",
    )

    assert plan.total_items == 3
    assert {item.remote_file_id for item in plan.items if item.group == "remote_115"} == {"remote-1"}
    assert {Path(item.target_path).name for item in plan.items if item.target_path} == {
        "episode-1.source.strm",
        "episode-1.organized.strm",
        "remote-1.mkv",
    }


def test_season_scope_expands_to_mappings_with_same_season(db_session, tmp_path: Path) -> None:
    first = _mapping(
        db_session,
        tmp_path,
        item_id="episode-1",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-1",
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-2",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-2",
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-3",
        item_type="Episode",
        series_id="series-1",
        season_id="season-2",
        remote_file_id="remote-3",
    )
    fake = Fake115Client()
    _add_remote_nodes(fake, "remote-1", "remote-2", "remote-3")

    plan = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=first.id,
        scope="season",
        source="test",
    )

    assert plan.total_items == 6
    assert {item.remote_file_id for item in plan.items if item.group == "remote_115"} == {"remote-1", "remote-2"}
    assert {Path(item.target_path).name for item in plan.items if item.target_path} == {
        "episode-1.source.strm",
        "episode-1.organized.strm",
        "remote-1.mkv",
        "episode-2.source.strm",
        "episode-2.organized.strm",
        "remote-2.mkv",
    }


def test_series_scope_expands_to_mappings_with_same_series(db_session, tmp_path: Path) -> None:
    first = _mapping(
        db_session,
        tmp_path,
        item_id="episode-1",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-1",
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-2",
        item_type="Episode",
        series_id="series-1",
        season_id="season-2",
        remote_file_id="remote-2",
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-3",
        item_type="Episode",
        series_id="series-2",
        season_id="season-3",
        remote_file_id="remote-3",
    )
    fake = Fake115Client()
    _add_remote_nodes(fake, "remote-1", "remote-2", "remote-3")

    plan = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=first.id,
        scope="series",
        source="test",
    )

    assert plan.total_items == 6
    assert {item.remote_file_id for item in plan.items if item.group == "remote_115"} == {"remote-1", "remote-2"}


def test_season_and_series_scope_require_group_ids(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path, item_type="Episode")
    service = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)])

    with pytest.raises(ValueError, match="season scope requires emby_season_id"):
        service.create_plan_from_mapping(mapping_id=mapping.id, scope="season", source="test")

    with pytest.raises(ValueError, match="series scope requires emby_series_id"):
        service.create_plan_from_mapping(mapping_id=mapping.id, scope="series", source="test")


def test_create_plan_deduplicates_local_paths_and_remote_files(db_session, tmp_path: Path) -> None:
    shared_source = tmp_path / "source" / "shared.strm"
    first = _mapping(
        db_session,
        tmp_path,
        item_id="episode-1",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-1",
        source_path=shared_source,
    )
    _mapping(
        db_session,
        tmp_path,
        item_id="episode-2",
        item_type="Episode",
        series_id="series-1",
        season_id="season-1",
        remote_file_id="remote-1",
        source_path=shared_source,
    )
    fake = Fake115Client()
    _add_remote_nodes(fake, "remote-1")

    plan = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=first.id,
        scope="season",
        source="test",
    )

    assert plan.total_items == 4
    assert [item.target_path for item in plan.items if item.group == "source_strm"] == [str(shared_source)]
    assert [item.remote_file_id for item in plan.items if item.group == "remote_115"] == ["remote-1"]


def test_create_plan_uses_local_dry_run_status_for_blocked_and_missing_items(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    service = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)])

    class StubPathGuard:
        def delete_path(self, path: str, *, dry_run: bool):
            assert dry_run is True
            if path.endswith(".source.strm"):
                return SimpleNamespace(path=path, entry_type="missing", status="not_found", error_message="path_not_found")
            return SimpleNamespace(path=path, entry_type="dir", status="blocked", error_message="directory_delete_not_allowed")

    service.path_guard = StubPathGuard()

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    local_items = {item.group: item for item in plan.items if item.group != "remote_115"}

    assert local_items["source_strm"].status == "blocked"
    assert local_items["source_strm"].blocked_reason == "path_not_found"
    assert local_items["source_strm"].dry_run_result == "not_found"
    assert local_items["emby_library"].status == "blocked"
    assert local_items["emby_library"].blocked_reason == "directory_delete_not_allowed"
    assert local_items["emby_library"].dry_run_result == "blocked"


def test_create_plan_blocks_remote_115_when_client_missing(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)

    plan = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=mapping.id,
        scope="movie",
        source="test",
    )
    remote_item = next(item for item in plan.items if item.group == "remote_115")

    assert remote_item.status == "blocked"
    assert remote_item.blocked_reason == "client_115_required"


def test_create_plan_blocks_remote_115_when_dry_run_fails(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)

    plan = EmbyDeletePlanService(
        db_session,
        client_115=FailingDryRun115Client(),
        allowed_roots=[str(tmp_path)],
    ).create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    remote_item = next(item for item in plan.items if item.group == "remote_115")

    assert remote_item.status == "blocked"
    assert remote_item.blocked_reason == "remote_dry_run_failed"
    assert remote_item.error_message == "dry-run failed for remote-1"


def test_execute_failed_plan_raises_without_changing_item_statuses(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    fake = ExecuteFailing115Client()
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])
    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    first_summary = service.execute_plan(plan.id, confirm=True)

    assert first_summary.deleted == 2
    assert first_summary.failed == 1
    assert fake.calls == [("remote-1", True), ("remote-1", False)]
    assert plan.status == "failed"
    statuses_before = {item.group: item.status for item in plan.items}

    with pytest.raises(ValueError, match="delete plan is not executable"):
        service.execute_plan(plan.id, confirm=True)

    db_session.refresh(plan)
    assert plan.status == "failed"
    assert {item.group: item.status for item in plan.items} == statuses_before
    assert fake.calls == [("remote-1", True), ("remote-1", False)]


def test_create_plan_blocks_unsupported_remote_provider(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    mapping.remote_provider = "webdav"
    db_session.commit()
    fake = Tracking115Client()
    _add_remote_nodes(fake, "remote-1")
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    remote_item = next(item for item in plan.items if item.group == "remote_115")
    summary = service.execute_plan(plan.id, confirm=True)

    assert remote_item.status == "blocked"
    assert remote_item.blocked_reason == "unsupported_remote_provider"
    assert summary.deleted == 2
    assert summary.blocked == 1
    assert fake.calls == []
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
    _add_remote_nodes(fake, "remote-1")
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path / "organized")])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")
    blocked_item = next(item for item in plan.items if item.group == "source_strm")
    summary = service.execute_plan(plan.id, confirm=True)

    assert blocked_item.status == "blocked"
    assert blocked_item.blocked_reason == "path_outside_allowed_roots"
    assert blocked_file.exists()
    assert summary.blocked == 1
