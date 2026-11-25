from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScriptRun(Base):
    """脚本的一次运行：Unraid 回报（trigger=report），或由 18x 定时/手动执行。"""

    __tablename__ = "script_runs"
    __table_args__ = (UniqueConstraint("run_key", name="uq_script_runs_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(512), nullable=False)
    script_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # 排队中、运行中的记录还没有结束时间和退出码
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # queued / running / success / warning / failed / stopped / interrupted
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    items_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # report（Unraid 回报）/ scheduled（18x 定时）/ manual（页面手动）
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="report", server_default="report")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 子进程 pid（同时是进程组号），用于重启后清理残留进程
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)

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


class ScriptJobConfig(Base):
    """一个脚本的调度配置和参数。"""

    __tablename__ = "script_job_configs"
    __table_args__ = (UniqueConstraint("job_name", name="uq_script_job_configs_job_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # unraid：仍由 Unraid 定时运行，18x 只收回报；18x：由 18x 定时执行
    executor: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # 每天运行时间，HH:MM，按 Asia/Shanghai
    run_time: Mapped[str] = mapped_column(String(5), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ScriptJobConfigChange(Base):
    """脚本配置的一次修改：完整记录修改前后。"""

    __tablename__ = "script_job_config_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)


class SehuatangPost(Base):
    """sehuatang 帖子的处理去向，用于跨天去重。"""

    __tablename__ = "sehuatang_posts"
    __table_args__ = (UniqueConstraint("tid", name="uq_sehuatang_posts_tid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tid: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("script_runs.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
