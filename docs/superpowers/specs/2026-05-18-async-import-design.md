# 目录树导入异步化设计

**目标：** 解决 `POST /imports/remote-fetch` 长时间同步阻塞导致 nginx 无响应、系统卡死的问题；同时为用户提供实时进度反馈。

**方案：** asyncio.to_thread + 内存进度存储 + SSE 推送（方案 B）

---

## 背景与根因

今天（2026-05-18）执行目录树导入后 Unraid 系统卡死，load average 破 999。根因链：

1. `POST /imports/remote-fetch` 同步阻塞最长 2 分钟（115 轮询 + DB 写入）
2. 系统高负载导致 nginx 响应变慢
3. Unraid WEBUI 监控脚本（已另外修复）判定 nginx 无响应，进入 `while ps -ef | grep nginx` 死循环
4. fork 风暴 → 系统彻底卡死

本设计解决第 1 点（其他点已独立修复）。

---

## 受影响文件

| 文件 | 变更类型 |
|---|---|
| `app/services/importer/import_service.py` | N×flush → 3 阶段批量插入 |
| `app/services/importer/remote_tree_service.py` | 加 `progress_cb` 回调 + 指数退避轮询 |
| `app/api/routes/imports.py` | remote-fetch 异步化 + Semaphore + 新增 SSE 接口 |

**无新依赖**——SSE 通过 FastAPI 内置 `StreamingResponse` 实现。

---

## 架构

```
POST /imports/remote-fetch
  │
  ├── 检查 Semaphore → 已有任务则 409
  ├── 创建 TreeImport 占位记录 (status="pending") → 拿到 import_id
  ├── asyncio.create_task(_run_import)   # 立即返回
  └── 返回 {import_id, status: "pending"}

asyncio Task: _run_import
  └── async with _import_sem
      └── await asyncio.to_thread(_blocking_import)   # event loop 不阻塞

_blocking_import（线程池内）
  ├── 独立创建 SessionLocal()            # 不复用请求的 session
  ├── progress_cb → 更新 _progress[import_id]
  └── RemoteTreeFetchService.fetch_subtree(progress_cb=cb)

GET /imports/{import_id}/progress        # SSE
  └── 每秒推送 _progress[import_id]，done=True 后关闭流
```

---

## 详细设计

### 1. imports.py：模块级状态

```python
import asyncio

_import_sem = asyncio.Semaphore(1)   # 同时最多 1 个导入任务
_progress: dict[int, dict] = {}      # import_id → 进度快照
```

### 2. imports.py：remote-fetch 路由

```python
@router.post("/remote-fetch")
async def remote_fetch_tree(payload: RemoteFetchRequest, db: Session = Depends(get_db)):
    if _import_sem.locked():
        raise HTTPException(409, "已有导入任务在运行，请稍后再试")

    # 创建占位记录，立即获得 import_id
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

    _progress[import_id] = {"stage": "等待开始", "current": 0, "total": 0, "done": False, "error": None}
    asyncio.create_task(_run_import(import_id, payload))
    return {"import_id": import_id, "status": "pending"}


async def _run_import(import_id: int, payload: RemoteFetchRequest) -> None:
    async with _import_sem:
        await asyncio.to_thread(_blocking_import, import_id, payload)


def _blocking_import(import_id: int, payload: RemoteFetchRequest) -> None:
    from app.db.session import SessionLocal

    def cb(stage: str, current: int, total: int) -> None:
        _progress[import_id].update(stage=stage, current=current, total=total)

    with SessionLocal() as session:
        try:
            RemoteTreeFetchService(session, import_id=import_id).fetch_subtree(
                cid=payload.cid,
                path_label=payload.path_label,
                depth_limit=payload.depth_limit,
                folders_only=payload.folders_only,
                progress_cb=cb,
            )
            _progress[import_id].update(stage="完成", done=True)
        except Exception as exc:
            _progress[import_id].update(stage="失败", error=str(exc), done=True)
```

### 3. imports.py：SSE 进度接口

```python
@router.get("/imports/{import_id}/progress")
async def import_progress(import_id: int):
    async def event_stream():
        while True:
            state = _progress.get(import_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            if state["done"]:
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**前端接入（无需额外库）：**
```javascript
const source = new EventSource(`/imports/${importId}/progress`)
source.onmessage = (e) => {
  const { stage, current, total, done, error } = JSON.parse(e.data)
  if (done) source.close()
}
```

### 4. remote_tree_service.py：progress_cb + 指数退避

`fetch_subtree` 新增 `progress_cb: Callable[[str, int, int], None] | None = None` 参数。

**进度阶段：**

| stage | current | total |
|---|---|---|
| `"触发导出"` | 0 | 1 |
| `"轮询导出状态"` | 已等待秒数 | 180（上限） |
| `"下载目录树"` | 0 | 1 |
| `"写入数据库"` | 已写节点数 | 总节点数 |

**轮询改指数退避（最坏 180 秒，快速任务前几次更快）：**

```python
delay = 1.0
elapsed = 0.0
while elapsed < 180:
    if progress_cb:
        progress_cb("轮询导出状态", int(elapsed), 180)
    status = client.fs_export_dir_status({"export_id": export_id})
    if 导出完成:
        break
    time.sleep(delay)
    elapsed += delay
    delay = min(delay * 1.5, 30)
else:
    raise RuntimeError("等待目录树导出超时（>3分钟）")
```

**`_persist_tree_import` 同步改造**（`remote_tree_service.py` 与 `import_service.py` 共用同一模式）：
- 加 `progress_cb` 在写入阶段汇报进度
- 补上 parent_id 回填（目前缺失）

### 5. import_service.py：3 阶段批量插入

```python
# 阶段 1：全部 folder 节点一次性 add_all，flush 拿 id
folder_nodes = [TreeNode(..., parent_id=None) for p in folder_parsed]
self.db.add_all(folder_nodes)
self.db.flush()

# 阶段 2：回填 parent_id
path_to_id = {n.raw_path: n.id for n in folder_nodes}
for node in folder_nodes:
    node.parent_id = path_to_id.get(node.parent_path or "")

# 阶段 3：file 节点 add_all，统一 commit
self.db.add_all(file_nodes)
self.db.commit()
```

原来 N 次 flush → 现在 1 次 flush + 1 次 commit。

---

## 边界与约束

- `_progress` 不持久化，服务重启后历史进度丢失（单用户场景可接受）
- `import_id` 不在 `_progress` 里（历史任务）→ SSE 立即推送 `error: not found` 并关闭
- 任务失败 → `done=True` + `error` 字段非空
- `POST /imports/tree`（文件上传路由）的 N×flush 同步修复，但不做异步化（文件上传通常很快）
- Semaphore 只保护 remote-fetch，文件上传路由不受限制

---

## 不在本次范围内

- 前端 UI 改造（进度条展示）：可单独做，接口已就绪
- 历史任务进度查询：需持久化，单用户暂不需要
- `/imports/tree` 异步化：文件上传耗时极短，不值得增加复杂度
