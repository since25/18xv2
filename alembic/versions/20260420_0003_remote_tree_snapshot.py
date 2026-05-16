"""远端目录树快照：tree_imports 加 source_type，tree_nodes 加 remote_cid

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tree_imports",
        sa.Column("source_type", sa.String(50), nullable=False, server_default="file_upload"),
    )
    op.add_column(
        "tree_nodes",
        sa.Column("remote_cid", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tree_nodes", "remote_cid")
    op.drop_column("tree_imports", "source_type")
