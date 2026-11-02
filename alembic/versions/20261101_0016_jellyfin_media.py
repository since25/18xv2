"""新增 Jellyfin 媒体扫描与合集映射表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261101_0016"
down_revision = "20261101_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jellyfin_media_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("file_ext", sa.String(32), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mtime", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_job_id", sa.String(128), nullable=True),
        sa.Column("jellyfin_item_id", sa.String(128), nullable=True),
        sa.Column("resolve_state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("match_state", sa.String(32), nullable=False, server_default="unmatched"),
        sa.Column("match_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("source", "path", name="uq_jellyfin_media_items_source_path"),
    )
    op.create_index("ix_jellyfin_media_items_source", "jellyfin_media_items", ["source"])
    op.create_index("ix_jellyfin_media_items_active", "jellyfin_media_items", ["active"])
    op.create_index("ix_jellyfin_media_items_last_seen_job_id", "jellyfin_media_items", ["last_seen_job_id"])
    op.create_index("ix_jellyfin_media_items_jellyfin_item_id", "jellyfin_media_items", ["jellyfin_item_id"])
    op.create_index("ix_jellyfin_media_items_resolve_state", "jellyfin_media_items", ["resolve_state"])
    op.create_index("ix_jellyfin_media_items_match_state", "jellyfin_media_items", ["match_state"])

    op.create_table(
        "jellyfin_media_keywords",
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("jellyfin_media_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "keyword_entry_id",
            sa.Integer(),
            sa.ForeignKey("keyword_entries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("match_source", sa.String(32), nullable=False),
        sa.Column("raw_term", sa.String(512), nullable=False),
        sa.UniqueConstraint("media_item_id", "keyword_entry_id", name="uq_jellyfin_media_keywords_item_keyword"),
    )
    op.create_index("ix_jellyfin_media_keywords_media_item_id", "jellyfin_media_keywords", ["media_item_id"])
    op.create_index("ix_jellyfin_media_keywords_keyword_entry_id", "jellyfin_media_keywords", ["keyword_entry_id"])

    op.create_table(
        "jellyfin_keyword_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword_entry_id", sa.Integer(), sa.ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("jellyfin_collection_id", sa.String(128), nullable=True),
        sa.Column("canonical_name_snapshot", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_jellyfin_keyword_collections_keyword_entry_id", "jellyfin_keyword_collections", ["keyword_entry_id"])
    op.create_index("ix_jellyfin_keyword_collections_jellyfin_collection_id", "jellyfin_keyword_collections", ["jellyfin_collection_id"])
    op.create_index("ix_jellyfin_keyword_collections_status", "jellyfin_keyword_collections", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jellyfin_keyword_collections_status", table_name="jellyfin_keyword_collections")
    op.drop_index("ix_jellyfin_keyword_collections_jellyfin_collection_id", table_name="jellyfin_keyword_collections")
    op.drop_index("ix_jellyfin_keyword_collections_keyword_entry_id", table_name="jellyfin_keyword_collections")
    op.drop_table("jellyfin_keyword_collections")
    op.drop_index("ix_jellyfin_media_keywords_keyword_entry_id", table_name="jellyfin_media_keywords")
    op.drop_index("ix_jellyfin_media_keywords_media_item_id", table_name="jellyfin_media_keywords")
    op.drop_table("jellyfin_media_keywords")
    op.drop_index("ix_jellyfin_media_items_match_state", table_name="jellyfin_media_items")
    op.drop_index("ix_jellyfin_media_items_resolve_state", table_name="jellyfin_media_items")
    op.drop_index("ix_jellyfin_media_items_jellyfin_item_id", table_name="jellyfin_media_items")
    op.drop_index("ix_jellyfin_media_items_last_seen_job_id", table_name="jellyfin_media_items")
    op.drop_index("ix_jellyfin_media_items_active", table_name="jellyfin_media_items")
    op.drop_index("ix_jellyfin_media_items_source", table_name="jellyfin_media_items")
    op.drop_table("jellyfin_media_items")
