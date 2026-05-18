# 目录树导入异步化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `POST /imports/remote-fetch` 从同步阻塞改为异步后台任务，并通过 SSE 接口提供实时进度，防止长时间任务压垮系统。

**Architecture:** asyncio.to_thread 将阻塞操作移入线程池，event loop 保持响应；asyncio.Lock 做并发保护；进度写入模块级内存 dict，SSE endpoint 轮询推送。`_persist_tree_import` 改为 UPDATE 已有记录（不再 INSERT），消除双插入。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.x、pytest

---

## 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `app/services/importer/import_service.py` | 修：N×flush → 3 阶段批量插入 |
| `app/services/importer/remote_tree_service.py` | 修：`fetch_subtree` 加 `import_id`/`progress_cb`；`_persist_tree_import` 改 UPDATE；轮询改指数退避 |
| `app/api/routes/imports.py` | 修：remote-fetch 异步化 + Lock + SSE 接口 |
| `app/main.py` | 修：lifespan 清理残留 pending 记录 |
| `tests/importer/test_import_service.py` | 新建：import_service 批量插入测试 |
| `tests/importer/test_remote_tree_service.py` | 修：更新已有测试 + 新增 UPDATE/progress_cb 测试 |
| `tests/api/test_imports_async.py` | 新建：异步路由 + SSE 集成测试 |

---

## Task 1：import_service.py — 3 阶段批量插入

**Files:**
- Modify: `app/services/importer/import_service.py`
- Create: `tests/importer/test_import_service.py`

- [ ] **Step 1：写失败测试**

新建 `tests/importer/test_import_service.py`：

```python
from __future__ import annotations

import pytest
from app.services.importer.import_service import TreeImportService


TREE_WITH_NESTED_FOLDERS = b"""\
|---- root
| |- parent
| | |- child
"""


def test_batch_insert_sets_parent_id_correctly(db_session):
    """批量插入后 parent_id 应正确回填，child.parent_id == parent.id。"""
    svc = TreeImportService(db_session)
    result = svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)

    from app.models.tree import TreeNode
    from sqlalchemy import select
    nodes = db_session.scalars(
        select(TreeNode).where(TreeNode.import_id == result.id)
    ).all()
    by_name = {n.raw_name: n for n in nodes}

    assert by_name["child"].parent_id == by_name["parent"].id
    assert by_name["parent"].parent_id == by_name["root"].id
    assert by_name["root"].parent_id is None


def test_batch_insert_single_flush_not_n_flushes(db_session, monkeypatch):
    """验证不再发生 N 次 flush：flush 调用次数应 ≤ 3（阶段1一次、commit前无需再flush）。"""
    flush_count = 0
    original_flush = db_session.flush

    def counting_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", counting_flush)

    svc = TreeImportService(db_session)
    svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)

    # 原来 N 个 folder 就有 N 次 flush；现在最多 2 次（阶段1 + 可选阶段2）
    assert flush_count <= 2


def test_import_result_status_is_completed(db_session):
    svc = TreeImportService(db_session)
    result = svc.import_tree(filename="test.txt", raw_bytes=TREE_WITH_NESTED_FOLDERS)
    assert result.status == "completed"
    assert "folders=3" in (result.note or "")
```

- [ ] **Step 2：运行测试，确认失败**

```bash
cd /mnt/user/docker1/18xv2 && python -m pytest tests/importer/test_import_service.py -v
```

预期：`test_batch_insert_sets_parent_id_correctly` 通过（逻辑已有），`test_batch_insert_single_flush_not_n_flushes` **FAIL**（当前每个 folder 都 flush）。

- [ ] **Step 3：修改 import_service.py — 3 阶段批量插入**

将 `app/services/importer/import_service.py` 的 `import_tree` 方法中处理 folder 节点的循环替换为：

