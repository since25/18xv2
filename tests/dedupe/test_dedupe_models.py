from __future__ import annotations

from sqlalchemy import inspect

from app.db.base import Base


def test_dedupe_tables_are_registered(db_session):
    table_names = set(inspect(db_session.bind).get_table_names())
    assert {
        "dedupe_scan_runs",
        "dedupe_groups",
        "dedupe_candidates",
        "dedupe_remote_confirmations",
        "dedupe_delete_plans",
        "dedupe_delete_plan_items",
    }.issubset(table_names)

    assert "dedupe_scan_runs" in Base.metadata.tables
    assert "dedupe_delete_plan_items" in Base.metadata.tables
