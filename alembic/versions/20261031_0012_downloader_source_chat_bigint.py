"""widen RN downloader source chat IDs to bigint"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0012"
down_revision = "20261031_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "downloader_packages",
        "source_chat_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "downloader_packages",
        "source_chat_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
