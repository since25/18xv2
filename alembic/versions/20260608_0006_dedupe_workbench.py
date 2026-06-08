"""add dedupe workbench tables

Revision ID: 20260608_0006
Revises: 0005
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.create_table(
        "dedupe_scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tree_import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("scope_path_prefix", sa.Text(), nullable=True),
        sa.Column("included_extensions", sa.Text(), nullable=False, server_default=".mp4,.mkv,.avi,.mov"),
        sa.Column("candidate_threshold", sa.Float(), nullable=False, server_default="0.82"),
        sa.Column("high_confidence_threshold", sa.Float(), nullable=False, server_default="0.92"),
        sa.Column("rules_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_groups", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dedupe_scan_runs_tree_import_id", "dedupe_scan_runs", ["tree_import_id"])
    op.create_index("ix_dedupe_scan_runs_status", "dedupe_scan_runs", ["status"])

    op.create_table(
        "dedupe_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_run_id",
            sa.Integer(),
            sa.ForeignKey("dedupe_scan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tree_import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.String(128), nullable=False),
        sa.Column("representative_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("score_max", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence_level", sa.String(32), nullable=False, server_default="filename_suspected"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column(
            "suggested_keep_candidate_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scan_run_id", "group_key", name="uq_dedupe_groups_run_key"),
    )
    op.create_index("ix_dedupe_groups_scan_run_id", "dedupe_groups", ["scan_run_id"])
    op.create_index("ix_dedupe_groups_tree_import_id", "dedupe_groups", ["tree_import_id"])
    op.create_index("ix_dedupe_groups_confidence_level", "dedupe_groups", ["confidence_level"])
    op.create_index("ix_dedupe_groups_status", "dedupe_groups", ["status"])
    op.create_index("ix_dedupe_groups_suggested_keep_candidate_id", "dedupe_groups", ["suggested_keep_candidate_id"])
    op.create_index("ix_dedupe_groups_status_confidence", "dedupe_groups", ["status", "confidence_level"])

    op.create_table(
        "dedupe_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("dedupe_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_file_id", sa.Integer(), sa.ForeignKey("node_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("file_ext", sa.String(32), nullable=True),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("suggested_action", sa.String(32), nullable=False, server_default="undecided"),
        sa.Column("suggested_reason", sa.Text(), nullable=True),
        sa.Column("user_action", sa.String(32), nullable=False, server_default="undecided"),
        sa.Column("user_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "node_file_id", name="uq_dedupe_candidates_group_node_file"),
    )
    op.create_index("ix_dedupe_candidates_group_id", "dedupe_candidates", ["group_id"])
    op.create_index("ix_dedupe_candidates_node_file_id", "dedupe_candidates", ["node_file_id"])
    op.create_index("ix_dedupe_candidates_user_action", "dedupe_candidates", ["user_action"])

    if _dialect_name() != "sqlite":
        op.create_foreign_key(
            "fk_dedupe_groups_suggested_keep_candidate_id",
            "dedupe_groups",
            "dedupe_candidates",
            ["suggested_keep_candidate_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "dedupe_remote_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("dedupe_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("remote_file_id", sa.String(64), nullable=True),
        sa.Column("remote_parent_id", sa.String(64), nullable=True),
        sa.Column("remote_path", sa.Text(), nullable=True),
        sa.Column("remote_name", sa.Text(), nullable=True),
        sa.Column("sha1", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("file_status", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_dedupe_remote_confirmations_candidate_id",
        "dedupe_remote_confirmations",
        ["candidate_id"],
    )
    op.create_index("ix_dedupe_remote_confirmations_status", "dedupe_remote_confirmations", ["status"])

    op.create_table(
        "dedupe_delete_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source_scan_run_id",
            sa.Integer(),
            sa.ForeignKey("dedupe_scan_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tree_import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("confirm_token", sa.String(128), nullable=True),
        sa.Column("rate_limit_seconds", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dedupe_delete_plans_tree_import_id", "dedupe_delete_plans", ["tree_import_id"])
    op.create_index("ix_dedupe_delete_plans_status", "dedupe_delete_plans", ["status"])

    op.create_table(
        "dedupe_delete_plan_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("dedupe_delete_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("dedupe_candidates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("node_file_id", sa.Integer(), sa.ForeignKey("node_files.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("remote_file_id", sa.String(64), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("remote_path", sa.Text(), nullable=True),
        sa.Column("confirmation_level", sa.String(32), nullable=False),
        sa.Column("delete_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("plan_id", "candidate_id", name="uq_dedupe_delete_plan_items_plan_candidate"),
    )
    op.create_index("ix_dedupe_delete_plan_items_plan_id", "dedupe_delete_plan_items", ["plan_id"])
    op.create_index("ix_dedupe_delete_plan_items_candidate_id", "dedupe_delete_plan_items", ["candidate_id"])
    op.create_index("ix_dedupe_delete_plan_items_node_file_id", "dedupe_delete_plan_items", ["node_file_id"])
    op.create_index("ix_dedupe_plan_items_status", "dedupe_delete_plan_items", ["status"])


def downgrade() -> None:
    if _dialect_name() != "sqlite":
        op.drop_constraint(
            "fk_dedupe_groups_suggested_keep_candidate_id",
            "dedupe_groups",
            type_="foreignkey",
        )

    op.drop_index("ix_dedupe_plan_items_status", table_name="dedupe_delete_plan_items")
    op.drop_index("ix_dedupe_delete_plan_items_node_file_id", table_name="dedupe_delete_plan_items")
    op.drop_index("ix_dedupe_delete_plan_items_candidate_id", table_name="dedupe_delete_plan_items")
    op.drop_index("ix_dedupe_delete_plan_items_plan_id", table_name="dedupe_delete_plan_items")
    op.drop_index("ix_dedupe_delete_plans_status", table_name="dedupe_delete_plans")
    op.drop_index("ix_dedupe_delete_plans_tree_import_id", table_name="dedupe_delete_plans")
    op.drop_index("ix_dedupe_remote_confirmations_status", table_name="dedupe_remote_confirmations")
    op.drop_index("ix_dedupe_remote_confirmations_candidate_id", table_name="dedupe_remote_confirmations")
    op.drop_index("ix_dedupe_candidates_user_action", table_name="dedupe_candidates")
    op.drop_index("ix_dedupe_candidates_node_file_id", table_name="dedupe_candidates")
    op.drop_index("ix_dedupe_candidates_group_id", table_name="dedupe_candidates")
    op.drop_index("ix_dedupe_groups_status_confidence", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_groups_suggested_keep_candidate_id", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_groups_status", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_groups_confidence_level", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_groups_tree_import_id", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_groups_scan_run_id", table_name="dedupe_groups")
    op.drop_index("ix_dedupe_scan_runs_status", table_name="dedupe_scan_runs")
    op.drop_index("ix_dedupe_scan_runs_tree_import_id", table_name="dedupe_scan_runs")
    op.drop_table("dedupe_delete_plan_items")
    op.drop_table("dedupe_delete_plans")
    op.drop_table("dedupe_remote_confirmations")
    op.drop_table("dedupe_candidates")
    op.drop_table("dedupe_groups")
    op.drop_table("dedupe_scan_runs")
