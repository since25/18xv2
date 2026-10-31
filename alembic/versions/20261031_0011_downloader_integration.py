"""add RN downloader integration tables"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0011"
down_revision = "20260706_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "downloader_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_key", sa.String(64), nullable=False, server_default="rn"),
        sa.Column("remote_package_id", sa.Integer(), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel_title", sa.Text(), nullable=True),
        sa.Column("source_chat_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.String(64), nullable=True),
        sa.Column("boundary_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("known_total_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_download_status", sa.String(32), nullable=False, server_default="never"),
        sa.Column("has_successful_attempt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("index_revision", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_key", "remote_package_id", name="uq_downloader_packages_node_remote"),
    )
    op.create_index("ix_downloader_packages_library_id", "downloader_packages", ["library_id"])
    op.create_index("ix_downloader_packages_boundary_status", "downloader_packages", ["boundary_status"])
    op.create_index("ix_downloader_packages_current_download_status", "downloader_packages", ["current_download_status"])
    op.create_index("ix_downloader_packages_status", "downloader_packages", ["boundary_status", "current_download_status"])

    op.create_table(
        "downloader_package_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("downloader_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matched_term", sa.String(255), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("dismissed_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("package_id", "keyword_entry_id", name="uq_downloader_candidate_package_keyword"),
    )
    op.create_index("ix_downloader_package_candidates_package_id", "downloader_package_candidates", ["package_id"])
    op.create_index("ix_downloader_package_candidates_keyword_entry_id", "downloader_package_candidates", ["keyword_entry_id"])
    op.create_index("ix_downloader_candidates_status", "downloader_package_candidates", ["status"])

    op.create_table(
        "downloader_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("downloader_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("downloader_package_candidates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("remote_batch_id", sa.Integer(), nullable=True),
        sa.Column("remote_task_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="submitted"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_downloader_submission_idempotency"),
    )
    op.create_index("ix_downloader_submissions_package_id", "downloader_submissions", ["package_id"])
    op.create_index("ix_downloader_submissions_candidate_id", "downloader_submissions", ["candidate_id"])
    op.create_index("ix_downloader_submissions_remote_task_id", "downloader_submissions", ["remote_task_id"])
    op.create_index("ix_downloader_submissions_status", "downloader_submissions", ["status"])
    op.create_index("ix_downloader_submissions_task", "downloader_submissions", ["remote_task_id"])

    op.create_table(
        "downloader_task_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_key", sa.String(64), nullable=False, server_default="rn"),
        sa.Column("remote_task_id", sa.String(128), nullable=False),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("node_key", "remote_task_id", name="uq_downloader_task_node_remote"),
    )
    op.create_index("ix_downloader_task_snapshots_status", "downloader_task_snapshots", ["status"])

    op.create_table(
        "downloader_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("packages_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_downloader_sync_runs_kind", "downloader_sync_runs", ["kind"])
    op.create_index("ix_downloader_sync_runs_status", "downloader_sync_runs", ["status"])


def downgrade() -> None:
    op.drop_table("downloader_sync_runs")
    op.drop_table("downloader_task_snapshots")
    op.drop_table("downloader_submissions")
    op.drop_table("downloader_package_candidates")
    op.drop_table("downloader_packages")
