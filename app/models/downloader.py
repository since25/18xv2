from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
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
    # Telegram supergroup/channel IDs use the -100... range and exceed int32.
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    boundary_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    media_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 资源包可能包含多 GB 媒体，累计大小超过 int32。
    known_total_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    current_download_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never", index=True)
    has_successful_attempt: Mapped[bool] = mapped_column(default=False, nullable=False)
    completed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ignored_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_media_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
        UniqueConstraint(
            "package_id",
            "keyword_entry_id",
            "package_revision",
            name="uq_downloader_candidate_package_keyword_revision",
        ),
        Index("ix_downloader_candidates_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("downloader_packages.id", ondelete="CASCADE"), nullable=False)
    keyword_entry_id: Mapped[int] = mapped_column(ForeignKey("keyword_entries.id", ondelete="CASCADE"), nullable=False)
    package_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
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
    package_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    download_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full", server_default="full")
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
        Index("ix_downloader_tasks_node_created", "node_key", "remote_created_at"),
        Index("ix_downloader_tasks_node_status", "node_key", "status"),
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
    remote_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    downloaded_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    channel_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_file_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DownloaderTaskHistory(Base):
    """任务详情发生变化时追加的不可变快照。"""

    __tablename__ = "downloader_task_histories"
    __table_args__ = (
        Index("ix_downloader_task_histories_task_observed", "node_key", "remote_task_id", "observed_at"),
        UniqueConstraint("node_key", "remote_task_id", "payload_hash", name="uq_downloader_task_history_payload"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False, default="rn")
    remote_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_file_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    files: Mapped[list["DownloaderTaskFileHistory"]] = relationship(
        back_populates="history", cascade="all, delete-orphan", order_by="DownloaderTaskFileHistory.message_id"
    )


class DownloaderTaskFileHistory(Base):
    """任务历史快照中的文件级状态。"""

    __tablename__ = "downloader_task_file_histories"
    __table_args__ = (
        UniqueConstraint("history_id", "message_id", name="uq_downloader_task_file_history_message"),
        Index("ix_downloader_task_file_histories_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    history_id: Mapped[int] = mapped_column(ForeignKey("downloader_task_histories.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    downloaded_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    download_speed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    save_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    upload_speed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    raw_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    history: Mapped[DownloaderTaskHistory] = relationship(back_populates="files")


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
