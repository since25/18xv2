# 冲突处理改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 UI 内联选择替换歧义冲突的 TSV 流程；为重复目标冲突增加三层懒加载详情 + 115 删除功能。

**Architecture:** 后端新增 5 个 JSON 接口（歧义 JSON list/resolve、node-details、resolve-duplicate-conflicts、115/file-info），前端重写 OrganizeTasksPage 中两个冲突处理区域。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、React + Vite + Ant Design

---

## 文件变更清单

| 文件 | 变更 |
|---|---|
| `app/services/tasks/organize_task_service.py` | 扩展 `AmbiguousKeywordConflict`（加 keyword_options）；新增 `apply_ambiguous_resolutions_from_json`、`get_node_details`、`resolve_duplicate_task_statuses` |
| `app/schemas/tasks.py` | 新增 `AmbiguousKeywordOption`、`AmbiguousConflictListResponse`、`AmbiguousResolveRequest`、`AmbiguousResolveResponse`、`NodeDetailRequest`、`NodeDetailItem`、`NodeDetailResponse`、`DuplicateResolution`、`DuplicateResolveRequest`、`DuplicateResolveResponse` |
| `app/api/routes/tasks.py` | 新增 `GET /ambiguous-conflicts`、`POST /ambiguous-conflicts/resolve`、`POST /node-details`、`POST /resolve-duplicate-conflicts` |
| `app/api/routes/files_115.py` | 新建：`POST /115/file-info` |
| `app/main.py` | 注册 `files_115` router |
| `tests/services/test_organize_task_service.py` | 新建：service 层单元测试 |
| `tests/api/test_tasks_conflicts.py` | 新建：API 层集成测试 |
| `frontend/src/api/types.ts` | 新增 7 个接口类型 |
| `frontend/src/pages/OrganizeTasksPage.tsx` | 重写歧义冲突区 + 重复冲突区 |

---

## Task 1：扩展 AmbiguousKeywordConflict，加入 keyword_options

**Files:**
- Modify: `app/services/tasks/organize_task_service.py`
- Create: `tests/services/test_organize_task_service.py`

- [ ] **Step 1：写失败测试**

新建 `tests/services/__init__.py`（若不存在）并创建测试文件：

```python
# tests/services/test_organize_task_service.py
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry, KeywordHit
from app.models.tree import TreeImport, TreeNode
from app.services.tasks.organize_task_service import OrganizeTaskService


def _seed_import(db: Session) -> tuple[int, int, int]:
    """返回 (import_id, keyword_id_a, keyword_id_b)"""
    ti = TreeImport(source_filename="test.txt", status="done")
    db.add(ti)
    db.flush()
    node = TreeNode(
        import_id=ti.id, raw_name="专辑X",
        normalized_name="专辑x", raw_path="/待整理/专辑X",
        depth=1, node_type="folder", fingerprint_hint="fp1",
    )
    db.add(node)
    ka = KeywordEntry(canonical_name="作者A", keyword_type="whitelist", status="active")
    kb = KeywordEntry(canonical_name="作者B", keyword_type="whitelist", status="active")
    db.add_all([ka, kb])
    db.flush()
    db.add_all([
        KeywordHit(import_id=ti.id, raw_keyword="作者A", normalized_keyword="作者a",
                   keyword_entry_id=ka.id, source_path="/待整理/专辑X", match_source="test"),
        KeywordHit(import_id=ti.id, raw_keyword="作者B", normalized_keyword="作者b",
                   keyword_entry_id=kb.id, source_path="/待整理/专辑X", match_source="test"),
    ])
    db.commit()
    return ti.id, ka.id, kb.id


def test_list_ambiguous_conflicts_returns_keyword_options(db_session: Session):
    import_id, ka_id, kb_id = _seed_import(db_session)
    conflicts = OrganizeTaskService(db_session).list_ambiguous_conflicts(import_id=import_id)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.source_path == "/待整理/专辑X"
    # keyword_options 必须包含 id 和 name
    assert len(conflict.keyword_options) == 2
    option_ids = {opt.id for opt in conflict.keyword_options}
    assert ka_id in option_ids
    assert kb_id in option_ids
    option_names = {opt.name for opt in conflict.keyword_options}
    assert "作者A" in option_names
    assert "作者B" in option_names
```

- [ ] **Step 2：运行，确认失败**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
.venv/bin/python -m pytest tests/services/test_organize_task_service.py::test_list_ambiguous_conflicts_returns_keyword_options -v
```

期望：`FAILED` — `AmbiguousKeywordConflict` 无 `keyword_options` 属性。

- [ ] **Step 3：修改 AmbiguousKeywordConflict，加入 keyword_options**

在 `app/services/tasks/organize_task_service.py` 顶部，在 `AmbiguousKeywordConflict` 之前新增：

```python
@dataclass(slots=True)
class AmbiguousKeywordOption:
    id: int
    name: str
```

修改 `AmbiguousKeywordConflict`：

```python
@dataclass(slots=True)
class AmbiguousKeywordConflict:
    source_path: str
    keywords: list[str]              # 保留，TSV export 继续使用
    keyword_options: list[AmbiguousKeywordOption]  # 新增，JSON 接口使用

    @property
    def keyword_count(self) -> int:
        return len(self.keywords)