```python
def import_tree(self, filename: str, raw_bytes: bytes) -> TreeImport:
    parsed_nodes = parse_tree_bytes(raw_bytes)
    decoded_text = decode_tree_bytes(raw_bytes)
    tree_import = TreeImport(
        source_filename=filename,
        source_text=decoded_text,
        status="processing",
    )
    self.db.add(tree_import)
    self.db.flush()

    seen_paths: set[str] = set()
    skipped_duplicates = 0
    folder_parsed = []
    file_parsed = []
    for parsed in parsed_nodes:
        if parsed.raw_path in seen_paths:
            skipped_duplicates += 1
            continue
        seen_paths.add(parsed.raw_path)
        if parsed.node_type == "folder":
            folder_parsed.append(parsed)
        else:
            file_parsed.append(parsed)

    # 阶段 1：批量插入全部 folder 节点（parent_id 暂为 None），一次 flush 拿到所有 id
    folder_nodes = [
        TreeNode(
            import_id=tree_import.id,
            raw_name=p.name,
            normalized_name=normalize_folder_name(p.name),
            raw_path=p.raw_path,
            parent_path=p.parent_path,
            depth=p.depth,
            node_type="folder",
            parent_id=None,
            fingerprint_hint=p.fingerprint_hint,
        )
        for p in folder_parsed
    ]
    self.db.add_all(folder_nodes)
    self.db.flush()

    # 阶段 2：回填 parent_id（利用已有 id）
    path_to_id: dict[str, int] = {n.raw_path: n.id for n in folder_nodes}
    for node in folder_nodes:
        node.parent_id = path_to_id.get(node.parent_path or "")

    # 阶段 3：批量插入 file 节点，统一 commit
    file_nodes = [
        NodeFile(
            import_id=tree_import.id,
            folder_node_id=path_to_id.get(p.parent_path or ""),
            raw_name=p.name,
            normalized_name=p.name.strip(),
            raw_path=p.raw_path,
            parent_path=p.parent_path,
            depth=p.depth,
            file_ext=Path(p.name).suffix.lower() or None,
            fingerprint_hint=p.fingerprint_hint,
        )
        for p in file_parsed
    ]
    self.db.add_all(file_nodes)

    tree_import.status = "completed"
    tree_import.note = f"Imported {len(folder_nodes)} folders and {len(file_nodes)} files"
    if skipped_duplicates:
        tree_import.note += f", skipped {skipped_duplicates} duplicate paths"
    self.db.commit()
    self.db.refresh(tree_import)
    return tree_import
```

- [ ] **Step 4：运行测试，确认全部通过**

```bash
python -m pytest tests/importer/test_import_service.py -v
```

预期：3 个测试全部 PASS。

- [ ] **Step 5：运行全量测试，确认无回归**

```bash
python -m pytest tests/ -v --tb=short
```

预期：全部通过。

- [ ] **Step 6：提交**

```bash
git add app/services/importer/import_service.py tests/importer/test_import_service.py
git commit -m "perf: import_service 改 3 阶段批量插入，N×flush → 1flush+1commit"
```

---

## Task 2：remote_tree_service.py — _persist_tree_import 改 UPDATE + parent_id 回填

**Files:**
- Modify: `app/services/importer/remote_tree_service.py`
- Modify: `tests/importer/test_remote_tree_service.py`

- [ ] **Step 1：更新已有测试，让它们预先创建 TreeImport 占位记录**

在 `tests/importer/test_remote_tree_service.py` 中，两个已有测试都调用 `service.fetch_subtree(cid=..., path_label=..., depth_limit=...)` 但缺少 `import_id`。在每个测试开头加上：

```python
from app.models.tree import TreeImport

# 创建占位记录
placeholder = TreeImport(
    status="pending",
    source_filename="remote:根目录",
    source_type="remote_115",
    note="cid=0 depth_limit=3",
)
db_session.add(placeholder)
db_session.commit()
db_session.refresh(placeholder)
```

然后在 `service.fetch_subtree(...)` 调用中加入 `import_id=placeholder.id`。

- [ ] **Step 2：新增测试：_persist_tree_import 不创建第二条记录**

在 `tests/importer/test_remote_tree_service.py` 末尾追加：

