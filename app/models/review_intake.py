from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReviewIntakeItem(Base):
    __tablename__ = "review_intake_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    bucket: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="shortcut")
    note: Mapped[str | None] = mapped_column(Text)
    extracted_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    approved_keyword_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="SET NULL"),
    )
    approved_keyword: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("bucket", "path_hash", name="uq_review_intake_bucket_path_hash"),
        Index("ix_review_intake_bucket_status", "bucket", "status"),
    )
