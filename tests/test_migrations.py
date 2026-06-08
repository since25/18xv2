from __future__ import annotations

import importlib.util
from pathlib import Path


class MigrationOrderRecorder:
    def __init__(self, existing_tables: set[str]) -> None:
        self.created_tables = set(existing_tables)

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
