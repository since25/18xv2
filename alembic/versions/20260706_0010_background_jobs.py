"""add persistent background jobs

Revision ID: 20260706_0010
Revises: 20260704_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20260706_0010"
down_revision = "20260704_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=255), nullable=False),
        sa.Column("current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index("ix_background_jobs_done", "background_jobs", ["done"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_done", table_name="background_jobs")
    op.drop_index("ix_background_jobs_job_type", table_name="background_jobs")
    op.drop_table("background_jobs")
