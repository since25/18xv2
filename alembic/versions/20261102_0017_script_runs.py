"""新增 Unraid 脚本日报运行记录和名单表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261102_0017"
down_revision = "20261101_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "script_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_key", sa.String(512), nullable=False),
        sa.Column("script_name", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("items_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_key", name="uq_script_runs_run_key"),
    )
    op.create_index("ix_script_runs_script_name", "script_runs", ["script_name"])
    op.create_index("ix_script_runs_started_at", "script_runs", ["started_at"])
    op.create_index("ix_script_runs_status", "script_runs", ["status"])

    op.create_table(
        "script_run_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("script_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("keyword", sa.String(512), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
    )
    op.create_index("ix_script_run_items_run_id", "script_run_items", ["run_id"])
    op.create_index("ix_script_run_items_run_id_kind", "script_run_items", ["run_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_script_run_items_run_id_kind", table_name="script_run_items")
    op.drop_index("ix_script_run_items_run_id", table_name="script_run_items")
    op.drop_table("script_run_items")
    op.drop_index("ix_script_runs_status", table_name="script_runs")
    op.drop_index("ix_script_runs_started_at", table_name="script_runs")
    op.drop_index("ix_script_runs_script_name", table_name="script_runs")
    op.drop_table("script_runs")
