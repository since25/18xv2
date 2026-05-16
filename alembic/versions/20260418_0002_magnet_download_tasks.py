"""add magnet_download_tasks

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "magnet_download_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("source_tid", sa.Integer(), nullable=False, index=True),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_magnet", sa.Text(), nullable=False),
        sa.Column("source_detail_url", sa.Text(), nullable=True),
        sa.Column("source_section", sa.String(255), nullable=True),
        sa.Column("matched_keyword", sa.String(255), nullable=True),
        sa.Column("matched_alias", sa.String(255), nullable=True),
        sa.Column("match_score", sa.String(32), nullable=True),
        sa.Column("duplicate_status", sa.String(32), nullable=False, server_default="unchecked", index=True),
        sa.Column("duplicate_detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("target_cid", sa.String(64), nullable=True),
        sa.Column("task_id_115", sa.String(64), nullable=True),
        sa.Column("submitted_to_115_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("operation_log", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("magnet_download_tasks")