```

修改 `list_ambiguous_conflicts` 中构造 `AmbiguousKeywordConflict` 的部分（第 251-260 行附近），将：

```python
conflicts.append(
    AmbiguousKeywordConflict(
        source_path=source_path,
        keywords=sorted(entry_by_id[keyword_id].canonical_name for keyword_id in keyword_ids),
    )
)
```

改为：

```python
sorted_options = sorted(
    [AmbiguousKeywordOption(id=kid, name=entry_by_id[kid].canonical_name) for kid in keyword_ids],
    key=lambda o: o.name,
)
conflicts.append(
    AmbiguousKeywordConflict(
        source_path=source_path,
        keywords=[opt.name for opt in sorted_options],
        keyword_options=sorted_options,
    )
)
```

- [ ] **Step 4：运行测试，确认通过**

```bash
.venv/bin/python -m pytest tests/services/test_organize_task_service.py::test_list_ambiguous_conflicts_returns_keyword_options -v
```

期望：`PASSED`

- [ ] **Step 5：提交**

```bash
git add app/services/tasks/organize_task_service.py tests/services/test_organize_task_service.py
git commit -m "feat: AmbiguousKeywordConflict 新增 keyword_options 字段（含关键词 ID）"
```

---

## Task 2：后端 - 歧义冲突 JSON 接口 + JSON resolve 接口

**Files:**
- Modify: `app/schemas/tasks.py`
- Modify: `app/services/tasks/organize_task_service.py`
- Modify: `app/api/routes/tasks.py`
- Modify: `tests/services/test_organize_task_service.py`

- [ ] **Step 1：写失败测试（service 层 resolve）**

追加到 `tests/services/test_organize_task_service.py`：

```python
def test_apply_ambiguous_resolutions_from_json(db_session: Session):
    import_id, ka_id, kb_id = _seed_import(db_session)
    svc = OrganizeTaskService(db_session)
    tasks, replaced, skipped, errors = svc.apply_ambiguous_resolutions_from_json(
        import_id=import_id,
        resolutions=[{"source_path": "/待整理/专辑X", "keyword_entry_id": ka_id}],
        replace_existing=True,
    )
    assert errors == []
    assert len(tasks) == 1
    assert tasks[0].keyword_entry_id == ka_id
    assert tasks[0].source_path == "/待整理/专辑X"
    assert "作者A" in tasks[0].target_path
```

- [ ] **Step 2：运行，确认失败**

```bash
.venv/bin/python -m pytest tests/services/test_organize_task_service.py::test_apply_ambiguous_resolutions_from_json -v
```

期望：`FAILED` — 方法不存在。

- [ ] **Step 3：在 service 中新增 apply_ambiguous_resolutions_from_json**

在 `app/services/tasks/organize_task_service.py` 的 `apply_ambiguous_resolutions_from_tsv` 方法之后添加：

```python
def apply_ambiguous_resolutions_from_json(
    self,
    *,
    import_id: int,
    resolutions: list[dict],  # [{source_path: str, keyword_entry_id: int}]
    replace_existing: bool = True,
) -> tuple[list[OrganizeTask], int, int, list[str]]:
    """JSON 版裁决应用，复用 TSV 版核心逻辑，入参改为 dict 列表。"""
    if not resolutions:
        return [], 0, 0, []

    # 构造等价的 TSV 文本，复用现有方法
    lines = ["source_path\tkeyword_count\tkeywords\tselected_keyword\tselected_keyword_id"]
    for item in resolutions:
        sp = str(item.get("source_path", "")).strip()
        kid = str(item.get("keyword_entry_id", "")).strip()
        lines.append(f"{sp}\t\t\t\t{kid}")
    tsv_text = "\n".join(lines) + "\n"
    return self.apply_ambiguous_resolutions_from_tsv(
        import_id=import_id,
        tsv_text=tsv_text,
        replace_existing=replace_existing,
    )
```

- [ ] **Step 4：运行测试，确认通过**

```bash
.venv/bin/python -m pytest tests/services/test_organize_task_service.py -v
```

期望：`2 passed`

- [ ] **Step 5：新增 Schema 类型**

在 `app/schemas/tasks.py` 末尾（`OrganizeTaskBatchResponse.model_rebuild()` 之前）添加：

```python
class AmbiguousKeywordOption(BaseModel):
    id: int
    name: str


class AmbiguousConflictItem(BaseModel):
    source_path: str
    keyword_options: list[AmbiguousKeywordOption]


class AmbiguousConflictListResponse(BaseModel):
    import_id: int
    conflict_count: int
    items: list[AmbiguousConflictItem]


class AmbiguousResolveItem(BaseModel):
    source_path: str
    keyword_entry_id: int


class AmbiguousResolveRequest(BaseModel):
    import_id: int
    resolutions: list[AmbiguousResolveItem]
    replace_existing: bool = True


class AmbiguousResolveResponse(BaseModel):
    import_id: int
    created_count: int
    replaced_count: int = 0
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 6：在 router 中新增两个端点**

在 `app/api/routes/tasks.py` 的 import 列表中补充新 schema，然后在文件末尾（workbench 之前）添加：

先在文件顶部 import 处补充：
```python
from app.schemas.tasks import (
    # ... 现有 imports ...
    AmbiguousConflictListResponse,
    AmbiguousResolveRequest,
    AmbiguousResolveResponse,
)
```

然后添加端点（放在 `export_ambiguous_conflicts` 之前）：

