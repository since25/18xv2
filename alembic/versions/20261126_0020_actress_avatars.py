"""女优头像：档案上记录从 Gfriends 找图、上传 Jellyfin 人物主图的状态。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261126_0020"
down_revision = "20261126_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("actresses") as batch:
        batch.add_column(sa.Column("avatar_state", sa.String(16), nullable=False, server_default="pending"))
        batch.add_column(sa.Column("avatar_source", sa.Text(), nullable=True))
        batch.add_column(sa.Column("avatar_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("avatar_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_actresses_avatar_state", "actresses", ["avatar_state"])


def downgrade() -> None:
    op.drop_index("ix_actresses_avatar_state", table_name="actresses")
    with op.batch_alter_table("actresses") as batch:
        batch.drop_column("avatar_checked_at")
        batch.drop_column("avatar_note")
        batch.drop_column("avatar_source")
        batch.drop_column("avatar_state")
