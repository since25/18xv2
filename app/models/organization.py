from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrganizationPlan(Base):
    __tablename__ = "organization_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_desc: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["OrganizationPlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    jobs: Mapped[list["ExecutionJob"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class OrganizationPlanItem(Base):
    __tablename__ = "organization_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("organization_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_target_path: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False, default="noop")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conflict_status: Mapped[str] = mapped_column(String(50), nullable=False, default="none")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped["OrganizationPlan"] = relationship(back_populates="items")


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("organization_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_required")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["OrganizationPlan"] = relationship(back_populates="jobs")
    logs: Mapped[list["ExecutionLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    rollback_records: Mapped[list["ExecutionRollbackRecord"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    before_path: Mapped[str] = mapped_column(Text, nullable=False)
    after_path: Mapped[str] = mapped_column(Text, nullable=False)
    api_status: Mapped[str] = mapped_column(String(50), nullable=False, default="skipped")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job: Mapped["ExecutionJob"] = relationship(back_populates="logs")


class ExecutionRollbackRecord(Base):
    __tablename__ = "execution_rollback_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    log_id: Mapped[int | None] = mapped_column(ForeignKey("execution_logs.id", ondelete="SET NULL"), nullable=True, index=True)
    undo_action: Mapped[str] = mapped_column(String(50), nullable=False)
    undo_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="recorded")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job: Mapped["ExecutionJob"] = relationship(back_populates="rollback_records")


class BatchPlanOperationLog(Base):
    __tablename__ = "batch_plan_operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_plan_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_plan_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped_plan_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
