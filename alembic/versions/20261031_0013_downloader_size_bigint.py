"""widen RN downloader package sizes to bigint"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0013"
down_revision = "20261031_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "downloader_packages",
        "known_total_size",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )


def downgrade() -> None:
    op.alter_column(
        "downloader_packages",
        "known_total_size",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
