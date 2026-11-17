from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.background_job_service import BackgroundJobService
from app.models.tree import NodeFile, TreeImport, TreeNode
from app.schemas.imports import (
    RemoteFetchRequest,
    TreeImportEntryPageResponse,
    TreeImportEntryResponse,
    TreeImportPageResponse,
    TreeImportResponse,
    TreeImportSummaryResponse,
)
from app.services.importer.import_service import TreeImportService
from app.services.importer.remote_tree_service import RemoteTreeFetchService
from app.services.job_runner import JobAlreadyRunning, create_job, job_event_stream, submit_job

router = APIRouter(prefix="/imports", tags=["imports"])
logger = logging.getLogger(__name__)

@router.get("/data", response_model=TreeImportPageResponse)
def list_imports(
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> TreeImportPageResponse:
    stmt = select(TreeImport)
    count_stmt = select(func.count()).select_from(TreeImport)
    if query:
        stmt = stmt.where(TreeImport.source_filename.contains(query))
        count_stmt = count_stmt.where(TreeImport.source_filename.contains(query))
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    rows = db.scalars(
        stmt.order_by(TreeImport.id.desc()).offset(safe_offset).limit(safe_limit)
    ).all()
    total = db.scalar(count_stmt) or 0
    return TreeImportPageResponse(
        total=int(total),
        items=[TreeImportSummaryResponse.model_validate(row) for row in rows],
    )


@router.get("/{import_id}/entries", response_model=TreeImportEntryPageResponse)
def list_import_entries(
    import_id: int,
    query: str | None = None,
    max_depth: int | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> TreeImportEntryPageResponse:
    tree_import = db.get(TreeImport, import_id)
    if tree_import is None:
        raise HTTPException(status_code=404, detail="Import not found")

    node_stmt = select(TreeNode).where(TreeNode.import_id == import_id)
    file_stmt = select(NodeFile).where(NodeFile.import_id == import_id)
    if query:
        node_stmt = node_stmt.where((TreeNode.raw_name.contains(query)) | (TreeNode.raw_path.contains(query)))
        file_stmt = file_stmt.where((NodeFile.raw_name.contains(query)) | (NodeFile.raw_path.contains(query)))
    if max_depth is not None:
        node_stmt = node_stmt.where(TreeNode.depth <= max_depth)
        file_stmt = file_stmt.where(NodeFile.depth <= max_depth)

    nodes = db.scalars(node_stmt.order_by(TreeNode.raw_path.asc(), TreeNode.id.asc())).all()
    files = db.scalars(file_stmt.order_by(NodeFile.raw_path.asc(), NodeFile.id.asc())).all()
    items = [
        TreeImportEntryResponse(
            id=node.id,
            entry_type="folder",
            raw_name=node.raw_name,
            normalized_name=node.normalized_name,
            raw_path=node.raw_path,
            parent_path=node.parent_path,
            depth=node.depth,
            remote_id=node.remote_cid,
        )
        for node in nodes
    ] + [
        TreeImportEntryResponse(
            id=file.id,
            entry_type="file",
            raw_name=file.raw_name,
            normalized_name=file.normalized_name,
            raw_path=file.raw_path,
            parent_path=file.parent_path,
            depth=file.depth,
            remote_id=file.remote_file_id,
        )
        for file in files
    ]
    items.sort(key=lambda item: (item.raw_path, item.entry_type, item.id))
    sliced = items[offset : offset + max(1, min(limit, 500))]
    return TreeImportEntryPageResponse(total=len(items), items=sliced)


@router.post("/tree", response_model=TreeImportResponse)
async def import_tree(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TreeImportResponse:
    content = await file.read()
    tree_import = TreeImportService(db).import_tree(filename=file.filename or "tree.txt", raw_bytes=content)
    return TreeImportResponse.model_validate(tree_import)


@router.post("/remote-fetch")
async def remote_fetch_tree(
    payload: RemoteFetchRequest,
    db: Session = Depends(get_db),
) -> dict:
    BackgroundJobService.purge_expired(db)
    tree_import = TreeImport(
        status="pending",
        source_filename=f"remote:{payload.path_label}",
        source_type="remote_115",
        note=f"cid={payload.cid} depth_limit={payload.depth_limit}",
    )
    db.add(tree_import)
    db.flush()
    import_id = tree_import.id

    # 任务编号沿用导入批次编号；判重失败时回滚，不留下 pending 的导入批次
    try:
        create_job(db, "remote_import", job_id=str(import_id))
    except JobAlreadyRunning:
        db.rollback()
        raise HTTPException(status_code=409, detail="已有导入任务在运行，请稍后再试")

    def work(session, cb):
        try:
            RemoteTreeFetchService(session).fetch_subtree(
                cid=payload.cid,
                path_label=payload.path_label,
                depth_limit=payload.depth_limit,
                folders_only=payload.folders_only,
                import_id=import_id,
                progress_cb=cb,
            )
            # 与改造前一致：导入任务不写摘要
            return None
        except Exception:
            # 导入批次置为失败；这一步自身出错只记 warning，原异常继续交给启动器收尾
            try:
                session.rollback()
                rec = session.get(TreeImport, import_id)
                if rec:
                    rec.status = "failed"
                    session.commit()
            except Exception as inner:  # noqa: BLE001
                logger.warning("导入失败后更新 DB 状态出错 import_id=%d: %s", import_id, inner)
            raise

    submit_job(str(import_id), work)
    return {"import_id": import_id, "status": "pending"}


@router.get("/{import_id}/progress")
async def import_progress(import_id: int) -> StreamingResponse:
    """SSE 接口：每秒推送导入进度，done 后再推一帧断开。"""
    return StreamingResponse(job_event_stream(str(import_id)), media_type="text/event-stream")


@router.delete("/{import_id}")
def delete_import(import_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    tree_import = db.get(TreeImport, import_id)
    if tree_import is None:
        raise HTTPException(status_code=404, detail="Import not found")
    db.delete(tree_import)
    db.commit()
    return {"deleted": True}
