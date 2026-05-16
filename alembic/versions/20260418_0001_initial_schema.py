"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tree_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
    )

    op.create_table(
        "tree_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("raw_name", sa.String(512), nullable=False),
        sa.Column("normalized_name", sa.String(512), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("parent_path", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_type", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("fingerprint_hint", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("import_id", "raw_path", name="uq_tree_nodes_import_raw_path"),
    )

    op.create_table(
        "node_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("folder_node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("raw_name", sa.String(512), nullable=False),
        sa.Column("normalized_name", sa.String(512), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("parent_path", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_ext", sa.String(32), nullable=True),
        sa.Column("fingerprint_hint", sa.String(128), nullable=False),
        sa.Column("remote_file_id", sa.String(64), nullable=True),
        sa.Column("remote_parent_id", sa.String(64), nullable=True),
        sa.Column("remote_pick_code", sa.String(64), nullable=True),
        sa.Column("remote_full_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("import_id", "raw_path", name="uq_node_files_import_raw_path"),
    )

    op.create_table(
        "node_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tag", sa.String(128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source", sa.String(50), nullable=False, server_default="rule"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "keyword_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("canonical_name_normalized", sa.String(255), nullable=False, index=True),
        sa.Column("keyword_type", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active", index=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("canonical_name_normalized", name="uq_keyword_entries_canonical_normalized"),
    )

    op.create_table(
        "keyword_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_normalized", sa.String(255), nullable=False, index=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alias_normalized", name="uq_keyword_aliases_alias_normalized"),
    )

    op.create_table(
        "keyword_hits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_keyword", sa.String(255), nullable=False),
        sa.Column("normalized_keyword", sa.String(255), nullable=False, index=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("canonical_name_snapshot", sa.String(255), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_folder_name", sa.String(512), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("match_rule", sa.String(500), nullable=True),
        sa.Column("match_source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "keyword_library_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("keyword_normalized", sa.String(255), nullable=False, index=True),
        sa.Column("list_type", sa.String(32), nullable=False, index=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("pattern", sa.String(500), nullable=True),
        sa.Column("flags", sa.String(20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("list_type", "keyword_normalized", name="uq_keyword_library_list_keyword"),
    )

    op.create_table(
        "keyword_operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("related_keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "strategy_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("match_mode", sa.String(50), nullable=False, server_default="contains_any"),
        sa.Column("keywords_json", sa.JSON(), nullable=False),
        sa.Column("target_root", sa.String(255), nullable=False),
        sa.Column("target_template", sa.Text(), nullable=False, server_default="{normalized_name}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "organization_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_version", sa.String(100), nullable=False),
        sa.Column("scope_desc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "organization_plan_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("organization_plans.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("suggested_target_path", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(20), nullable=False, server_default="noop"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("conflict_status", sa.String(50), nullable=False, server_default="none"),
        sa.Column("reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("organization_plans.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("confirmation_validated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("rollback_status", sa.String(50), nullable=False, server_default="not_required"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "execution_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("before_path", sa.Text(), nullable=False),
        sa.Column("after_path", sa.Text(), nullable=False),
        sa.Column("api_status", sa.String(50), nullable=False, server_default="skipped"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "execution_rollback_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("log_id", sa.Integer(), sa.ForeignKey("execution_logs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("undo_action", sa.String(50), nullable=False),
        sa.Column("undo_payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="recorded"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "batch_plan_operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_plan_ids", sa.Text(), nullable=True),
        sa.Column("processed_plan_ids", sa.Text(), nullable=True),
        sa.Column("skipped_plan_ids", sa.Text(), nullable=True),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "organize_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column("matched_canonical_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("operation_log", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )



def downgrade() -> None:
    op.drop_table("organize_tasks")
    op.drop_table("batch_plan_operation_logs")
    op.drop_table("execution_rollback_records")
    op.drop_table("execution_logs")
    op.drop_table("execution_jobs")
    op.drop_table("organization_plan_items")
    op.drop_table("organization_plans")
    op.drop_table("strategy_rules")
    op.drop_table("keyword_operation_logs")
    op.drop_table("keyword_library_entries")
    op.drop_table("keyword_hits")
    op.drop_table("keyword_aliases")
    op.drop_table("keyword_entries")
    op.drop_table("node_tags")
    op.drop_table("node_files")
    op.drop_table("tree_nodes")
    op.drop_table("tree_imports")