```python
def test_persist_tree_import_updates_existing_record_not_insert(db_session, monkeypatch) -> None:
    """fetch_subtree 完成后 DB 中只有 1 条 TreeImport 记录，不产生第二条。"""
    from app.models.tree import TreeImport, TreeNode
    from sqlalchemy import select

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 99}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "1", "pick_code": "pc1"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- 根目录\n| |- 子目录\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:根目录",
                              source_type="remote_115", note="cid=1 depth_limit=3")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    result = service.fetch_subtree(cid="1", path_label="根目录", depth_limit=3,
                                   import_id=placeholder.id)

    total_imports = db_session.scalar(select(func.count()).select_from(TreeImport))
    assert total_imports == 1, f"期望 1 条 TreeImport 记录，实际 {total_imports} 条"
    assert result.id == placeholder.id
    assert result.status == "completed"


def test_persist_tree_import_backfills_parent_id(db_session, monkeypatch) -> None:
    """_persist_tree_import 完成后子节点的 parent_id 应正确指向父节点。"""
    from app.models.tree import TreeImport, TreeNode
    from sqlalchemy import select

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 88}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "2", "pick_code": "pc2"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- root\n| |- parent\n| | |- child\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:root",
                              source_type="remote_115", note="cid=2 depth_limit=3")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    result = service.fetch_subtree(cid="2", path_label="root", depth_limit=3,
                                   import_id=placeholder.id)

    nodes = db_session.scalars(
        select(TreeNode).where(TreeNode.import_id == result.id)
    ).all()
    by_name = {n.raw_name: n for n in nodes}
    assert by_name["child"].parent_id == by_name["parent"].id
    assert by_name["parent"].parent_id == by_name["root"].id


def test_progress_cb_called_with_expected_stages(db_session, monkeypatch) -> None:
    """fetch_subtree 应按顺序调用 progress_cb，包含 '轮询导出状态' 和 '写入数据库'。"""
    from app.models.tree import TreeImport

    service = RemoteTreeFetchService(db_session)
    fake_client = Mock()
    fake_client.fs_export_dir.return_value = {"state": True, "data": {"export_id": 77}}
    fake_client.fs_export_dir_status.return_value = {"data": {"file_id": "3", "pick_code": "pc3"}}
    fake_client.download_url.return_value = "http://example.com/tree.txt"

    class _Resp:
        content = "|---- root\n".encode()

    monkeypatch.setattr(service, "_get_p115_client", lambda: fake_client)
    monkeypatch.setattr("app.services.importer.remote_tree_service.http_requests.get", lambda *a, **kw: _Resp())

    placeholder = TreeImport(status="pending", source_filename="remote:root",
                              source_type="remote_115", note="cid=3 depth_limit=1")
    db_session.add(placeholder)
    db_session.commit()
    db_session.refresh(placeholder)

    stages: list[str] = []
    def cb(stage: str, current: int, total: int) -> None:
        stages.append(stage)

    service.fetch_subtree(cid="3", path_label="root", depth_limit=1,
                          import_id=placeholder.id, progress_cb=cb)

    assert "轮询导出状态" in stages
    assert "写入数据库" in stages
```

- [ ] **Step 3：运行测试，确认新测试失败**

```bash
python -m pytest tests/importer/test_remote_tree_service.py -v
```

预期：已有 2 个测试因缺少 `import_id` 参数报 TypeError FAIL；3 个新测试 FAIL。

- [ ] **Step 4：改造 remote_tree_service.py**

**4a. 修改 `fetch_subtree` 签名，加入 `import_id` 和 `progress_cb`：**

```python
def fetch_subtree(
    self,
    cid: str,
    path_label: str,
    *,
    depth_limit: int = 3,
    folders_only: bool = True,
    import_id: int,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> TreeImport:
```

在 `from __future__ import annotations` 后加入：
```python
from collections.abc import Callable
```

**4b. 在 fetch_subtree 中各关键步骤加 progress_cb 调用：**

触发导出后：
```python
if progress_cb:
    progress_cb("触发导出", 0, 1)
```

