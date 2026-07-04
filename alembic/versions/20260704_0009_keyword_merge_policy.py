"""add keyword merge policy

Revision ID: 20260704_0009
Revises: 20260702_0008
Create Date: 2026-07-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0009"
down_revision: Union[str, None] = "20260702_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "keyword_entries",
        sa.Column("merge_policy", sa.String(32), nullable=False, server_default="normal"),
    )
    op.create_index("ix_keyword_entries_merge_policy", "keyword_entries", ["merge_policy"])


def downgrade() -> None:
    op.drop_index("ix_keyword_entries_merge_policy", table_name="keyword_entries")
    op.drop_column("keyword_entries", "merge_policy")
