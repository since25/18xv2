"""add downloader revision candidates and task history"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0014"
down_revision = "20261031_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "downloader_packages",
        sa.Column("completed_revision", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("downloader_package_candidates") as batch:
        batch.add_column(
            sa.Column("package_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.drop_constraint(
            "uq_downloader_candidate_package_keyword", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_downloader_candidate_package_keyword_revision",
            ["package_id", "keyword_entry_id", "package_revision"],
        )
    op.execute(
        sa.text(
            """
            UPDATE downloader_package_candidates
            SET package_revision = COALESCE(
                (SELECT index_revision FROM downloader_packages
                 WHERE downloader_packages.id = downloader_package_candidates.package_id),
                0
            )
            """
        )
    )
    with op.batch_alter_table("downloader_submissions") as batch:
        batch.add_column(
            sa.Column("package_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("download_mode", sa.String(32), nullable=False, server_default="full")
        )
    op.execute(
        sa.text(
            """
            UPDATE downloader_submissions
            SET package_revision = COALESCE(
                (SELECT index_revision FROM downloader_packages
                 WHERE downloader_packages.id = downloader_submissions.package_id),
                0
            )
            """
        )
    )
    op.create_table(
        "downloader_task_histories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_key", sa.String(64), nullable=False, server_default="rn"),
        sa.Column("remote_task_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("task_type", sa.String(64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_file_json", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_key", "remote_task_id", "payload_hash", name="uq_downloader_task_history_payload"),
    )
    op.create_index(
        "ix_downloader_task_histories_task_observed",
        "downloader_task_histories",
        ["node_key", "remote_task_id", "observed_at"],
    )
    op.create_table(
        "downloader_task_file_histories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("history_id", sa.Integer(), sa.ForeignKey("downloader_task_histories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("total_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("downloaded_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("download_speed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("save_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("uploaded_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("upload_speed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("raw_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("history_id", "message_id", name="uq_downloader_task_file_history_message"),
    )
    op.create_index(
        "ix_downloader_task_file_histories_status",
        "downloader_task_file_histories",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_downloader_task_file_histories_status", table_name="downloader_task_file_histories")
    op.drop_table("downloader_task_file_histories")
    op.drop_index("ix_downloader_task_histories_task_observed", table_name="downloader_task_histories")
    op.drop_table("downloader_task_histories")
    with op.batch_alter_table("downloader_submissions") as batch:
        batch.drop_column("download_mode")
        batch.drop_column("package_revision")
    with op.batch_alter_table("downloader_package_candidates") as batch:
        batch.drop_constraint("uq_downloader_candidate_package_keyword_revision", type_="unique")
        batch.create_unique_constraint(
            "uq_downloader_candidate_package_keyword", ["package_id", "keyword_entry_id"]
        )
        batch.drop_column("package_revision")
    op.drop_column("downloader_packages", "completed_revision")