将轮询循环替换为指数退避：
```python
delay = 1.0
elapsed = 0.0
pick_code = None
# while/else：else 仅在条件耗尽时执行，break 退出不触发
while elapsed < 180:
    if progress_cb:
        progress_cb("轮询导出状态", int(elapsed), 180)
    status = client.fs_export_dir_status({"export_id": export_id})
    data = status.get("data")
    if isinstance(data, dict) and data.get("file_id"):
        pick_code = data.get("pick_code")
        logger.info("目录树导出完成 pick_code=%s", pick_code)
        break
    time.sleep(delay)
    elapsed += delay
    delay = min(delay * 1.5, 30)
else:
    raise RuntimeError("等待目录树导出超时（>3分钟）")
```

下载完成后：
```python
if progress_cb:
    progress_cb("下载目录树", 1, 1)
```

**4c. 将 `_persist_tree_import` 改为接受 `import_id` 并 UPDATE 已有记录：**

将方法签名改为：
```python
def _persist_tree_import(
    self,
    *,
    import_id: int,
    cid: str,
    depth_limit: int,
    raw_bytes: bytes,
    source_label: str,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> TreeImport:
```

方法体替换为：
```python
logger.info("开始解析目录树文本 source=%s cid=%s", source_label, cid)
parsed_nodes = parse_tree_bytes(raw_bytes)
folder_nodes_data = [p for p in parsed_nodes if p.node_type == "folder"]
logger.info("解析完成，文件夹节点数=%d", len(folder_nodes_data))

# 更新已有占位记录（不 INSERT 新行）
tree_import = self.db.get(TreeImport, import_id)
tree_import.status = "processing"
self.db.commit()

seen_paths: set[str] = set()
db_nodes: list[TreeNode] = []
for p in folder_nodes_data:
    if p.raw_path in seen_paths:
        continue
    seen_paths.add(p.raw_path)
    db_nodes.append(TreeNode(
        import_id=tree_import.id,
        raw_name=p.name,
        normalized_name=normalize_folder_name(p.name),
        raw_path=p.raw_path,
        parent_path=p.parent_path,
        depth=p.depth,
        node_type="folder",
        parent_id=None,
        fingerprint_hint=p.fingerprint_hint,
    ))

# 阶段 1：批量插入，一次 flush 拿到所有 id
self.db.add_all(db_nodes)
self.db.flush()
if progress_cb:
    progress_cb("写入数据库", 0, len(db_nodes))

# 阶段 2：回填 parent_id
path_to_id: dict[str, int] = {n.raw_path: n.id for n in db_nodes}
for node in db_nodes:
    node.parent_id = path_to_id.get(node.parent_path or "")
if progress_cb:
    progress_cb("写入数据库", len(db_nodes), len(db_nodes))

tree_import.status = "completed"
tree_import.note = f"cid={cid} depth_limit={depth_limit} folders={len(db_nodes)}"
self.db.commit()
self.db.refresh(tree_import)
logger.info("远端目录树快照完成：import_id=%d cid=%s folders=%d",
            tree_import.id, cid, len(db_nodes))
return tree_import
```

**4d. 同步更新 `fetch_subtree` 中对 `_persist_tree_import` 的所有调用，加入 `import_id=import_id` 和 `progress_cb=progress_cb` 参数。**

`fetch_subtree` 中有两处调用 `_persist_tree_import`（正常路径和根目录回退路径），两处均需更新：

```python
return self._persist_tree_import(
    import_id=import_id,
    cid=str(export_cid),
    depth_limit=depth_limit,
    raw_bytes=raw_bytes,
    source_label=label,
    progress_cb=progress_cb,
)
```

- [ ] **Step 5：运行测试，确认全部通过**

```bash
python -m pytest tests/importer/test_remote_tree_service.py -v
```

预期：5 个测试全部 PASS。

- [ ] **Step 6：运行全量测试**

```bash
python -m pytest tests/ -v --tb=short
```

预期：全部通过。

- [ ] **Step 7：提交**

