"""widen RN downloader source chat IDs to bigint"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0012"
down_revision = "20261031_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("downloader_packages") as batch:
        batch.alter_column(
            "source_chat_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("downloader_packages") as batch:
        batch.alter_column(
            "source_chat_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