```python
@router.get("/ambiguous-conflicts", response_model=AmbiguousConflictListResponse)
def list_ambiguous_conflicts_json(
    import_id: int,
    db: Session = Depends(get_db),
) -> AmbiguousConflictListResponse:
    """返回 JSON 格式的歧义冲突列表（含关键词 ID，用于 UI 内联选择）。"""
    from app.schemas.tasks import AmbiguousConflictItem, AmbiguousKeywordOption as SchemaOption
    conflicts = OrganizeTaskService(db).list_ambiguous_conflicts(import_id=import_id)
    items = [
        AmbiguousConflictItem(
            source_path=c.source_path,
            keyword_options=[SchemaOption(id=opt.id, name=opt.name) for opt in c.keyword_options],
        )
        for c in conflicts
    ]
    return AmbiguousConflictListResponse(import_id=import_id, conflict_count=len(items), items=items)


@router.post("/ambiguous-conflicts/resolve", response_model=AmbiguousResolveResponse)
def resolve_ambiguous_conflicts_json(
    payload: AmbiguousResolveRequest,
    db: Session = Depends(get_db),
) -> AmbiguousResolveResponse:
    """接收 UI 选择的裁决，生成对应任务。"""
    resolutions = [{"source_path": r.source_path, "keyword_entry_id": r.keyword_entry_id} for r in payload.resolutions]
    tasks, replaced, skipped, errors = OrganizeTaskService(db).apply_ambiguous_resolutions_from_json(
        import_id=payload.import_id,
        resolutions=resolutions,
        replace_existing=payload.replace_existing,
    )
    return AmbiguousResolveResponse(
        import_id=payload.import_id,
        created_count=len(tasks),
        replaced_count=replaced,
        skipped_count=skipped,
        errors=errors,
    )
```

- [ ] **Step 7：运行全量测试确保无回归**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：所有已有测试 `PASSED`，新增 2 个 `PASSED`。

- [ ] **Step 8：提交**

```bash
git add app/schemas/tasks.py app/services/tasks/organize_task_service.py app/api/routes/tasks.py tests/services/test_organize_task_service.py
git commit -m "feat: 歧义冲突 JSON list/resolve 接口"
```

---

## Task 3：后端 - node-details 接口（懒加载第一层）

**Files:**
- Modify: `app/schemas/tasks.py`
- Modify: `app/api/routes/tasks.py`
- Modify: `tests/services/test_organize_task_service.py`

- [ ] **Step 1：写失败测试**

追加到 `tests/services/test_organize_task_service.py`：

```python
from app.models.tasks import OrganizeTask


def test_get_node_details_returns_cid_and_paths(db_session: Session):
    ti = TreeImport(source_filename="test2.txt", status="done")
    db_session.add(ti)
    db_session.flush()
    node = TreeNode(
        import_id=ti.id, raw_name="专辑Y", normalized_name="专辑y",
        raw_path="/待整理/专辑Y", depth=1, node_type="folder",
        fingerprint_hint="fp2", remote_cid="cid_abc",
    )
    db_session.add(node)
    db_session.flush()
    task = OrganizeTask(
        import_id=ti.id, node_id=node.id,
        source_path="/待整理/专辑Y", target_path="/根目录/已整理/专辑Y",
        status="pending",
    )
    db_session.add(task)
    db_session.commit()

    svc = OrganizeTaskService(db_session)
    details = svc.get_node_details(task_ids=[task.id])
    assert task.id in details
    item = details[task.id]
    assert item["raw_name"] == "专辑Y"
    assert item["raw_path"] == "/待整理/专辑Y"
    assert item["cid"] == "cid_abc"
```

- [ ] **Step 2：运行，确认失败**

```bash
.venv/bin/python -m pytest tests/services/test_organize_task_service.py::test_get_node_details_returns_cid_and_paths -v
```

期望：`FAILED` — `get_node_details` 不存在。

- [ ] **Step 3：在 service 中新增 get_node_details**

在 `app/services/tasks/organize_task_service.py` 末尾 `_sanitize_directory_name` 之前添加：

```python
def get_node_details(self, task_ids: list[int]) -> dict[int, dict]:
    """批量查本地 tree_nodes，返回 task_id → {raw_name, raw_path, cid} 映射。"""
    if not task_ids:
        return {}
    tasks = list(
        self.db.scalars(
            select(OrganizeTask).where(OrganizeTask.id.in_(task_ids))
        ).all()
    )
    node_id_to_task_id: dict[int, int] = {}
    for t in tasks:
        if t.node_id is not None:
            node_id_to_task_id[t.node_id] = t.id

    if not node_id_to_task_id:
        return {}

    nodes = list(
        self.db.scalars(
            select(TreeNode).where(TreeNode.id.in_(node_id_to_task_id.keys()))
        ).all()
    )
    result: dict[int, dict] = {}
    for node in nodes:
        task_id = node_id_to_task_id[node.id]
        result[task_id] = {
            "raw_name": node.raw_name,
            "raw_path": node.raw_path,
            "cid": node.remote_cid,
        }
    return result
```

- [ ] **Step 4：新增 Schema 类型**

在 `app/schemas/tasks.py` 中补充：

```python
class NodeDetailRequest(BaseModel):
    task_ids: list[int]


class NodeDetailItem(BaseModel):
    raw_name: str
    raw_path: str
    cid: str | None = None


class NodeDetailResponse(BaseModel):
    details: dict[int, NodeDetailItem]
```

- [ ] **Step 5：在 router 中新增端点**

在 `app/api/routes/tasks.py` import 处补充 `NodeDetailRequest, NodeDetailResponse`，在文件末尾添加：

```python
@router.post("/node-details", response_model=NodeDetailResponse)
def get_task_node_details(
    payload: NodeDetailRequest,
    db: Session = Depends(get_db),
) -> NodeDetailResponse:
    """批量查询各任务关联节点的本地信息（raw_name / raw_path / remote_cid）。"""
    raw = OrganizeTaskService(db).get_node_details(task_ids=payload.task_ids)
    from app.schemas.tasks import NodeDetailItem
    details = {tid: NodeDetailItem(**item) for tid, item in raw.items()}
    return NodeDetailResponse(details=details)
```

