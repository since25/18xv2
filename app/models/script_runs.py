from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScriptRun(Base):
    """Unraid 脚本的一次运行回报。"""

    __tablename__ = "script_runs"
    __table_args__ = (UniqueConstraint("run_key", name="uq_script_runs_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(512), nullable=False)
    script_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    items_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    items: Mapped[list["ScriptRunItem"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class ScriptRunItem(Base):
    """一次脚本运行中需要展示的名单条目。"""

    __tablename__ = "script_run_items"
    __table_args__ = (Index("ix_script_run_items_run_id_kind", "run_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("script_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(512), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[ScriptRun] = relationship(back_populates="items")
