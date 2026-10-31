from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DownloaderPackage(Base):
    """RN 下载器资源包的本地快照。"""

    __tablename__ = "downloader_packages"
    __table_args__ = (
        UniqueConstraint("node_key", "remote_package_id", name="uq_downloader_packages_node_remote"),
        Index("ix_downloader_packages_status", "boundary_status", "current_download_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False, default="rn")
    remote_package_id: Mapped[int] = mapped_column(Integer, nullable=False)
    library_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    channel_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    boundary_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    known_total_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_download_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never", index=True)
    has_successful_attempt: Mapped[bool] = mapped_column(default=False, nullable=False)
    index_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    candidates: Mapped[list["DownloaderPackageCandidate"]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )
    submissions: Mapped[list["DownloaderSubmission"]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class DownloaderPackageCandidate(Base):
    """一个资源包被某条 18x 白名单命中的人工确认记录。"""

    __tablename__ = "downloader_package_candidates"
    __table_args__ = (
        UniqueConstraint("package_id", "keyword_entry_id", name="uq_downloader_candidate_package_keyword"),
        Index("ix_downloader_candidates_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("downloader_packages.id", ondelete="CASCADE"), nullable=False)
    keyword_entry_id: Mapped[int] = mapped_column(ForeignKey("keyword_entries.id", ondelete="CASCADE"), nullable=False)
    matched_term: Mapped[str] = mapped_column(String(255), nullable=False)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    package: Mapped[DownloaderPackage] = relationship(back_populates="candidates")


class DownloaderSubmission(Base):
    """18x 对某个远端资源包的一次幂等提交记录。"""

    __tablename__ = "downloader_submissions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_downloader_submission_idempotency"),
        Index("ix_downloader_submissions_task", "remote_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("downloader_packages.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("downloader_package_candidates.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    remote_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    package: Mapped[DownloaderPackage] = relationship(back_populates="submissions")


class DownloaderTaskSnapshot(Base):
    """下载器任务及文件进度的最新快照。"""

    __tablename__ = "downloader_task_snapshots"
    __table_args__ = (
        UniqueConstraint("node_key", "remote_task_id", name="uq_downloader_task_node_remote"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False, default="rn")
    remote_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_file_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DownloaderSyncRun(Base):
    """一次远端同步运行的结果。"""

    __tablename__ = "downloader_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    packages_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
