from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MigrationOrderRecorder:
    def __init__(self, existing_tables: set[str]) -> None:
        self.created_tables = set(existing_tables)
        self.added_columns: list[tuple[str, object]] = []
        self.created_indexes: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def create_table(self, table_name: str, *elements, **kwargs) -> None:
        missing_targets = []
        for element in elements:
            for foreign_key in getattr(element, "foreign_keys", []):
                target_table = foreign_key.target_fullname.split(".", 1)[0]
                if target_table not in self.created_tables:
                    missing_targets.append(target_table)

        assert not missing_targets, (
            f"{table_name} references tables before they are created: "
            f"{', '.join(sorted(set(missing_targets)))}"
        )
        self.created_tables.add(table_name)

    def create_index(self, *args, **kwargs) -> None:
        self.created_indexes.append((args, kwargs))
        return None

    def add_column(self, table_name: str, column) -> None:
        self.added_columns.append((table_name, column))

    def drop_index(self, *args, **kwargs) -> None:
        return None

    def drop_column(self, *args, **kwargs) -> None:
        return None

    def create_foreign_key(
        self,
        constraint_name: str,
        source_table: str,
        referent_table: str,
        local_cols: list[str],
        remote_cols: list[str],
        **kwargs,
    ) -> None:
        assert source_table in self.created_tables
        assert referent_table in self.created_tables

    def get_bind(self):
        class Bind:
            class dialect:
                name = "postgresql"

        return Bind()


def test_dedupe_migration_creates_referenced_tables_before_foreign_keys(monkeypatch):
    migration_path = Path("alembic/versions/20260608_0006_dedupe_workbench.py")
    spec = importlib.util.spec_from_file_location("dedupe_workbench_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    recorder = MigrationOrderRecorder(existing_tables={"tree_imports", "node_files"})

    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()


def test_keyword_entries_has_merge_policy_column():
    migration_path = Path("alembic/versions/20260704_0009_keyword_merge_policy.py")
    spec = importlib.util.spec_from_file_location("keyword_merge_policy_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE keyword_entries (
                    id INTEGER PRIMARY KEY,
                    canonical_name VARCHAR(255) NOT NULL
                )
                """
            )
        )

        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("keyword_entries")
        }

    assert "merge_policy" in columns
    assert columns["merge_policy"]["nullable"] is False


def test_script_runs_migration_upgrades_and_downgrades():
    migration_path = Path("alembic/versions/20261102_0017_script_runs.py")
    spec = importlib.util.spec_from_file_location("script_runs_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert {"script_runs", "script_run_items"}.issubset(set(sa.inspect(connection).get_table_names()))
        migration.downgrade()
        assert "script_runs" not in sa.inspect(connection).get_table_names()
        assert "script_run_items" not in sa.inspect(connection).get_table_names()


def _load_migration(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_jobs_migration_upgrades_and_downgrades():
    base = _load_migration("alembic/versions/20261102_0017_script_runs.py", "script_runs_migration_base")
    migration = _load_migration("alembic/versions/20261125_0018_script_jobs.py", "script_jobs_migration")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        ops = Operations(MigrationContext.configure(connection))
        base.op = ops
        migration.op = ops
        base.upgrade()
        migration.upgrade()

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert {"script_job_configs", "script_job_config_changes", "sehuatang_posts"}.issubset(tables)
        run_columns = {column["name"]: column for column in inspector.get_columns("script_runs")}
        assert {"trigger", "dry_run", "log_path", "error_reason", "pid"}.issubset(run_columns)
        assert run_columns["finished_at"]["nullable"] is True
        assert run_columns["exit_code"]["nullable"] is True

        rows = connection.execute(
            sa.text("select job_name, executor, enabled, run_time, params from script_job_configs")
        ).all()
        by_name = {row.job_name: row for row in rows}
        assert set(by_name) == {"sehuatang", "MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING"}
        assert {row.executor for row in rows} == {"unraid"}
        assert not any(row.enabled for row in rows)
        assert by_name["sehuatang"].run_time == "01:28"
        assert by_name["MOVE_SSD_CACHE_TO_DISK2"].run_time == "01:01"
        assert by_name["DEL_SOMETHING"].run_time == "12:09"
        sehuatang_params = by_name["sehuatang"].params
        if isinstance(sehuatang_params, str):
            sehuatang_params = json.loads(sehuatang_params)
        assert sehuatang_params == {
            "pages": 4,
            "forum_url": "https://sehuatang.org/forum.php?mod=forumdisplay&fid=2&typeid=684&filter=typeid&page={page}",
            "qb_category": "国产BT",
        }

        # 18x 自己产生的记录（含未结束的）回滚时要删掉，旧版本只认识 Unraid 回报
        connection.execute(
            sa.text(
                "insert into script_runs (id, run_key, script_name, started_at, finished_at, exit_code, status,"
                " counts, items_truncated, received_at, trigger, dry_run)"
                " values (1, 'report-1', 'DEL_SOMETHING', '2026-11-25 04:09:00', '2026-11-25 04:10:00', 0, 'success',"
                " '{}', 0, '2026-11-25 04:10:00', 'report', 0),"
                " (2, 'manual-1', 'sehuatang', '2026-11-25 05:00:00', null, null, 'running',"
                " '{}', 0, '2026-11-25 05:00:00', 'manual', 0)"
            )
        )
        connection.execute(
            sa.text("insert into script_run_items (run_id, kind, path) values (1, 'deleted_file', 'a'), (2, 'submitted', 'b')")
        )

        migration.downgrade()
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert not {"script_job_configs", "script_job_config_changes", "sehuatang_posts"} & tables
        assert connection.execute(sa.text("select run_key from script_runs")).scalars().all() == ["report-1"]
        assert connection.execute(sa.text("select run_id from script_run_items")).scalars().all() == [1]
        assert {"script_runs", "script_run_items"}.issubset(tables)
        run_columns = {column["name"] for column in inspector.get_columns("script_runs")}
        assert not {"trigger", "dry_run", "log_path", "error_reason", "pid"} & run_columns
