"""add downloader UI fields and task indexes"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20261101_0015"
down_revision = "20261031_0014"
branch_labels = None
depends_on = None


_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _bytes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(number, 0)


def backfill_task_fields(raw_payload_json: str) -> dict[str, Any]:
    """从旧快照 JSON 提取可筛选的任务字段。"""
    empty = {
        "remote_created_at": None,
        "remote_updated_at": None,
        "finished_at": None,
        "total_bytes": 0,
        "downloaded_bytes": 0,
        "channel_title": None,
    }
    try:
        payload = json.loads(raw_payload_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return empty
    if not isinstance(payload, dict):
        return empty
    created_at = _timestamp(payload.get("created_at"))
    updated_at = _timestamp(payload.get("updated_at"))
    total_bytes = downloaded_bytes = 0
    files = payload.get("files")
    if isinstance(files, list):
        for file_payload in files:
            if not isinstance(file_payload, dict):
                continue
            total_bytes += _bytes(file_payload.get("total_size_bytes"))
            downloaded_bytes += _bytes(file_payload.get("downloaded_size_bytes"))
    return {
        "remote_created_at": created_at,
        "remote_updated_at": updated_at,
        "finished_at": updated_at if str(payload.get("status") or "") in _TERMINAL_STATUSES else None,
        "total_bytes": total_bytes,
        "downloaded_bytes": downloaded_bytes,
        "channel_title": payload.get("chat_title") or None,
    }


def upgrade() -> None:
    with op.batch_alter_table("downloader_packages") as batch:
        batch.add_column(sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("ignored_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("completed_media_count", sa.Integer(), nullable=True))
    with op.batch_alter_table("downloader_task_snapshots") as batch:
        batch.add_column(sa.Column("remote_created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("remote_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("downloaded_bytes", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("channel_title", sa.Text(), nullable=True))
    op.create_index(
        "ix_downloader_tasks_node_created",
        "downloader_task_snapshots",
        ["node_key", "remote_created_at"],
    )
    op.create_index(
        "ix_downloader_tasks_node_status",
        "downloader_task_snapshots",
        ["node_key", "status"],
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, raw_payload_json FROM downloader_task_snapshots")).mappings().all()
    table = sa.table(
        "downloader_task_snapshots",
        sa.column("id", sa.Integer()),
        sa.column("remote_created_at", sa.DateTime(timezone=True)),
        sa.column("remote_updated_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("total_bytes", sa.BigInteger()),
        sa.column("downloaded_bytes", sa.BigInteger()),
        sa.column("channel_title", sa.Text()),
    )
    for row in rows:
        bind.execute(
            table.update().where(table.c.id == row["id"]).values(**backfill_task_fields(row["raw_payload_json"]))
        )


def downgrade() -> None:
    op.drop_index("ix_downloader_tasks_node_status", table_name="downloader_task_snapshots")
    op.drop_index("ix_downloader_tasks_node_created", table_name="downloader_task_snapshots")
    with op.batch_alter_table("downloader_task_snapshots") as batch:
        batch.drop_column("channel_title")
        batch.drop_column("downloaded_bytes")
        batch.drop_column("total_bytes")
        batch.drop_column("finished_at")
        batch.drop_column("remote_updated_at")
        batch.drop_column("remote_created_at")
    with op.batch_alter_table("downloader_packages") as batch:
        batch.drop_column("completed_media_count")
        batch.drop_column("ignored_reason")
        batch.drop_column("ignored_at")
