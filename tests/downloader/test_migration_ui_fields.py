from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import get_settings


MIGRATION_PATH = Path("alembic/versions/20261101_0015_downloader_ui_fields.py")


def _load_migration():
    spec = importlib.util.spec_from_file_location("downloader_ui_fields_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_backfill_task_fields_extracts_times_bytes_and_channel():
    migration = _load_migration()

    result = migration.backfill_task_fields(
        '{"created_at":1761890000.0,"updated_at":1761890600.0,'
        '"status":"completed","chat_title":"Foo channel",'
        '"files":[{"total_size_bytes":100,"downloaded_size_bytes":80},'
        '{"total_size_bytes":50,"downloaded_size_bytes":20}]}'
    )

    assert result["remote_created_at"] == datetime.fromtimestamp(1761890000, UTC)
    assert result["remote_updated_at"] == datetime.fromtimestamp(1761890600, UTC)
    assert result["finished_at"] == datetime.fromtimestamp(1761890600, UTC)
    assert result["total_bytes"] == 150
    assert result["downloaded_bytes"] == 100
    assert result["channel_title"] == "Foo channel"


def test_backfill_task_fields_ignores_malformed_payloads_and_formatted_sizes():
    migration = _load_migration()

    for raw in ("{}", "not json", '{"files": {}}', '{"files":[{"total_size_bytes":"12.3 MB"}]}'):
        result = migration.backfill_task_fields(raw)
        assert result["remote_created_at"] is None
        assert result["remote_updated_at"] is None
        assert result["finished_at"] is None
        assert result["total_bytes"] == 0
        assert result["downloaded_bytes"] == 0


def test_ui_fields_migration_upgrades_and_downgrades(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "20261101_0015")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        task_columns = {column["name"] for column in sa.inspect(connection).get_columns("downloader_task_snapshots")}
        package_columns = {column["name"] for column in sa.inspect(connection).get_columns("downloader_packages")}
        index_names = {index["name"] for index in sa.inspect(connection).get_indexes("downloader_task_snapshots")}
    assert {"remote_created_at", "remote_updated_at", "finished_at", "total_bytes", "downloaded_bytes", "channel_title"} <= task_columns
    assert {"ignored_at", "ignored_reason", "completed_media_count"} <= package_columns
    assert "ix_downloader_tasks_node_created" in index_names
    assert "ix_downloader_tasks_node_status" in index_names

    command.downgrade(config, "20261031_0014")
    with engine.connect() as connection:
        task_columns = {column["name"] for column in sa.inspect(connection).get_columns("downloader_task_snapshots")}
    assert "total_bytes" not in task_columns
