from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizeTask(Base):
    __tablename__ = "organize_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("tree_imports.id", ondelete="SET NULL"), nullable=True, index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    keyword_entry_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    matched_canonical_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MagnetDownloadTask(Base):
    __tablename__ = "magnet_download_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    keyword_entry_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    source_tid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_title: Mapped[str] = mapped_column(Text, nullable=False)
    source_magnet: Mapped[str] = mapped_column(Text, nullable=False)
    source_detail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    match_score: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unchecked", index=True)
    duplicate_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    target_cid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id_115: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_to_115_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
