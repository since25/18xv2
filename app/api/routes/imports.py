from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
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
# 进度快照：import_id → {stage, current, total, done, error}；done 后 5s 回收
_progress: dict[int, dict] = {}


@router.get("", response_class=HTMLResponse)
def imports_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>导入批次</title>
  <style>
    :root { --bg:#f6efe5; --card:#fffaf3; --ink:#1f2421; --muted:#5b645f; --accent:#0f5c8a; --soft:#dcebf4; --line:#ddd3c4; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f3ea 0%,#eee3d6 100%); color:var(--ink); }
    .shell { max-width:1180px; margin:0 auto; padding:28px 18px 40px; }
    .hero,.panel { background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 28px rgba(33,37,41,.06); }
    .hero { padding:24px; color:#fff; background:linear-gradient(135deg, rgba(15,92,138,.95), rgba(17,94,89,.92)); }
    .hero a { display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:0 14px; border-radius:14px; text-decoration:none; font-weight:600; background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.18); margin-right:10px; margin-top:14px; }
    .grid { display:grid; grid-template-columns:320px 1fr; gap:18px; margin-top:22px; }
    .panel { padding:20px; }
    label { display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }
    input, button { width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; }
    input { padding:12px 14px; background:#fff; }
    button { padding:12px 14px; cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
    button.secondary { background:var(--soft); color:var(--accent); border:1px solid rgba(15,92,138,.18); }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .actions button { flex:1; }
    .status,.box { margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; white-space:pre-wrap; font-size:13px; line-height:1.6; }
    .list { display:grid; gap:12px; }
    .card { border:1px solid var(--line); border-radius:18px; padding:14px; background:#fff; }
    .badges { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
    .badge { background:#eee5d8; border-radius:999px; padding:4px 10px; font-size:12px; color:var(--muted); }
    .meta { color:var(--muted); line-height:1.6; font-size:13px; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>导入批次</h1>
      <p>这里只展示批次级别信息，不再直接铺开整棵目录树。需要定位具体目录时，再进入节点页面按批次、关键词和层级筛选。</p>
      <a href="/workbench">返回统一工作台</a>
      <a href="/nodes">打开节点列表</a>
      <a href="/extractor/keywords/workbench">打开提取器</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <label for="treeFile">上传目录树文件</label>
        <input id="treeFile" type="file" accept=".txt,.text" />
        <label for="queryInput">按文件名搜索</label>
        <input id="queryInput" placeholder="例如 tree_sample" />
        <label for="limitInput">显示数量</label>
        <input id="limitInput" type="number" min="1" max="200" value="30" />
        <div class="actions">
          <button id="uploadBtn">导入目录树</button>
          <button class="secondary" id="refreshBtn">刷新列表</button>
        </div>
        <div class="status" id="statusBox">可以在这里上传目录树，或查看最近导入批次。</div>
      </aside>
      <section class="panel">
        <div class="box" id="metaBox">导入批次会显示在这里。</div>
        <div class="list" id="importList"></div>
      </section>
    </div>
  </div>
  <script>
    const importList = document.getElementById('importList');
    const metaBox = document.getElementById('metaBox');
    const statusBox = document.getElementById('statusBox');
    const queryInput = document.getElementById('queryInput');
    const limitInput = document.getElementById('limitInput');

    async function loadImports() {
      const params = new URLSearchParams();
      if (queryInput.value.trim()) params.set('query', queryInput.value.trim());
      params.set('limit', String(Number(limitInput.value) || 30));
      const response = await fetch(`/imports/data?${params.toString()}`);
      const body = await response.json();
      importList.innerHTML = '';
      metaBox.textContent = `当前返回 ${body.items.length} / ${body.total} 个导入批次。`;
      if (!body.items.length) {
        importList.innerHTML = '<div class="box">当前没有匹配的导入批次。</div>';
        return;
      }
      body.items.forEach(item => {
        const card = document.createElement('article');
        card.className = 'card';
        card.innerHTML = `
          <div><strong>#${item.id} · ${item.source_filename}</strong></div>
          <div class="badges">
            <span class="badge">${item.status}</span>
            <span class="badge">${String(item.imported_at).replace('T', ' ').slice(0, 19)}</span>
          </div>
          <div class="meta">${item.note || '无备注'}</div>
          <div class="actions">
            <button class="secondary" data-role="nodes">查看节点</button>
            <button class="secondary" data-role="extractor">进入提取器</button>
            <button class="secondary" data-role="delete">删除批次</button>
          </div>
        `;
        card.querySelector('[data-role="nodes"]').addEventListener('click', () => {
          window.location.href = `/nodes?import_id=${item.id}`;
        });
        card.querySelector('[data-role="extractor"]').addEventListener('click', () => {
          window.location.href = `/extractor/keywords/workbench`;
        });
        card.querySelector('[data-role="delete"]').addEventListener('click', async () => {
          const response = await fetch(`/imports/${item.id}`, { method: 'DELETE' });
          const body = await response.json();
          statusBox.textContent = response.ok ? `已删除批次 #${item.id}` : (body.detail || '删除失败');
          if (response.ok) {
            await loadImports();
          }
        });
        importList.appendChild(card);
      });
    }

    async function uploadTree() {
      const input = document.getElementById('treeFile');
      const file = input.files[0];
      if (!file) {
        statusBox.textContent = '请先选择一个目录树文件。';
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch('/imports/tree', { method: 'POST', body: formData });
      const body = await response.json();
      statusBox.textContent = response.ok ? `导入完成，批次 ID: ${body.id}` : (body.detail || '导入失败');
      if (response.ok) {
        await loadImports();
      }
    }

    document.getElementById('uploadBtn').addEventListener('click', uploadTree);
    document.getElementById('refreshBtn').addEventListener('click', loadImports);
    queryInput.addEventListener('input', loadImports);
    loadImports();
  </script>
</body>
</html>"""


@router.get("/data", response_model=TreeImportPageResponse)
def list_imports(
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> TreeImportPageResponse:
    stmt = select(TreeImport).order_by(TreeImport.id.desc())
    if query:
        stmt = stmt.where(TreeImport.source_filename.contains(query))
    rows = list(db.scalars(stmt).all())
    sliced = rows[offset : offset + max(1, min(limit, 200))]
    return TreeImportPageResponse(
        total=len(rows),
        items=[TreeImportSummaryResponse.model_validate(row) for row in sliced],
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

    _progress[import_id] = {
        "stage": "等待开始", "current": 0, "total": 0, "done": False, "error": None
    }
    asyncio.create_task(_run_import(import_id, payload))
    return {"import_id": import_id, "status": "pending"}


async def _run_import(import_id: int, payload: RemoteFetchRequest) -> None:
    async with _import_lock:
        await asyncio.to_thread(_blocking_import, import_id, payload)


def _blocking_import(import_id: int, payload: RemoteFetchRequest) -> None:
    from app.db.session import SessionLocal

    def cb(stage: str, current: int, total: int) -> None:
        _progress[import_id].update(stage=stage, current=current, total=total)

    session = SessionLocal()
    try:
        RemoteTreeFetchService(session).fetch_subtree(
            cid=payload.cid,
            path_label=payload.path_label,
            depth_limit=payload.depth_limit,
            folders_only=payload.folders_only,
            import_id=import_id,
            progress_cb=cb,
        )
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
        _progress[import_id].update(stage="失败", error=str(exc), done=True)
    finally:
        session.close()


@router.get("/{import_id}/progress")
async def import_progress(import_id: int) -> StreamingResponse:
    """SSE 接口：每秒推送导入进度，done=True 后 5 秒结束并回收内存条目。"""
    async def event_stream():
        while True:
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