```bash
git add app/services/importer/remote_tree_service.py tests/importer/test_remote_tree_service.py
git commit -m "refactor: remote_tree_service 改 UPDATE 已有记录 + progress_cb + 指数退避"
```

---

## Task 3：main.py — lifespan 清理残留 pending 记录

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1：在 lifespan 的 `yield` 之前加入清理逻辑**

在 `app/main.py` 的 `lifespan` 函数里，找到 `yield` 前的最后一行 `logger.info("115 client singleton ready in passive mode")`，在其之后、`yield` 之前插入：

```python
# 上次异常退出可能留下 status="pending" 的记录，防止 UI 显示永久 pending
from app.db.session import SessionLocal as _SessionLocal
from app.models.tree import TreeImport as _TreeImport
with _SessionLocal() as _s:
    interrupted = (
        _s.query(_TreeImport)
        .filter(_TreeImport.status == "pending")
        .update({"status": "interrupted"})
    )
    _s.commit()
    if interrupted:
        logger.info("lifespan: 清理 %d 条残留 pending 导入记录 → interrupted", interrupted)
```

- [ ] **Step 2：手动验证（无需自动化测试）**

```bash
# 在 DB 里手动插入一条 pending 记录后重启服务，确认启动日志出现
# "lifespan: 清理 1 条残留 pending 导入记录 → interrupted"
# 并确认 DB 该记录 status 变为 interrupted
```

- [ ] **Step 3：提交**

```bash
git add app/main.py
git commit -m "fix: lifespan 启动时清理残留 pending 导入记录"
```

---

## Task 4：imports.py — 异步化 remote-fetch + Lock + SSE

**Files:**
- Modify: `app/api/routes/imports.py`
- Create: `tests/api/test_imports_async.py`

- [ ] **Step 1：写失败测试**

新建 `tests/api/test_imports_async.py`：

```python
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import organization as _org  # noqa: F401
from app.models import tasks as _task  # noqa: F401
from app.models import tree as _tree  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个测试独立 SQLite + TestClient。"""
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)

    from app import main as _main
    from app.api.routes import imports as _imports
    from app.api import deps

    # 覆盖 DB 依赖，使用测试库
    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    # 重置模块级状态，防止测试间污染
    import importlib
    importlib.reload(_imports)
    _main.app.dependency_overrides[deps.get_db] = override_get_db

    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()


def test_remote_fetch_returns_import_id_immediately(client, monkeypatch):
    """POST /imports/remote-fetch 应立即返回 {import_id, status: pending}，不阻塞。"""
    from app.api.routes import imports as _imports

    # 让后台任务立即完成，避免真实 115 调用
    async def fake_run_import(import_id, payload):
        _imports._progress[import_id] = {
            "stage": "完成", "current": 1, "total": 1, "done": True, "error": None
        }

    monkeypatch.setattr(_imports, "_run_import", fake_run_import)

    resp = client.post("/imports/remote-fetch", json={
        "cid": "12345",
        "path_label": "测试目录",
        "depth_limit": 2,
        "folders_only": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "import_id" in data
    assert data["status"] == "pending"


def test_remote_fetch_returns_409_when_lock_held(client, monkeypatch):
    """并发第二次 POST 应返回 409。"""
    from app.api.routes import imports as _imports

    # 模拟 lock 已被持有
    async def fake_run_import(import_id, payload):
        await asyncio.sleep(10)  # 长时间持有 lock

    monkeypatch.setattr(_imports, "_run_import", fake_run_import)

    # 手动锁住
    async def _lock_it():
        await _imports._import_lock.acquire()

    import asyncio as _asyncio
    _asyncio.get_event_loop().run_until_complete(_lock_it())

    resp = client.post("/imports/remote-fetch", json={
        "cid": "99",
        "path_label": "测试",
        "depth_limit": 2,
        "folders_only": True,
    })
    assert resp.status_code == 409

    # 清理 lock
    _imports._import_lock.release()


def test_sse_progress_endpoint_streams_done(client, monkeypatch):
    """GET /imports/{id}/progress 应推送至少一帧，done=True 后结束。"""
    from app.api.routes import imports as _imports

    # 预置进度为已完成状态
    import_id = 999
    _imports._progress[import_id] = {
        "stage": "完成", "current": 5, "total": 5, "done": True, "error": None
    }

    with client.stream("GET", f"/imports/{import_id}/progress") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                break  # 拿到第一帧就够了

    assert len(frames) >= 1
    assert frames[0]["done"] is True
    assert frames[0]["stage"] == "完成"


def test_sse_progress_returns_error_for_unknown_import_id(client):
    """未知 import_id 应推送 error: not found 并结束。"""
    from app.api.routes import imports as _imports
    _imports._progress.clear()

    with client.stream("GET", "/imports/88888/progress") as resp:
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                break

    assert frames[0].get("error") == "not found"
```

