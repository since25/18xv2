from __future__ import annotations

from sqlalchemy import inspect

from app.core.config import Settings
from app.db.base import Base
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMediaMapping, EmbyMediaMappingPath


def test_emby_media_action_tables_are_registered() -> None:
    table_names = set(Base.metadata.tables)

    assert "emby_media_mappings" in table_names
    assert "emby_media_mapping_paths" in table_names
    assert "emby_delete_plans" in table_names
    assert "emby_delete_plan_items" in table_names
    assert "emby_metadata_snapshots" in table_names
    assert "emby_metadata_candidates" in table_names


def test_mapping_relationships_persist(db_session) -> None:
    mapping = EmbyMediaMapping(
        emby_item_id="item-1",
        emby_item_type="Movie",
        emby_title="美国队长",
        alist_url="http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv",
        alist_mount_name="115_OPEN",
        remote_provider="115",
        remote_path="/电影/a.mkv",
        remote_file_id="115-file-1",
    )
    mapping.paths.append(
        EmbyMediaMappingPath(
            path_role="source_strm",
            path="/mnt/cache/docker1/alist-strm/video/alist_mv1/a.strm",
            root_name="alist_mv1",
            root_path="/mnt/cache/docker1/alist-strm/video/alist_mv1",
            file_size=120,
            inode=11,
            link_count=1,
        )
    )
    db_session.add(mapping)
    db_session.commit()

    saved = db_session.get(EmbyMediaMapping, mapping.id)
    assert saved is not None
    assert saved.paths[0].path_role == "source_strm"
    assert saved.paths[0].link_count == 1


def test_delete_plan_defaults(db_session) -> None:
    plan = EmbyDeletePlan(
        source="iina_lua",
        emby_item_id="item-1",
        scope="movie",
        status="draft",
        summary="美国队长",
    )
    db_session.add(plan)
    db_session.commit()

    saved = db_session.get(EmbyDeletePlan, plan.id)
    assert saved is not None
    assert saved.status == "draft"
    assert saved.total_items == 0


def test_settings_parse_emby_media_action_csv_values() -> None:
    settings = Settings(
        EMBY_MEDIA_ACTIONS_STRM_ROOTS="/a,/b",
        EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS="/organized",
        EMBY_MEDIA_ACTIONS_SOURCE_ROOTS="/source-a,/source-b",
    )

    assert settings.emby_media_actions_strm_roots == ["/a", "/b"]
    assert settings.emby_media_actions_organized_roots == ["/organized"]
    assert settings.emby_media_actions_source_roots == ["/source-a", "/source-b"]
