from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class TreeImport(Base):
    __tablename__ = "tree_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # file_upload = 文件导入；remote_115 = 115 Open API 拉取的远端快照
    source_type: Mapped[str] = mapped_column(String(50), default="file_upload", nullable=False)

    nodes: Mapped[list["TreeNode"]] = relationship(back_populates="tree_import", cascade="all, delete-orphan")
    files: Mapped[list["NodeFile"]] = relationship(back_populates="tree_import", cascade="all, delete-orphan")


class TreeNode(TimestampMixin, Base):
    __tablename__ = "tree_nodes"
    __table_args__ = (UniqueConstraint("import_id", "raw_path", name="uq_tree_nodes_import_raw_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    parent_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    fingerprint_hint: Mapped[str] = mapped_column(String(128), nullable=False)
    # 115 云盘目录 ID（仅 remote_115 来源的快照使用）
    remote_cid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tree_import: Mapped["TreeImport"] = relationship(back_populates="nodes")
    parent: Mapped["TreeNode | None"] = relationship(remote_side="TreeNode.id", back_populates="children")
    children: Mapped[list["TreeNode"]] = relationship(back_populates="parent")
    tags: Mapped[list["NodeTag"]] = relationship(back_populates="node", cascade="all, delete-orphan")
    files: Mapped[list["NodeFile"]] = relationship(back_populates="folder", cascade="all, delete-orphan")


class NodeFile(TimestampMixin, Base):
    __tablename__ = "node_files"
    __table_args__ = (UniqueConstraint("import_id", "raw_path", name="uq_node_files_import_raw_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_node_id: Mapped[int | None] = mapped_column(ForeignKey("tree_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    parent_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fingerprint_hint: Mapped[str] = mapped_column(String(128), nullable=False)
    remote_file_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_pick_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_full_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    tree_import: Mapped["TreeImport"] = relationship(back_populates="files")
    folder: Mapped["TreeNode | None"] = relationship(back_populates="files")


class NodeTag(TimestampMixin, Base):
    __tablename__ = "node_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("tree_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    tag: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="rule")

    node: Mapped["TreeNode"] = relationship(back_populates="tags")
