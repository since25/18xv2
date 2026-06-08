from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DedupeScanRun(Base):
    __tablename__ = "dedupe_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    scope_path_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    included_extensions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    candidate_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    high_confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    rules_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_groups: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    groups: Mapped[list["DedupeGroup"]] = relationship(back_populates="scan_run", cascade="all, delete-orphan")


class DedupeGroup(Base):
    __tablename__ = "dedupe_groups"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "group_key", name="uq_dedupe_groups_scan_run_group_key"),
        Index("ix_dedupe_groups_status_confidence", "status", "confidence_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("dedupe_scan_runs.id", ondelete="CASCADE"), nullable=False)
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False)
    group_key: Mapped[str] = mapped_column(String(512), nullable=False)
    representative_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    score_max: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    suggested_keep_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    scan_run: Mapped["DedupeScanRun"] = relationship(back_populates="groups")
    candidates: Mapped[list["DedupeCandidate"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class DedupeCandidate(Base):
    __tablename__ = "dedupe_candidates"
    __table_args__ = (
        UniqueConstraint("group_id", "node_file_id", name="uq_dedupe_candidates_group_node_file"),
        Index("ix_dedupe_candidates_user_action", "user_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("dedupe_groups.id", ondelete="CASCADE"), nullable=False)
    node_file_id: Mapped[int] = mapped_column(ForeignKey("node_files.id", ondelete="RESTRICT"), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    suggested_action: Mapped[str] = mapped_column(String(32), nullable=False)
    suggested_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped["DedupeGroup"] = relationship(back_populates="candidates")
    confirmations: Mapped[list["DedupeRemoteConfirmation"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class DedupeRemoteConfirmation(Base):
    __tablename__ = "dedupe_remote_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("dedupe_candidates.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    remote_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate: Mapped["DedupeCandidate"] = relationship(back_populates="confirmations")


class DedupeDeletePlan(Base):
    __tablename__ = "dedupe_delete_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_scan_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("dedupe_scan_runs.id", ondelete="SET NULL"), nullable=True
    )
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    confirm_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rate_limit_seconds: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["DedupeDeletePlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class DedupeDeletePlanItem(Base):
    __tablename__ = "dedupe_delete_plan_items"
    __table_args__ = (Index("ix_dedupe_plan_items_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dedupe_delete_plans.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("dedupe_candidates.id", ondelete="RESTRICT"), nullable=False)
    node_file_id: Mapped[int] = mapped_column(ForeignKey("node_files.id", ondelete="RESTRICT"), nullable=False)
    remote_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    delete_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["DedupeDeletePlan"] = relationship(back_populates="items")
