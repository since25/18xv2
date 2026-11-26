"""女优档案、片子演员、待删清单、删除批次和白名单合集的数据表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Actress(Base):
    """一位女优的档案：规范名、黑白名单状态和片数。"""

    __tablename__ = "actresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name_normalized: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # none（未标）/ blacklist / whitelist
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="none", server_default="none", index=True)
    # 出现在多少个有效番号目录里，每次刷新重算
    film_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    aliases: Mapped[list["ActressAlias"]] = relationship(back_populates="actress", cascade="all, delete-orphan")


class ActressAlias(Base):
    """女优别名；归一化后的别名在全部女优之间唯一。"""

    __tablename__ = "actress_aliases"
    __table_args__ = (UniqueConstraint("alias_normalized", name="uq_actress_aliases_alias_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actress_id: Mapped[int] = mapped_column(ForeignKey("actresses.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    actress: Mapped[Actress] = relationship(back_populates="aliases")


class ActressMark(Base):
    """一次状态修改记录。"""

    __tablename__ = "actress_marks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actress_id: Mapped[int] = mapped_column(ForeignKey("actresses.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    # web（网页）/ player（播放器）/ import（旧名单导入）/ merge（合并）
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # 从哪部片上标的（如有）；片子条目被删时置空
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("jellyfin_media_items.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JellyfinMediaActor(Base):
    """扫描时从 NFO 读到的某个 STRM 条目的演员名单，每次扫描整体重算。"""

    __tablename__ = "jellyfin_media_actors"

    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("jellyfin_media_items.id", ondelete="CASCADE"), primary_key=True
    )
    # 演员在 NFO 里的先后次序，从 0 开始
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class ActressDeleteCandidate(Base):
    """待删清单里的一部片（一个番号目录）。"""

    __tablename__ = "actress_delete_candidates"
    __table_args__ = (UniqueConstraint("film_dir", name="uq_actress_delete_candidates_film_dir"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    film_dir: Mapped[str] = mapped_column(Text, nullable=False)
    # 本次是否删除，默认勾选
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # mark（改状态时加入）/ daily（每日任务加入）
    added_by: Mapped[str] = mapped_column(String(16), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 115 文件能否解析到：unchecked / found / missing / error
    remote_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unchecked", server_default="unchecked"
    )
    remote_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActressKeptFilm(Base):
    """用户标为「保留」的片子，每日任务不再把它放进待删清单。"""

    __tablename__ = "actress_kept_films"
    __table_args__ = (UniqueConstraint("film_dir", name="uq_actress_kept_films_film_dir"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    film_dir: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ActressDeleteBatch(Base):
    """一次「确认删除」生成的删除批次。"""

    __tablename__ = "actress_delete_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # pending / running / completed / failed / interrupted
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_films: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_films: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_films: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 删完后触发 Jellyfin 扫库的结果：done / skipped / error
    jellyfin_refresh: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    films: Mapped[list["ActressDeleteBatchFilm"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ActressDeleteBatchFilm.id"
    )


class ActressDeleteBatchFilm(Base):
    """删除批次里的一部片。"""

    __tablename__ = "actress_delete_batch_films"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("actress_delete_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    film_dir: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[str] = mapped_column(String(255), nullable=False)
    # pending / deleted / skipped / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    # 跳过原因（如已受白名单保护）
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    batch: Mapped[ActressDeleteBatch] = relationship(back_populates="films")
    files: Mapped[list["ActressDeleteBatchFile"]] = relationship(
        back_populates="film", cascade="all, delete-orphan", order_by="ActressDeleteBatchFile.id"
    )


class ActressDeleteBatchFile(Base):
    """删除批次里一部片要删的一个文件或目录。"""

    __tablename__ = "actress_delete_batch_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_film_id: Mapped[int] = mapped_column(
        ForeignKey("actress_delete_batch_films.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # remote_115（115 原文件）/ source_strm（porn_tv1 的 STRM）/ organized_dir（302porn_tv1 番号目录）
    group: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    remote_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # pending / deleted / missing / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    film: Mapped[ActressDeleteBatchFilm] = relationship(back_populates="files")


class JellyfinActressCollection(Base):
    """白名单女优与 Jellyfin 合集的同步映射，结构与关键词合集一致。"""

    __tablename__ = "jellyfin_actress_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actress_id: Mapped[int | None] = mapped_column(
        ForeignKey("actresses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    jellyfin_collection_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    canonical_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    # active / untagged / conflict / retired
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active", index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    actress = relationship("Actress")
