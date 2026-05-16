from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.models.organization import ExecutionJob
from app.schemas.plans import JobResponse

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = db.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.id == job_id)
        .options(selectinload(ExecutionJob.logs), selectinload(ExecutionJob.rollback_records))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)
