"""持久化的白名单扫描候选账本。

跨次扫描去重 + 生命周期跟踪。详见
docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §3
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhitelistCandidate(Base):
    __tablename__ = "whitelist_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 去重键（业务唯一）；source_tid 用 Integer 与 MagnetDownloadTask 对齐
    source_tid: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    source_magnet: Mapped[str] = mapped_column(Text, nullable=False)

    # 资源元信息（扫描时落盘，提交时无需重查外部库）
    source_title: Mapped[str] = mapped_column(Text)
    source_section: Mapped[str | None] = mapped_column(String(64))
    source_detail_url: Mapped[str | None] = mapped_column(Text)

    # 关键词命中；同一磁力可被多关键词命中各占一行
    # RESTRICT：禁止删除还有 candidate 引用的关键词
    matched_keyword_entry_id: Mapped[int] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="RESTRICT"),
        index=True, nullable=False,
    )
    matched_keyword: Mapped[str] = mapped_column(String(255))
    matched_alias: Mapped[str | None] = mapped_column(String(255))
    match_score: Mapped[float] = mapped_column(Float, default=0.0)

    # 重复检查快照
    last_scanned_tree_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("tree_imports.id", ondelete="SET NULL"),
    )
    duplicate_status: Mapped[str] = mapped_column(String(32))
    duplicate_reason: Mapped[str | None] = mapped_column(Text)
    matched_import_label: Mapped[str | None] = mapped_column(String(255))
    target_path: Mapped[str] = mapped_column(Text)

    # 生命周期
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True,
    )
    magnet_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("magnet_download_tasks.id", ondelete="SET NULL"),
    )
    dismissed_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_scanned_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_tid", "source_magnet", "matched_keyword_entry_id",
            name="uq_whitelist_candidate_source_keyword",
        ),
        Index(
            "ix_whitelist_candidate_lifecycle_keyword",
            "lifecycle_status", "matched_keyword_entry_id",
        ),
    )
