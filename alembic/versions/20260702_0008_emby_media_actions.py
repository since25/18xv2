"""add emby media action tables

Revision ID: 20260702_0008
Revises: 0007
Create Date: 2026-07-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emby_media_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("emby_item_id", sa.String(128), nullable=False),
        sa.Column("emby_item_type", sa.String(32), nullable=False),
        sa.Column("emby_title", sa.String(512), nullable=False),
        sa.Column("emby_series_id", sa.String(128), nullable=True),
        sa.Column("emby_season_id", sa.String(128), nullable=True),
        sa.Column("emby_episode_id", sa.String(128), nullable=True),
        sa.Column("alist_url", sa.Text(), nullable=False),
        sa.Column("alist_mount_name", sa.String(128), nullable=True),
        sa.Column("remote_provider", sa.String(32), nullable=False, server_default="115"),
        sa.Column("remote_path", sa.Text(), nullable=True),
        sa.Column("remote_file_id", sa.String(128), nullable=True),
        sa.Column("remote_pick_code", sa.String(128), nullable=True),
        sa.Column("remote_sha1", sa.String(64), nullable=True),
        sa.Column("remote_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("emby_item_id", "alist_url", name="uq_emby_media_mappings_item_url"),
    )
    op.create_index("ix_emby_media_mappings_emby_item_id", "emby_media_mappings", ["emby_item_id"])
    op.create_index("ix_emby_media_mappings_emby_item_type", "emby_media_mappings", ["emby_item_type"])
    op.create_index("ix_emby_media_mappings_emby_series_id", "emby_media_mappings", ["emby_series_id"])
    op.create_index("ix_emby_media_mappings_emby_season_id", "emby_media_mappings", ["emby_season_id"])
    op.create_index("ix_emby_media_mappings_emby_episode_id", "emby_media_mappings", ["emby_episode_id"])
    op.create_index("ix_emby_media_mappings_remote_provider", "emby_media_mappings", ["remote_provider"])
    op.create_index("ix_emby_media_mappings_remote_file_id", "emby_media_mappings", ["remote_file_id"])
    op.create_index(
        "ix_emby_media_mappings_remote_path",
        "emby_media_mappings",
        ["remote_provider", "remote_file_id"],
    )

    op.create_table(
        "emby_media_mapping_paths",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("emby_media_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path_role", sa.String(32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("root_name", sa.String(128), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("inode", sa.Integer(), nullable=True),
        sa.Column("link_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("mapping_id", "path", name="uq_emby_media_mapping_paths_mapping_path"),
    )
    op.create_index("ix_emby_media_mapping_paths_mapping_id", "emby_media_mapping_paths", ["mapping_id"])
    op.create_index("ix_emby_media_mapping_paths_path_role", "emby_media_mapping_paths", ["path_role"])
    op.create_index("ix_emby_media_mapping_paths_root_name", "emby_media_mapping_paths", ["root_name"])

    op.create_table(
        "emby_delete_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="iina_lua"),
        sa.Column("emby_item_id", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_emby_delete_plans_emby_item_id", "emby_delete_plans", ["emby_item_id"])
    op.create_index("ix_emby_delete_plans_scope", "emby_delete_plans", ["scope"])
    op.create_index("ix_emby_delete_plans_status", "emby_delete_plans", ["status"])

    op.create_table(
        "emby_delete_plan_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("emby_delete_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("remote_file_id", sa.String(128), nullable=True),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dry_run_result", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_emby_delete_plan_items_plan_id", "emby_delete_plan_items", ["plan_id"])
    op.create_index("ix_emby_delete_plan_items_group", "emby_delete_plan_items", ["group"])
    op.create_index("ix_emby_delete_plan_items_status", "emby_delete_plan_items", ["status"])

    op.create_table(
        "emby_metadata_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("emby_item_id", sa.String(128), nullable=False),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("emby_media_mappings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("snapshot_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("nfo_path", sa.Text(), nullable=True),
        sa.Column("nfo_xml", sa.Text(), nullable=True),
        sa.Column("emby_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("actors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_emby_metadata_snapshots_emby_item_id", "emby_metadata_snapshots", ["emby_item_id"])
    op.create_index("ix_emby_metadata_snapshots_mapping_id", "emby_metadata_snapshots", ["mapping_id"])

    op.create_table(
        "emby_metadata_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_list", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("emby_item_id", sa.String(128), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("emby_metadata_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("selected_actors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("applied_keyword_entry_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_emby_metadata_candidates_target_list", "emby_metadata_candidates", ["target_list"])
    op.create_index("ix_emby_metadata_candidates_status", "emby_metadata_candidates", ["status"])
    op.create_index("ix_emby_metadata_candidates_emby_item_id", "emby_metadata_candidates", ["emby_item_id"])
    op.create_index("ix_emby_metadata_candidates_snapshot_id", "emby_metadata_candidates", ["snapshot_id"])


def downgrade() -> None:
    op.drop_table("emby_metadata_candidates")
    op.drop_table("emby_metadata_snapshots")
    op.drop_table("emby_delete_plan_items")
    op.drop_table("emby_delete_plans")
    op.drop_table("emby_media_mapping_paths")
    op.drop_table("emby_media_mappings")