- [ ] **Step 6：运行全量测试**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：全部 `PASSED`。

- [ ] **Step 7：提交**

```bash
git add app/schemas/tasks.py app/services/tasks/organize_task_service.py app/api/routes/tasks.py tests/services/test_organize_task_service.py
git commit -m "feat: POST /organize-tasks/node-details 懒加载节点详情接口"
```

---

## Task 4：后端 - resolve-duplicate-conflicts 接口

**Files:**
- Modify: `app/schemas/tasks.py`
- Modify: `app/api/routes/tasks.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_tasks_conflicts.py`

- [ ] **Step 1：写失败测试（API 层）**

新建 `tests/api/__init__.py`（空文件）和 `tests/api/test_tasks_conflicts.py`：

```python
# tests/api/test_tasks_conflicts.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import keywords as _kw  # noqa: F401
from app.models import organization as _org  # noqa: F401
from app.models import tasks as _task  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.models.tasks import OrganizeTask
from app.models.tree import TreeImport, TreeNode
from app.services.client_115.client import Fake115Client


@pytest.fixture
def db_session(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session):
    from app.api.deps import get_db
    from app.main import app

    fake_115 = Fake115Client()
    app.state.client_115 = fake_115

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_dup_tasks(db: Session) -> tuple[int, int]:
    """创建两个 target_path 相同的 pending 任务，返回 (task_id_a, task_id_b)。"""
    ti = TreeImport(source_filename="dup.txt", status="done")
    db.add(ti)
    db.flush()
    node_a = TreeNode(
        import_id=ti.id, raw_name="专辑Z", normalized_name="专辑z",
        raw_path="/待整理/路径A/专辑Z", depth=2, node_type="folder",
        fingerprint_hint="fp_a", remote_cid="cid_a",
    )
    node_b = TreeNode(
        import_id=ti.id, raw_name="专辑Z", normalized_name="专辑z",
        raw_path="/待整理/路径B/专辑Z", depth=2, node_type="folder",
        fingerprint_hint="fp_b", remote_cid="cid_b",
    )
    db.add_all([node_a, node_b])
    db.flush()
    task_a = OrganizeTask(
        import_id=ti.id, node_id=node_a.id,
        source_path="/待整理/路径A/专辑Z",
        target_path="/根目录/已整理/专辑Z",
        status="pending",
    )
    task_b = OrganizeTask(
        import_id=ti.id, node_id=node_b.id,
        source_path="/待整理/路径B/专辑Z",
        target_path="/根目录/已整理/专辑Z",
        status="pending",
    )
    db.add_all([task_a, task_b])
    db.commit()
    return task_a.id, task_b.id


def test_resolve_duplicate_conflicts_skip_no_delete(client, db_session: Session):
    ta_id, tb_id = _make_dup_tasks(db_session)
    resp = client.post("/organize-tasks/resolve-duplicate-conflicts", json={
        "resolutions": [{
            "target_path": "/根目录/已整理/专辑Z",
            "keep_task_id": ta_id,
            "skip_task_ids": [tb_id],
            "delete_from_115": False,
        }]
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_count"] == 1
    assert body["deleted_from_115_count"] == 0
    assert body["errors"] == []
    # 验证 task_b 已变为 skipped
    db_session.expire_all()
    from sqlalchemy import select
    task_b = db_session.scalar(select(OrganizeTask).where(OrganizeTask.id == tb_id))
    assert task_b.status == "skipped"


def test_resolve_duplicate_conflicts_delete_from_115(client, db_session: Session):
    ta_id, tb_id = _make_dup_tasks(db_session)
    resp = client.post("/organize-tasks/resolve-duplicate-conflicts", json={
        "resolutions": [{
            "target_path": "/根目录/已整理/专辑Z",
            "keep_task_id": ta_id,
            "skip_task_ids": [tb_id],
            "delete_from_115": True,
        }]
    })
    assert resp.status_code == 200
    body = resp.json()
    # Fake115Client 无 cid_b 节点，delete 会抛异常 → errors 列表记录
    # 只要返回 200 且 resolved_count=1 即可（delete 失败不影响 skip）
    assert body["resolved_count"] == 1
```

- [ ] **Step 2：运行，确认失败**

```bash
.venv/bin/python -m pytest tests/api/test_tasks_conflicts.py -v
```

期望：`FAILED` — 端点不存在。

- [ ] **Step 3：新增 Schema 类型**

在 `app/schemas/tasks.py` 末尾添加：