- [ ] **Step 2：运行测试，确认失败**

```bash
python -m pytest tests/api/test_imports_async.py -v
```

预期：4 个测试全部 FAIL（`_import_lock`、`_run_import`、`_progress` 等尚未存在）。

- [ ] **Step 3：改造 imports.py**

**3a. 在文件顶部已有 import 区域后加入：**

```python
import asyncio
import json
from collections.abc import Callable
from fastapi.responses import StreamingResponse
```

**3b. 在 router 定义后加入模块级状态（两行）：**

```python
# 并发保护：同时最多 1 个 remote-fetch 任务（asyncio.Lock 保证原子检查+锁定）
_import_lock = asyncio.Lock()
# 进度快照：import_id → {stage, current, total, done, error}；done 后 5s 回收
_progress: dict[int, dict] = {}
```

**3c. 将原来的 `remote_fetch_tree` 函数完整替换为：**

```python
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
        except Exception:
            pass
        _progress[import_id].update(stage="失败", error=str(exc), done=True)
    finally:
        session.close()
```

**3d. 在 `remote_fetch_tree` 之后（文件末尾前）新增 SSE 接口：**

```python
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
```

- [ ] **Step 4：运行测试，确认全部通过**

```bash
python -m pytest tests/api/test_imports_async.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 5：运行全量测试**

```bash
python -m pytest tests/ -v --tb=short
```

预期：全部通过。

- [ ] **Step 6：提交**

```bash
git add app/api/routes/imports.py tests/api/test_imports_async.py
git commit -m "feat: remote-fetch 异步化 + Lock + SSE 进度接口"
```

---

## Task 5：验证端到端

- [ ] **Step 1：在服务器上部署并重启服务**

```bash
cd /mnt/user/docker1/18xv2 && git pull && docker compose restart
```

- [ ] **Step 2：触发一次导入，观察立即返回**

```bash
curl -s -X POST http://localhost:8000/imports/remote-fetch \
  -H "Content-Type: application/json" \
  -d '{"cid":"0","path_label":"根目录","depth_limit":2}' | jq .
```

预期：立即返回 `{"import_id": N, "status": "pending"}`，不等待 115 响应。

- [ ] **Step 3：用 SSE 接口观察进度**

```bash
curl -N http://localhost:8000/imports/{import_id}/progress
```

预期：每秒输出一行 `data: {"stage": "...", "current": ..., "total": ..., "done": false}`，完成后出现 `done: true`。

- [ ] **Step 4：验证并发保护**

在上一个导入进行中时，再次发送 POST：

```bash
curl -s -X POST http://localhost:8000/imports/remote-fetch \
  -H "Content-Type: application/json" \
  -d '{"cid":"1","path_label":"第二次","depth_limit":2}' | jq .
```

预期：返回 `{"detail": "已有导入任务在运行，请稍后再试"}` HTTP 409。

- [ ] **Step 5：观察系统负载正常**

```bash
watch -n 2 'cat /proc/loadavg'
```

预期：导入期间 load average 无异常飙升（相比修改前的 120-999）。

- [ ] **Step 6：最终提交（如有调试修改）**

```bash
git add -A && git commit -m "fix: 端到端验证后的微调（如有）"
```
