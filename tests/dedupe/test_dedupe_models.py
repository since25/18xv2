from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy import inspect

from app.db.base import Base

DEDUPE_TABLES = {
    "dedupe_scan_runs",
    "dedupe_groups",
    "dedupe_candidates",
    "dedupe_remote_confirmations",
    "dedupe_delete_plans",
    "dedupe_delete_plan_items",
}


def _table(name: str):
    return Base.metadata.tables[name]


def _column(table_name: str, column_name: str):
    return _table(table_name).c[column_name]


def _default_text(table_name: str, column_name: str) -> str | None:
    column = _column(table_name, column_name)
    if column.server_default is not None:
        arg = column.server_default.arg
        return getattr(arg, "text", str(arg))
    if column.default is not None:
        return str(column.default.arg)
    return None


def _single_column_index_names(table_name: str, column_name: str) -> set[str]:
    table = _table(table_name)
    return {
        index.name
        for index in table.indexes
        if [column.name for column in index.columns] == [column_name]
    }


def _has_index(table_name: str, index_name: str, column_names: list[str]) -> bool:
    table = _table(table_name)
    return any(
        index.name == index_name and [column.name for column in index.columns] == column_names
        for index in table.indexes
    )


def _fk_ondelete(table_name: str, column_name: str) -> str | None:
    foreign_keys = list(_column(table_name, column_name).foreign_keys)
    assert len(foreign_keys) == 1
    return foreign_keys[0].ondelete


def test_dedupe_tables_are_registered(db_session):
    table_names = set(inspect(db_session.bind).get_table_names())
    assert DEDUPE_TABLES.issubset(table_names)

    assert DEDUPE_TABLES.issubset(Base.metadata.tables)


def test_dedupe_scan_run_schema_contract():
    assert "ix_dedupe_scan_runs_tree_import_id" in _single_column_index_names(
        "dedupe_scan_runs", "tree_import_id"
    )
    assert "ix_dedupe_scan_runs_status" in _single_column_index_names("dedupe_scan_runs", "status")

    assert isinstance(_column("dedupe_scan_runs", "included_extensions").type, Text)
    assert _default_text("dedupe_scan_runs", "included_extensions") == ".mp4,.mkv,.avi,.mov"
    assert _default_text("dedupe_scan_runs", "candidate_threshold") == "0.82"
    assert _default_text("dedupe_scan_runs", "high_confidence_threshold") == "0.92"
    assert isinstance(_column("dedupe_scan_runs", "rules_snapshot_json").type, Text)
    assert _default_text("dedupe_scan_runs", "rules_snapshot_json") == "{}"
    assert isinstance(_column("dedupe_scan_runs", "summary_json").type, Text)


def test_dedupe_group_schema_contract():
    table = _table("dedupe_groups")
    unique_constraint_names = {
        constraint.name for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_dedupe_groups_run_key" in unique_constraint_names

    assert isinstance(_column("dedupe_groups", "group_key").type, String)
    assert _column("dedupe_groups", "group_key").type.length == 128
    assert isinstance(_column("dedupe_groups", "representative_name").type, Text)
    assert isinstance(_column("dedupe_groups", "normalized_name").type, Text)
    assert _default_text("dedupe_groups", "confidence_level") == "filename_suspected"
    assert _default_text("dedupe_groups", "status") == "pending_review"

    assert "ix_dedupe_groups_scan_run_id" in _single_column_index_names("dedupe_groups", "scan_run_id")
    assert "ix_dedupe_groups_tree_import_id" in _single_column_index_names("dedupe_groups", "tree_import_id")
    assert "ix_dedupe_groups_confidence_level" in _single_column_index_names(
        "dedupe_groups", "confidence_level"
    )
    assert "ix_dedupe_groups_status" in _single_column_index_names("dedupe_groups", "status")
    assert _has_index("dedupe_groups", "ix_dedupe_groups_status_confidence", ["status", "confidence_level"])


def test_dedupe_candidate_schema_contract():
    assert "ix_dedupe_candidates_group_id" in _single_column_index_names("dedupe_candidates", "group_id")
    assert "ix_dedupe_candidates_node_file_id" in _single_column_index_names(
        "dedupe_candidates", "node_file_id"
    )
    assert _fk_ondelete("dedupe_candidates", "node_file_id") == "CASCADE"

    assert isinstance(_column("dedupe_candidates", "raw_name").type, Text)
    assert isinstance(_column("dedupe_candidates", "normalized_name").type, Text)
    assert isinstance(_column("dedupe_candidates", "similarity_score").type, Float)
    assert _default_text("dedupe_candidates", "similarity_score") == "0.0"
    assert _default_text("dedupe_candidates", "suggested_action") == "undecided"
    assert not _column("dedupe_candidates", "user_action").nullable
    assert _default_text("dedupe_candidates", "user_action") == "undecided"
    assert "ix_dedupe_candidates_user_action" in _single_column_index_names(
        "dedupe_candidates", "user_action"
    )


def test_dedupe_remote_confirmation_schema_contract():
    assert "ix_dedupe_remote_confirmations_candidate_id" in _single_column_index_names(
        "dedupe_remote_confirmations", "candidate_id"
    )
    assert "ix_dedupe_remote_confirmations_status" in _single_column_index_names(
        "dedupe_remote_confirmations", "status"
    )

    assert isinstance(_column("dedupe_remote_confirmations", "remote_name").type, Text)
    assert isinstance(_column("dedupe_remote_confirmations", "sha1").type, String)
    assert _column("dedupe_remote_confirmations", "sha1").type.length == 128
    assert isinstance(_column("dedupe_remote_confirmations", "size_bytes").type, Integer)
    assert isinstance(_column("dedupe_remote_confirmations", "file_status").type, String)
    assert _column("dedupe_remote_confirmations", "file_status").type.length == 64
    assert _column("dedupe_remote_confirmations", "confirmed_at").server_default is not None


def test_dedupe_delete_plan_schema_contract():
    assert "ix_dedupe_delete_plans_tree_import_id" in _single_column_index_names(
        "dedupe_delete_plans", "tree_import_id"
    )
    assert "ix_dedupe_delete_plans_status" in _single_column_index_names(
        "dedupe_delete_plans", "status"
    )
    assert _default_text("dedupe_delete_plans", "rate_limit_seconds") == "2.0"


def test_dedupe_delete_plan_item_schema_contract():
    assert "ix_dedupe_delete_plan_items_plan_id" in _single_column_index_names(
        "dedupe_delete_plan_items", "plan_id"
    )
    assert "ix_dedupe_delete_plan_items_candidate_id" in _single_column_index_names(
        "dedupe_delete_plan_items", "candidate_id"
    )
    assert "ix_dedupe_delete_plan_items_node_file_id" in _single_column_index_names(
        "dedupe_delete_plan_items", "node_file_id"
    )
    assert "ix_dedupe_plan_items_status" in _single_column_index_names(
        "dedupe_delete_plan_items", "status"
    )
    assert not _column("dedupe_delete_plan_items", "remote_file_id").nullable