```python
class DuplicateResolution(BaseModel):
    target_path: str
    keep_task_id: int
    skip_task_ids: list[int]
    delete_from_115: bool = False


class DuplicateResolveRequest(BaseModel):
    resolutions: list[DuplicateResolution]


class DuplicateResolveResponse(BaseModel):
    resolved_count: int
    deleted_from_115_count: int = 0
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 4：在 router 中新增端点**

在 `app/api/routes/tasks.py` import 处补充 `DuplicateResolveRequest, DuplicateResolveResponse`，并在文件末尾（workbench 之前）添加：

```python
@router.post("/resolve-duplicate-conflicts", response_model=DuplicateResolveResponse)
def resolve_duplicate_conflicts(
    payload: DuplicateResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DuplicateResolveResponse:
    """批量处理重复目标冲突：skip 未保留任务，可选从 115 删除。"""
    from fastapi import Request as _Request
    from sqlalchemy import select as _select

    client_115 = getattr(request.app.state, "client_115", None)
    resolved_count = 0
    deleted_from_115_count = 0
    errors: list[str] = []

    for res in payload.resolutions:
        # 1. 将 skip_task_ids 标记为 skipped
        skip_tasks = list(
            db.scalars(_select(OrganizeTask).where(OrganizeTask.id.in_(res.skip_task_ids))).all()
        )
        for t in skip_tasks:
            t.status = "skipped"
        db.flush()
        resolved_count += 1

        # 2. 可选：从 115 删除
        if res.delete_from_115 and client_115 is not None and skip_tasks:
            node_ids = [t.node_id for t in skip_tasks if t.node_id is not None]
            if node_ids:
                from app.models.tree import TreeNode as _TreeNode
                nodes = list(
                    db.scalars(_select(_TreeNode).where(_TreeNode.id.in_(node_ids))).all()
                )
                for node in nodes:
                    if not node.remote_cid:
                        errors.append(f"节点 {node.id}（{node.raw_path}）无 remote_cid，跳过删除")
                        continue
                    try:
                        client_115.delete_node(file_id=node.remote_cid, dry_run=False)
                        deleted_from_115_count += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"删除 {node.raw_path}（cid={node.remote_cid}）失败：{exc}")

    db.commit()
    return DuplicateResolveResponse(
        resolved_count=resolved_count,
        deleted_from_115_count=deleted_from_115_count,
        errors=errors,
    )
```

注意：需要在 router 函数签名中添加 `request: Request` 依赖，并在顶部 import `Request`：
```python
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
```

- [ ] **Step 5：运行测试**

```bash
.venv/bin/python -m pytest tests/api/test_tasks_conflicts.py -v
```

期望：`2 passed`

- [ ] **Step 6：运行全量测试**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：全部通过。

- [ ] **Step 7：提交**

```bash
git add app/schemas/tasks.py app/api/routes/tasks.py tests/api/__init__.py tests/api/test_tasks_conflicts.py
git commit -m "feat: POST /organize-tasks/resolve-duplicate-conflicts 批量解决重复目标冲突"
```

---

## Task 5：后端 - POST /115/file-info 接口

**Files:**
- Create: `app/api/routes/files_115.py`
- Modify: `app/main.py`

- [ ] **Step 1：创建新 router 文件**

```python
# app/api/routes/files_115.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/115", tags=["115"])


class FileInfoRequest(BaseModel):
    cids: list[str]


class FileInfoItem(BaseModel):
    size: int | None = None
    modified_at: str | None = None
    error: str | None = None


class FileInfoResponse(BaseModel):
    items: dict[str, FileInfoItem]


@router.post("/file-info", response_model=FileInfoResponse)
def get_file_info(payload: FileInfoRequest, request: Request) -> FileInfoResponse:
    """批量从 115 获取文件/文件夹的大小和修改时间（按需调用，懒加载）。"""
    client_115 = getattr(request.app.state, "client_115", None)
    if client_115 is None:
        raise HTTPException(status_code=503, detail="115 client 未初始化")

    items: dict[str, FileInfoItem] = {}
    for cid in payload.cids:
        try:
            raw = client_115.get_file(file_id=cid)
            data = raw.get("data") or {}
            # 115 API 字段：file_size（字节），utime（unix 更新时间）
            size = data.get("file_size") or data.get("size")
            utime = data.get("utime") or data.get("ptime")
            modified_at = None
            if utime:
                from datetime import datetime, timezone
                modified_at = datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
            items[cid] = FileInfoItem(
                size=int(size) if size is not None else None,
                modified_at=modified_at,
            )
        except Exception as exc:  # noqa: BLE001
            items[cid] = FileInfoItem(error=str(exc))

    return FileInfoResponse(items=items)
```

- [ ] **Step 2：在 main.py 中注册 router**

在 `app/main.py` 的 import 块中添加：
```python
from app.api.routes import (
    # ... 现有 ...
    files_115,
)
```

在 `app.include_router(open_auth.router)` 之后添加：
```python
app.include_router(files_115.router)
```

- [ ] **Step 3：验证 API 可启动**

```bash
.venv/bin/python -c "from app.main import app; print('OK')"
```

期望：输出 `OK`，无 ImportError。

- [ ] **Step 4：运行全量测试**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：全部通过。

- [ ] **Step 5：提交**

```bash
git add app/api/routes/files_115.py app/main.py
git commit -m "feat: POST /115/file-info 按需查询 115 文件大小和修改时间"
```

---

## Task 6：前端 - 新增 TypeScript 类型定义

**Files:**
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1：在 types.ts 末尾追加新类型**

在 `frontend/src/api/types.ts` 末尾（`OpenAuthRecordsResponse` 之后）添加：

```typescript
// ── 歧义冲突（JSON 接口）────────────────────────────────────
export interface AmbiguousKeywordOption {
  id: number
  name: string
}

export interface AmbiguousConflictItem {
  source_path: string
  keyword_options: AmbiguousKeywordOption[]
}

export interface AmbiguousConflictListResponse {
  import_id: number
  conflict_count: number
  items: AmbiguousConflictItem[]
}

export interface AmbiguousResolveItem {
  source_path: string
  keyword_entry_id: number
}

export interface AmbiguousResolveRequest {
  import_id: number
  resolutions: AmbiguousResolveItem[]
  replace_existing: boolean
}

export interface AmbiguousResolveResponse {
  import_id: number
  created_count: number
  replaced_count: number
  skipped_count: number
  errors: string[]
}

// ── 重复目标冲突（懒加载 + 删除）───────────────────────────
export interface NodeDetailItem {
  raw_name: string
  raw_path: string
  cid: string | null
}

