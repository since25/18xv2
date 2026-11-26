"""女优档案：档案、别名、标记记录、片子演员、待删清单、保留名单、删除批次和白名单合集。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261126_0019"
down_revision = "20261125_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("canonical_name_normalized", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("film_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_actresses_canonical_name_normalized", "actresses", ["canonical_name_normalized"], unique=True
    )
    op.create_index("ix_actresses_status", "actresses", ["status"])

    op.create_table(
        "actress_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actress_id", sa.Integer(), sa.ForeignKey("actresses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_normalized", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("alias_normalized", name="uq_actress_aliases_alias_normalized"),
    )
    op.create_index("ix_actress_aliases_actress_id", "actress_aliases", ["actress_id"])

    op.create_table(
        "actress_marks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actress_id", sa.Integer(), sa.ForeignKey("actresses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=False),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("jellyfin_media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_actress_marks_actress_id", "actress_marks", ["actress_id"])

    op.create_table(
        "jellyfin_media_actors",
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("jellyfin_media_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("raw_name", sa.String(255), nullable=False),
        sa.Column("name_normalized", sa.String(255), nullable=False),
    )
    op.create_index("ix_jellyfin_media_actors_name_normalized", "jellyfin_media_actors", ["name_normalized"])

    op.create_table(
        "actress_delete_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("film_dir", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("added_by", sa.String(16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("remote_state", sa.String(16), nullable=False, server_default="unchecked"),
        sa.Column("remote_note", sa.Text(), nullable=True),
        sa.Column("remote_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("film_dir", name="uq_actress_delete_candidates_film_dir"),
    )

    op.create_table(
        "actress_kept_films",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("film_dir", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("film_dir", name="uq_actress_kept_films_film_dir"),
    )

    op.create_table(
        "actress_delete_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_films", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_films", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_films", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jellyfin_refresh", sa.String(16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_actress_delete_batches_job_id", "actress_delete_batches", ["job_id"])

    op.create_table(
        "actress_delete_batch_films",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("actress_delete_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("film_dir", sa.Text(), nullable=False),
        sa.Column("number", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_actress_delete_batch_films_batch_id", "actress_delete_batch_films", ["batch_id"])

    op.create_table(
        "actress_delete_batch_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_film_id",
            sa.Integer(),
            sa.ForeignKey("actress_delete_batch_films.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group", sa.String(16), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("remote_file_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_actress_delete_batch_files_batch_film_id", "actress_delete_batch_files", ["batch_film_id"])

    op.create_table(
        "jellyfin_actress_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actress_id", sa.Integer(), sa.ForeignKey("actresses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("jellyfin_collection_id", sa.String(128), nullable=True),
        sa.Column("canonical_name_snapshot", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_jellyfin_actress_collections_actress_id", "jellyfin_actress_collections", ["actress_id"])
    op.create_index(
        "ix_jellyfin_actress_collections_jellyfin_collection_id",
        "jellyfin_actress_collections",
        ["jellyfin_collection_id"],
    )
    op.create_index("ix_jellyfin_actress_collections_status", "jellyfin_actress_collections", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jellyfin_actress_collections_status", table_name="jellyfin_actress_collections")
    op.drop_index("ix_jellyfin_actress_collections_jellyfin_collection_id", table_name="jellyfin_actress_collections")
    op.drop_index("ix_jellyfin_actress_collections_actress_id", table_name="jellyfin_actress_collections")
    op.drop_table("jellyfin_actress_collections")
    op.drop_index("ix_actress_delete_batch_files_batch_film_id", table_name="actress_delete_batch_files")
    op.drop_table("actress_delete_batch_files")
    op.drop_index("ix_actress_delete_batch_films_batch_id", table_name="actress_delete_batch_films")
    op.drop_table("actress_delete_batch_films")
    op.drop_index("ix_actress_delete_batches_job_id", table_name="actress_delete_batches")
    op.drop_table("actress_delete_batches")
    op.drop_table("actress_kept_films")
    op.drop_table("actress_delete_candidates")
    op.drop_index("ix_jellyfin_media_actors_name_normalized", table_name="jellyfin_media_actors")
    op.drop_table("jellyfin_media_actors")
    op.drop_index("ix_actress_marks_actress_id", table_name="actress_marks")
    op.drop_table("actress_marks")
    op.drop_index("ix_actress_aliases_actress_id", table_name="actress_aliases")
    op.drop_table("actress_aliases")
    op.drop_index("ix_actresses_status", table_name="actresses")
    op.drop_index("ix_actresses_canonical_name_normalized", table_name="actresses")
    op.drop_table("actresses")
