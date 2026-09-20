from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.background_jobs import BackgroundJob


class BackgroundJobService:
    """后台任务状态的统一持久化入口。"""

    @staticmethod
    def create(db: Session, job_id: str, job_type: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = BackgroundJob(
            job_id=job_id,
            job_type=job_type,
            stage="等待开始",
            current=0,
            total=0,
            done=False,
            started_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        return BackgroundJobService.to_dict(row)

    @staticmethod
    def update(db: Session, job_id: str, **changes: Any) -> dict[str, Any] | None:
        row = db.get(BackgroundJob, job_id)
        if row is None:
            return None
        summary = changes.pop("summary", None)
        if summary is not None:
            changes["summary_json"] = json.dumps(summary, ensure_ascii=False)
        for key, value in changes.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        db.commit()
        return BackgroundJobService.to_dict(row)

    @staticmethod
    def get(db: Session, job_id: str) -> dict[str, Any] | None:
        try:
            row = db.get(BackgroundJob, job_id)
        except OperationalError:
            db.rollback()
            return None
        return BackgroundJobService.to_dict(row) if row is not None else None

    @staticmethod
    def list_active(db: Session, job_type: str | None = None) -> list[dict[str, Any]]:
        stmt = select(BackgroundJob).where(BackgroundJob.done.is_(False)).order_by(BackgroundJob.started_at.asc())
        if job_type:
            stmt = stmt.where(BackgroundJob.job_type == job_type)
        try:
            rows = db.scalars(stmt).all()
        except OperationalError:
            db.rollback()
            return []
        return [BackgroundJobService.to_dict(row) for row in rows]

    @staticmethod
    def purge_expired(db: Session, retention_seconds: int = 600) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=retention_seconds)
        result = db.execute(
            delete(BackgroundJob).where(
                BackgroundJob.done.is_(True),
                BackgroundJob.finished_at.is_not(None),
                BackgroundJob.finished_at < cutoff,
            )
        )
        db.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def recover_running(db: Session) -> int:
        rows = db.scalars(select(BackgroundJob).where(BackgroundJob.done.is_(False))).all()
        count = 0
        for row in rows:
            row.stage = "服务重启，中断"
            row.error = "服务进程在任务完成前退出"
            row.done = True
            row.finished_at = datetime.now(UTC)
            row.updated_at = row.finished_at
            count += 1
        if count:
            db.commit()
        return count

    @staticmethod
    def to_dict(row: BackgroundJob) -> dict[str, Any]:
        summary = None
        if row.summary_json:
            try:
                summary = json.loads(row.summary_json)
            except json.JSONDecodeError:
                summary = None
        return {
            "job_id": row.job_id,
            "job_type": row.job_type,
            "stage": row.stage,
            "current": row.current,
            "total": row.total,
            "done": row.done,
            "error": row.error,
            "summary": summary,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