export interface NodeDetailResponse {
  details: Record<number, NodeDetailItem>
}

export interface FileInfoItem {
  size: number | null
  modified_at: string | null
  error: string | null
}

export interface FileInfoResponse {
  items: Record<string, FileInfoItem>
}

export interface DuplicateResolution {
  target_path: string
  keep_task_id: number
  skip_task_ids: number[]
  delete_from_115: boolean
}

export interface DuplicateResolveResponse {
  resolved_count: number
  deleted_from_115_count: number
  errors: string[]
}
```

- [ ] **Step 2：验证 TypeScript 编译无错**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2/frontend
npm run build 2>&1 | tail -20
```

期望：无 TypeScript 错误（只要 types.ts 语法正确即可，页面未改动前可能有其他 warning）。

- [ ] **Step 3：提交**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
git add frontend/src/api/types.ts
git commit -m "feat: 前端新增歧义冲突和重复冲突相关 TypeScript 类型"
```

---

## Task 7：前端 - 歧义冲突内联 UI

**Files:**
- Modify: `frontend/src/pages/OrganizeTasksPage.tsx`

这是纯前端任务，不涉及 TDD。直接替换现有歧义冲突区域。

- [ ] **Step 1：确认现有歧义冲突区域在文件中的位置**

```bash
grep -n "导出冲突\|歧义冲突\|ambiguous\|exportConflicts\|importConflicts" /Users/wangyichuan/Desktop/wangcodemac/18x_v2/frontend/src/pages/OrganizeTasksPage.tsx | head -30
```

- [ ] **Step 2：在 OrganizeTasksPage.tsx 中增加歧义冲突状态**

在现有 state 声明区域（`const [dupConflicts, setDupConflicts]` 附近）添加：

```tsx
// 歧义冲突状态
const [ambiguousConflicts, setAmbiguousConflicts] = useState<AmbiguousConflictListResponse | null>(null)
const [ambiguousSelections, setAmbiguousSelections] = useState<Record<string, number>>({})  // source_path → keyword_entry_id
const [ambiguousLoading, setAmbiguousLoading] = useState(false)
const [ambiguousSubmitting, setAmbiguousSubmitting] = useState(false)
const [replaceExisting, setReplaceExisting] = useState(true)
```

在文件顶部 import 处补充类型：
```tsx
import type {
  // ... 现有类型 ...
  AmbiguousConflictListResponse,
  AmbiguousConflictItem,
} from '../api/types'
```

- [ ] **Step 3：添加歧义冲突加载和提交函数**

在现有函数区域添加（`loadDupConflicts` 函数附近）：

```tsx
const loadAmbiguousConflicts = async () => {
  if (!importId) return
  setAmbiguousLoading(true)
  try {
    const res = await api.get<AmbiguousConflictListResponse>(
      `/organize-tasks/ambiguous-conflicts?import_id=${importId}`
    )
    setAmbiguousConflicts(res)
    // 预填第一个选项
    const defaults: Record<string, number> = {}
    for (const item of res.items) {
      if (item.keyword_options.length > 0) {
        defaults[item.source_path] = item.keyword_options[0].id
      }
    }
    setAmbiguousSelections(defaults)
  } finally {
    setAmbiguousLoading(false)
  }
}

