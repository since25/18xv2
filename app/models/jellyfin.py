from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JellyfinMediaItem(Base):
    """Jellyfin 媒体扫描得到的文件条目。"""

    __tablename__ = "jellyfin_media_items"
    __table_args__ = (UniqueConstraint("source", "path", name="uq_jellyfin_media_items_source_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    mtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    jellyfin_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    resolve_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending", index=True
    )
    match_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unmatched", server_default="unmatched", index=True
    )
    match_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    keyword_links: Mapped[list["JellyfinMediaKeyword"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )


class JellyfinMediaKeyword(Base):
    """媒体条目与关键词的本次匹配结果。"""

    __tablename__ = "jellyfin_media_keywords"
    __table_args__ = (UniqueConstraint("media_item_id", "keyword_entry_id", name="uq_jellyfin_media_keywords_item_keyword"),)

    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("jellyfin_media_items.id", ondelete="CASCADE"), primary_key=True
    )
    keyword_entry_id: Mapped[int] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="CASCADE"), primary_key=True
    )
    match_source: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_term: Mapped[str] = mapped_column(String(512), nullable=False)

    media_item: Mapped[JellyfinMediaItem] = relationship(back_populates="keyword_links")
    keyword_entry = relationship("KeywordEntry")


class JellyfinKeywordCollection(Base):
    """关键词与 Jellyfin 合集的同步映射。"""

    __tablename__ = "jellyfin_keyword_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    jellyfin_collection_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    canonical_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active", index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    keyword_entry = relationship("KeywordEntry")
