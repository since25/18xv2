"""add review intake table

Revision ID: 0007
Revises: 20260608_0006
Create Date: 2026-07-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "20260608_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_intake_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket", sa.String(32), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("path_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="shortcut"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("extracted_keywords_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "approved_keyword_entry_id",
            sa.Integer(),
            sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_keyword", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bucket", "path_hash", name="uq_review_intake_bucket_path_hash"),
    )
    op.create_index("ix_review_intake_items_bucket", "review_intake_items", ["bucket"])
    op.create_index("ix_review_intake_items_status", "review_intake_items", ["status"])
    op.create_index("ix_review_intake_bucket_status", "review_intake_items", ["bucket", "status"])


def downgrade() -> None:
    op.drop_index("ix_review_intake_bucket_status", table_name="review_intake_items")
    op.drop_index("ix_review_intake_items_status", table_name="review_intake_items")
    op.drop_index("ix_review_intake_items_bucket", table_name="review_intake_items")
    op.drop_table("review_intake_items")
