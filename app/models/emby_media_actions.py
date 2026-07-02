from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EmbyMediaMapping(Base):
    __tablename__ = "emby_media_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    emby_item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    emby_title: Mapped[str] = mapped_column(String(512), nullable=False)
    emby_series_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    emby_season_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    emby_episode_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    alist_url: Mapped[str] = mapped_column(Text, nullable=False)
    alist_mount_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="115", index=True)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    remote_pick_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_sha1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    paths: Mapped[list["EmbyMediaMappingPath"]] = relationship(back_populates="mapping", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("emby_item_id", "alist_url", name="uq_emby_media_mappings_item_url"),
        Index("ix_emby_media_mappings_remote_path", "remote_provider", "remote_file_id"),
    )


class EmbyMediaMappingPath(Base):
    __tablename__ = "emby_media_mapping_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mapping_id: Mapped[int] = mapped_column(ForeignKey("emby_media_mappings.id", ondelete="CASCADE"), nullable=False, index=True)
    path_role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    root_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    mapping: Mapped[EmbyMediaMapping] = relationship(back_populates="paths")

    __table_args__ = (UniqueConstraint("mapping_id", "path", name="uq_emby_media_mapping_paths_mapping_path"),)


class EmbyDeletePlan(Base):
    __tablename__ = "emby_delete_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="iina_lua")
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["EmbyDeletePlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class EmbyDeletePlanItem(Base):
    __tablename__ = "emby_delete_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("emby_delete_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan: Mapped[EmbyDeletePlan] = relationship(back_populates="items")


class EmbyMetadataSnapshot(Base):
    __tablename__ = "emby_metadata_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mapping_id: Mapped[int | None] = mapped_column(ForeignKey("emby_media_mappings.id", ondelete="SET NULL"), nullable=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    nfo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    nfo_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    emby_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmbyMetadataCandidate(Base):
    __tablename__ = "emby_metadata_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_list: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("emby_metadata_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    selected_actors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    applied_keyword_entry_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshot: Mapped[EmbyMetadataSnapshot] = relationship()
