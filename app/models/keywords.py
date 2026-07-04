from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class KeywordEntry(TimestampMixin, Base):
    __tablename__ = "keyword_entries"
    __table_args__ = (UniqueConstraint("canonical_name_normalized", name="uq_keyword_entries_canonical_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name_normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    keyword_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    merge_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", server_default="normal", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    aliases: Mapped[list["KeywordAlias"]] = relationship(back_populates="entry", cascade="all, delete-orphan")
    hits: Mapped[list["KeywordHit"]] = relationship(back_populates="entry")


class KeywordAlias(TimestampMixin, Base):
    __tablename__ = "keyword_aliases"
    __table_args__ = (UniqueConstraint("alias_normalized", name="uq_keyword_aliases_alias_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_entry_id: Mapped[int] = mapped_column(ForeignKey("keyword_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    entry: Mapped["KeywordEntry"] = relationship(back_populates="aliases")


class KeywordHit(TimestampMixin, Base):
    __tablename__ = "keyword_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    keyword_entry_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    canonical_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_folder_name: Mapped[str] = mapped_column(String(512), nullable=False)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True)
    match_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")

    entry: Mapped["KeywordEntry | None"] = relationship(back_populates="hits")


class KeywordLibraryEntry(TimestampMixin, Base):
    __tablename__ = "keyword_library_entries"
    __table_args__ = (UniqueConstraint("list_type", "keyword_normalized", name="uq_keyword_library_list_keyword"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    keyword_normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    list_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    import_id: Mapped[int | None] = mapped_column(ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True)
    pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    flags: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class KeywordOperationLog(TimestampMixin, Base):
    __tablename__ = "keyword_operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    keyword_entry_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    related_keyword_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
