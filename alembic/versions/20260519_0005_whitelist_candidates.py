"""add whitelist_candidates

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whitelist_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_tid", sa.Integer(), nullable=False, index=True),
        sa.Column("source_magnet", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_section", sa.String(255), nullable=True),
        sa.Column("source_detail_url", sa.Text(), nullable=True),
        sa.Column(
            "matched_keyword_entry_id", sa.Integer(),
            sa.ForeignKey("keyword_entries.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("matched_keyword", sa.String(255), nullable=False),
        sa.Column("matched_alias", sa.String(255), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "last_scanned_tree_import_id", sa.Integer(),
            sa.ForeignKey("tree_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("duplicate_status", sa.String(32), nullable=False),
        sa.Column("duplicate_reason", sa.Text(), nullable=True),
        sa.Column("matched_import_label", sa.String(255), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column(
            "lifecycle_status", sa.String(32),
            nullable=False, server_default="pending", index=True,
        ),
        sa.Column(
            "magnet_task_id", sa.Integer(),
            sa.ForeignKey("magnet_download_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source_tid", "source_magnet", "matched_keyword_entry_id",
            name="uq_whitelist_candidate_source_keyword",
        ),
    )
    op.create_index(
        "ix_whitelist_candidate_lifecycle_keyword",
        "whitelist_candidates",
        ["lifecycle_status", "matched_keyword_entry_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whitelist_candidate_lifecycle_keyword",
        table_name="whitelist_candidates",
    )
    op.drop_table("whitelist_candidates")