const submitAmbiguousResolutions = async () => {
  if (!importId || !ambiguousConflicts) return
  const resolutions = Object.entries(ambiguousSelections)
    .filter(([, kid]) => kid != null)
    .map(([source_path, keyword_entry_id]) => ({ source_path, keyword_entry_id }))
  if (resolutions.length === 0) {
    message.warning('请至少为一个冲突路径选择关键词')
    return
  }
  setAmbiguousSubmitting(true)
  try {
    const res = await api.post<AmbiguousResolveResponse>('/organize-tasks/ambiguous-conflicts/resolve', {
      import_id: importId,
      resolutions,
      replace_existing: replaceExisting,
    })
    message.success(`裁决完成：新建 ${res.created_count} 个任务，替换 ${res.replaced_count} 个`)
    if (res.errors.length > 0) {
      message.warning(`${res.errors.length} 条错误：${res.errors[0]}`)
    }
    await loadAmbiguousConflicts()
    await loadTasks()
  } finally {
    setAmbiguousSubmitting(false)
  }
}
```

注意：`api.post` 等方法根据项目现有 `api/client.ts` 的封装方式调用，若使用 `axios` 则用 `axios.post`。

- [ ] **Step 4：替换歧义冲突 Card 的 JSX 内容**

找到现有歧义冲突 Card（含"导出冲突明细"、"导入冲突裁决 TSV"的那一块），将其 `children` 替换为：

```tsx
<Space direction="vertical" style={{ width: '100%' }}>
  <Button onClick={loadAmbiguousConflicts} loading={ambiguousLoading}>
    加载歧义冲突
  </Button>

  {ambiguousConflicts && ambiguousConflicts.conflict_count === 0 && (
    <Alert type="success" message="当前批次无歧义冲突" showIcon />
  )}

  {ambiguousConflicts && ambiguousConflicts.conflict_count > 0 && (
    <>
      <Text type="secondary">
        共 {ambiguousConflicts.conflict_count} 条路径命中多个关键词，请为每条选择归属：
      </Text>
      {ambiguousConflicts.items.map((item: AmbiguousConflictItem) => (
        <Card
          key={item.source_path}
          size="small"
          style={{ background: '#fffbe6', borderColor: '#ffe58f' }}
        >
          <Text code style={{ fontSize: 12 }}>{item.source_path}</Text>
          <Radio.Group
            style={{ display: 'block', marginTop: 8 }}
            value={ambiguousSelections[item.source_path]}
            onChange={e =>
              setAmbiguousSelections(prev => ({
                ...prev,
                [item.source_path]: e.target.value,
              }))
            }
          >
            <Space direction="vertical">
              {item.keyword_options.map(opt => (
                <Radio key={opt.id} value={opt.id}>
                  {opt.name}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Card>
      ))}

      <Space>
        <Button
          size="small"
          onClick={() => {
            const defaults: Record<string, number> = {}
            ambiguousConflicts.items.forEach((item: AmbiguousConflictItem) => {
              if (item.keyword_options.length > 0) {
                defaults[item.source_path] = item.keyword_options[0].id
              }
            })
            setAmbiguousSelections(defaults)
          }}
        >
          全选第一个
        </Button>
        <Switch
          checkedChildren="替换已有"
          unCheckedChildren="不替换"
          checked={replaceExisting}
          onChange={setReplaceExisting}
        />
        <Button
          type="primary"
          onClick={submitAmbiguousResolutions}
          loading={ambiguousSubmitting}
          disabled={Object.keys(ambiguousSelections).length === 0}
        >
          保存裁决并生成任务
        </Button>
      </Space>
    </>
  )}

  <Collapse
    size="small"
    items={[{
      key: 'tsv',
      label: '高级操作：TSV 导出 / 导入',
      children: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Button size="small" onClick={() => {
            window.location.href = `/api/organize-tasks/ambiguous-conflicts/export?import_id=${importId}`
          }}>
            导出冲突 TSV
          </Button>
          {/* 原有 TSV 上传逻辑保留 */}
        </Space>
      ),
    }]}
  />
</Space>
```

根据当前页面实际 import 的 Ant Design 组件，补充缺少的 import：
```tsx
import { Alert, Button, Card, Collapse, Radio, Space, Switch, Typography, message } from 'antd'
const { Text } = Typography
```

- [ ] **Step 5：在浏览器中测试歧义冲突流程**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2/frontend
npm run dev
```

打开 `http://localhost:5173`，进入整理任务页，选择一个有歧义冲突的批次，点击"加载歧义冲突"，确认：
- 冲突路径列表显示正确
- Radio 可以选择
- "保存裁决"请求成功

- [ ] **Step 6：提交**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
git add frontend/src/pages/OrganizeTasksPage.tsx
git commit -m "feat: 歧义冲突 UI 内联 Radio 选择，替代 TSV 主流程"
```

---

## Task 8：前端 - 重复目标冲突三层懒加载 UI

**Files:**
- Modify: `frontend/src/pages/OrganizeTasksPage.tsx`

- [ ] **Step 1：增加重复冲突详情状态**

在现有 `dupConflicts` state 附近添加：

```tsx
// 重复冲突详情状态（懒加载）
const [dupNodeDetails, setDupNodeDetails] = useState<Record<string, NodeDetailResponse>>({})  // target_path → details
const [dupFileInfo, setDupFileInfo] = useState<Record<string, FileInfoResponse>>({})  // target_path → fileInfo
const [dupDetailLoading, setDupDetailLoading] = useState<Record<string, boolean>>({})  // target_path → loading
const [dupRefreshLoading, setDupRefreshLoading] = useState<Record<string, boolean>>({})
const [dupKeepTask, setDupKeepTask] = useState<Record<string, number>>({})  // target_path → keep_task_id
const [dupDeleteFrom115, setDupDeleteFrom115] = useState<Record<string, boolean>>({})  // target_path → bool
const [dupResolving, setDupResolving] = useState(false)
```

在文件顶部 import 处补充类型：
```tsx
import type {
  NodeDetailResponse,
  FileInfoResponse,
  DuplicateResolution,
} from '../api/types'
```

- [ ] **Step 2：添加懒加载和确认函数**

```tsx
const loadDupNodeDetails = async (targetPath: string, taskIds: number[]) => {
  setDupDetailLoading(prev => ({ ...prev, [targetPath]: true }))
  try {
    const res = await api.post<NodeDetailResponse>('/organize-tasks/node-details', {
      task_ids: taskIds,
    })
    setDupNodeDetails(prev => ({ ...prev, [targetPath]: res }))
  } finally {
    setDupDetailLoading(prev => ({ ...prev, [targetPath]: false }))
  }
}

const refreshDupFileInfo = async (targetPath: string, cids: string[]) => {
  const validCids = cids.filter(Boolean)
  if (validCids.length === 0) return
  setDupRefreshLoading(prev => ({ ...prev, [targetPath]: true }))
  try {
    const res = await api.post<FileInfoResponse>('/115/file-info', { cids: validCids })
    setDupFileInfo(prev => ({ ...prev, [targetPath]: res }))
  } finally {
    setDupRefreshLoading(prev => ({ ...prev, [targetPath]: false }))
  }
}

const confirmDupResolution = async () => {
  if (!dupConflicts) return
  const resolutions: DuplicateResolution[] = dupConflicts.groups
    .filter(g => dupKeepTask[g.target_path] != null)
    .map(g => ({
      target_path: g.target_path,
      keep_task_id: dupKeepTask[g.target_path],
      skip_task_ids: g.tasks.filter(t => t.id !== dupKeepTask[g.target_path]).map(t => t.id),
      delete_from_115: dupDeleteFrom115[g.target_path] ?? false,
    }))

  if (resolutions.length === 0) {
    message.warning('请至少为一个冲突组选择保留的任务')
    return
  }

  setDupResolving(true)
  try {
    const res = await api.post<DuplicateResolveResponse>('/organize-tasks/resolve-duplicate-conflicts', {
      resolutions,
    })
    message.success(`处理完成：${res.resolved_count} 组已解决，${res.deleted_from_115_count} 个文件已从 115 删除`)
    if (res.errors.length > 0) {
      message.warning(`${res.errors.length} 条错误：${res.errors[0]}`)
    }
    await loadDupConflicts()
  } finally {
    setDupResolving(false)
  }
}
```

- [ ] **Step 3：重写重复目标冲突区 JSX**

找到现有重复目标冲突 Card（含"查看重复目标冲突"按钮），将其内容替换为：

```tsx
<Card title="重复目标冲突">
  <Space direction="vertical" style={{ width: '100%' }}>
    <Button onClick={loadDupConflicts}>检查冲突</Button>

    {dupConflicts && dupConflicts.conflict_count === 0 && (
      <Alert type="success" message="当前批次无重复目标冲突" showIcon />
    )}

    {dupConflicts && dupConflicts.conflict_count > 0 && (
      <>
        <Text type="secondary">
          共 {dupConflicts.conflict_count} 组冲突，请为每组选择保留哪个文件：
        </Text>

        <Collapse
          items={dupConflicts.groups.map(group => {
            const details = dupNodeDetails[group.target_path]
            const fileInfo = dupFileInfo[group.target_path]
            const detailLoading = dupDetailLoading[group.target_path]
            const refreshLoading = dupRefreshLoading[group.target_path]

            return {
              key: group.target_path,
              label: (
                <Space>
                  <Text code style={{ fontSize: 12 }}>{group.target_path}</Text>
                  <Tag color="red">{group.tasks.length} 条冲突</Tag>
                </Space>
              ),
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {!details && (
                    <Button
                      size="small"
                      loading={detailLoading}
                      onClick={() =>
                        loadDupNodeDetails(group.target_path, group.tasks.map(t => t.id))
                      }
                    >
                      查看详情
                    </Button>
                  )}

                  <Radio.Group
                    value={dupKeepTask[group.target_path]}
                    onChange={e =>
                      setDupKeepTask(prev => ({ ...prev, [group.target_path]: e.target.value }))
                    }
                  >
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {group.tasks.map(task => {
                        const detail = details?.details?.[task.id]
                        const cid = detail?.cid
                        const info = cid ? fileInfo?.items?.[cid] : null
                        return (
                          <Radio key={task.id} value={task.id}>
                            <Space direction="vertical" size={2}>
                              <Text>{detail?.raw_name ?? task.source_path}</Text>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {detail?.raw_path ?? task.source_path}
                              </Text>
                              {info && !info.error && (
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {info.size != null ? `${(info.size / 1024 / 1024).toFixed(1)} MB` : '—'} ·{' '}
                                  {info.modified_at ? new Date(info.modified_at).toLocaleDateString('zh-CN') : '—'}
                                </Text>
                              )}
                            </Space>
                          </Radio>
                        )
                      })}
                    </Space>
                  </Radio.Group>

                  {details && (
                    <Button
                      size="small"
                      loading={refreshLoading}
                      onClick={() => {
                        const cids = group.tasks
                          .map(t => details?.details?.[t.id]?.cid)
                          .filter((c): c is string => Boolean(c))
                        refreshDupFileInfo(group.target_path, cids)
                      }}
                    >
                      从 115 刷新文件信息
                    </Button>
                  )}

                  <Space>
                    <Switch
                      checkedChildren="删除未保留文件"
                      unCheckedChildren="仅跳过任务"
                      checked={dupDeleteFrom115[group.target_path] ?? false}
                      onChange={v =>
                        setDupDeleteFrom115(prev => ({ ...prev, [group.target_path]: v }))
                      }
                    />
                  </Space>
                </Space>
              ),
            }
          })}
        />

        <Button
          type="primary"
          danger
          onClick={confirmDupResolution}
          loading={dupResolving}
          disabled={Object.keys(dupKeepTask).length === 0}
        >
          确认处理所有已选冲突
        </Button>
      </>
    )}
  </Space>
</Card>
```

根据实际 Ant Design 版本，确认 `Collapse` 的 `items` API（AntD v5 用 `items` prop）。若项目用的是 AntD v4，改用 `<Collapse.Panel>` 方式。

- [ ] **Step 4：在浏览器中测试**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2/frontend
npm run dev
```

验证：
1. 点"检查冲突"→ 显示冲突组
2. 每组默认只显示 source_path，不触发额外请求
3. 点"查看详情"→ 显示 raw_name/raw_path（来自 DB）
4. 点"从 115 刷新"→ 补充大小/修改时间（若 token 就绪）
5. 选择保留任务 + 开启删除开关 → "确认处理"后冲突消失

- [ ] **Step 5：运行全量后端测试确认无回归**

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：全部通过。

- [ ] **Step 6：提交**

```bash
git add frontend/src/pages/OrganizeTasksPage.tsx
git commit -m "feat: 重复目标冲突三层懒加载 UI + 115 删除功能"
```

---

## 验收检查

完成所有 Task 后执行：

```bash
# 后端测试
.venv/bin/python -m pytest tests/ -v

# 前端构建
cd frontend && npm run build
```

确认：
- [ ] 后端全部测试通过
- [ ] 前端无 TypeScript 编译错误
- [ ] 歧义冲突：加载→选择→保存，冲突列表刷新
- [ ] 重复冲突：默认视图→查看详情→刷新→确认处理，均正常
- [ ] 原 TSV 导出/导入仍可用（折叠隐藏但功能完整）
