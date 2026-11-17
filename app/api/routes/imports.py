from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

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

router = APIRouter(prefix="/imports", tags=["imports"])
logger = logging.getLogger(__name__)

# 并发保护：同时最多 1 个 remote-fetch 任务
# 注意：locked() 检查和 create_task 之间不是真正原子的，但在单用户场景下
# FastAPI 的单线程事件循环使并发 POST 极少，锁本身在 _run_import 中保证串行
_import_lock = asyncio.Lock()
# 进度快照：import_id → {stage, current, total, done, error, finished_at}；
# 正常由 SSE 在 done 后 5s 回收，但客户端不订阅进度时条目会永久残留，
# 因此启动新任务前再做一次兜底清理。
_progress: dict[int, dict] = {}
_PROGRESS_RETENTION_SECONDS = 600


def _prune_progress() -> None:
    now = time.monotonic()
    expired = [
        key
        for key, state in _progress.items()
        if state.get("done") and state.get("finished_at") is not None
        and now - state["finished_at"] > _PROGRESS_RETENTION_SECONDS
    ]
    for key in expired:
        _progress.pop(key, None)


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
async def remote_fetch_tree(  # 必须是 async def，asyncio.create_task 需要运行中的 event loop
    payload: RemoteFetchRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _import_lock.locked():
        raise HTTPException(status_code=409, detail="已有导入任务在运行，请稍后再试")

    _prune_progress()
    BackgroundJobService.purge_expired(db)
    tree_import = TreeImport(
        status="pending",
        source_filename=f"remote:{payload.path_label}",
        source_type="remote_115",
        note=f"cid={payload.cid} depth_limit={payload.depth_limit}",
    )
    db.add(tree_import)
    db.commit()
    db.refresh(tree_import)
    import_id = tree_import.id

    BackgroundJobService.create(db, str(import_id), "remote_import")
    _progress[import_id] = {
        "job_id": str(import_id), "job_type": "remote_import",
        "stage": "等待开始", "current": 0, "total": 0, "done": False, "error": None, "summary": None,
        "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
    }
    asyncio.create_task(_run_import(import_id, payload))
    return {"import_id": import_id, "status": "pending"}


async def _run_import(import_id: int, payload: RemoteFetchRequest) -> None:
    async with _import_lock:
        await asyncio.to_thread(_blocking_import, import_id, payload)


def _blocking_import(import_id: int, payload: RemoteFetchRequest) -> None:
    from app.db.session import SessionLocal

    session = SessionLocal()

    def cb(stage: str, current: int, total: int) -> None:
        BackgroundJobService.update(session, str(import_id), stage=stage, current=current, total=total)
        if import_id in _progress:
            _progress[import_id].update(stage=stage, current=current, total=total)

    try:
        RemoteTreeFetchService(session).fetch_subtree(
            cid=payload.cid,
            path_label=payload.path_label,
            depth_limit=payload.depth_limit,
            folders_only=payload.folders_only,
            import_id=import_id,
            progress_cb=cb,
        )
        BackgroundJobService.update(session, str(import_id), stage="完成", done=True, finished_at=datetime.now(UTC))
        if import_id in _progress:
            _progress[import_id].update(stage="完成", done=True)
    except Exception as exc:
        try:
            from app.models.tree import TreeImport as TI
            rec = session.get(TI, import_id)
            if rec:
                rec.status = "failed"
                session.commit()
        except Exception as inner:
            logger.warning("导入失败后更新 DB 状态出错 import_id=%d: %s", import_id, inner)
        BackgroundJobService.update(session, str(import_id), stage="失败", error=str(exc), done=True, finished_at=datetime.now(UTC))
        if import_id in _progress:
            _progress[import_id].update(stage="失败", error=str(exc), done=True)
    finally:
        progress_state = _progress.get(import_id)
        if progress_state is not None:
            progress_state["finished_at"] = time.monotonic()
        session.close()


@router.get("/{import_id}/progress")
async def import_progress(import_id: int) -> StreamingResponse:
    """SSE 接口：每秒推送导入进度，done=True 后 5 秒结束并回收内存条目。"""
    async def event_stream():
        while True:
            from app.db.session import SessionLocal
            with SessionLocal() as session:
                state = BackgroundJobService.get(session, str(import_id))
            # 保留内存 fallback，兼容旧客户端/测试手动注入的进度快照。
            if state is None:
                state = _progress.get(import_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            if state["done"]:
                await asyncio.sleep(5)
                _progress.pop(import_id, None)
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/{import_id}")
def delete_import(import_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    tree_import = db.get(TreeImport, import_id)
    if tree_import is None:
        raise HTTPException(status_code=404, detail="Import not found")
    db.delete(tree_import)
    db.commit()
    return {"deleted": True}
