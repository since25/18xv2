# 白名单批处理独立化 + 持久化候选账本 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把白名单批处理拆为独立页面 `/whitelist-batch`，引入持久化候选账本，扫描/提交均改为后台 job + SSE 推送，用户一次启动后自动循环到所有勾选项处理完。

**Architecture:** 新表 `whitelist_candidates` 跨次扫描去重；service 层 `app/services/whitelist/` 封装 scan / submit；路由 `app/api/routes/whitelist_batch.py` 复用 §async-import 的 asyncio.Lock + asyncio.to_thread + SSE 模式（两把锁：scan_lock + submit_lock）。前端新页面 `WhitelistBatchPage.tsx`，旧 `MagnetTasksPage` 删掉白名单批处理 Card。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / antd 5 / React Router

**Spec reference:** `docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md`

---

## 文件清单

### 新建
- `app/models/whitelist.py` — `WhitelistCandidate` 模型
- `alembic/versions/20260519_0005_whitelist_candidates.py` — 建表迁移
- `app/schemas/whitelist.py` — Pydantic schemas
- `app/services/whitelist/__init__.py` — 包入口
- `app/services/whitelist/candidate_service.py` — 主服务（scan / submit / list / dismiss / restore）
- `app/api/routes/whitelist_batch.py` — HTTP 路由 + job 编排
- `tests/whitelist/__init__.py`
- `tests/whitelist/test_candidate_service_scan.py`
- `tests/whitelist/test_candidate_service_submit.py`
- `tests/whitelist/test_candidate_service_list_dismiss.py`
- `tests/whitelist/test_whitelist_batch_routes.py`
- `frontend/src/api/whitelistBatch.ts` — 前端 API 包装
- `frontend/src/pages/WhitelistBatchPage.tsx` — 新页面

### 修改
- `tests/conftest.py:11-14` — 注册 `whitelist` 模型
- `app/main.py:23-56` — 注册路由、启动 sweeper、删除 stale-pending tree 清理无关
- `app/main.py:63-84` — import 新路由
- `app/api/routes/magnet_tasks.py:153-224` — 删除 `/whitelist-batch/preview` 和 `/whitelist-batch/submit`
- `app/services/magnet_download_service.py:644-760` — 删除 `preview_whitelist_batch` + `submit_whitelist_batch`
- `app/schemas/magnet_tasks.py` — 删除 `WhitelistBatchRequest` / `WhitelistBatchPreviewResponse` / `WhitelistBatchSubmitResponse` / `WhitelistBatchCandidateResponse`
- `frontend/src/App.tsx:40-52` — 新增 NAV 项 + Route 元素
- `frontend/src/pages/MagnetTasksPage.tsx` — 删除白名单批处理 Card 及相关 state / handlers (~200 行)
- `frontend/src/api/types.ts` — 删除旧白名单批处理类型
- `docker/nginx.conf` — `/api/` location 加 SSE 长连接配置

---

### Task 1: 数据模型 + Alembic 迁移

**Files:**
- Create: `app/models/whitelist.py`
- Create: `alembic/versions/20260519_0005_whitelist_candidates.py`
- Modify: `tests/conftest.py:11-14`
- Test: `tests/whitelist/__init__.py` (空), `tests/whitelist/test_model.py`

- [ ] **Step 1: 写失败测试 — 验证模型可以建实例 + 唯一约束生效**

创建 `tests/whitelist/__init__.py` 为空文件。

创建 `tests/whitelist/test_model.py`：
```python
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.whitelist import WhitelistCandidate
from app.models.keywords import KeywordEntry


def _make_keyword(db, name="演员A"):
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type="whitelist",
        status="active",
    )
    db.add(entry)
    db.commit()
    return entry


def test_whitelist_candidate_can_be_created(db_session):
    entry = _make_keyword(db_session)
    cand = WhitelistCandidate(
        source_tid=12345,
        source_magnet="magnet:?xt=urn:btih:abc",
        source_title="测试资源",
        matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name,
        match_score=0.95,
        duplicate_status="clear",
        target_path="/已整理/演员A/测试资源",
        lifecycle_status="pending",
    )
    db_session.add(cand)
    db_session.commit()
    assert cand.id is not None
    assert cand.first_seen_at is not None
    assert cand.last_scanned_at is not None


def test_whitelist_candidate_unique_per_tid_magnet_keyword(db_session):
    """同一 (tid, magnet, keyword_id) 不能存两行；换 keyword 可以。"""
    entry_a = _make_keyword(db_session, "演员A")
    entry_b = _make_keyword(db_session, "演员B")

    def _new(entry):
        return WhitelistCandidate(
            source_tid=999,
            source_magnet="magnet:?xt=urn:btih:same",
            source_title="t",
            matched_keyword_entry_id=entry.id,
            matched_keyword=entry.canonical_name,
            duplicate_status="clear",
            target_path="/x",
        )

    db_session.add(_new(entry_a))
    db_session.commit()

    # 同 (tid, magnet, keyword) → IntegrityError
    db_session.add(_new(entry_a))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 换 keyword → OK
    db_session.add(_new(entry_b))
    db_session.commit()
```

- [ ] **Step 2: 运行测试，确认失败（model 不存在）**

Run: `source .venv/bin/activate && pytest tests/whitelist/test_model.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models.whitelist'`

- [ ] **Step 3: 创建模型 `app/models/whitelist.py`**

```python
"""持久化的白名单扫描候选账本。

跨次扫描去重 + 生命周期跟踪。详见
docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §3
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WhitelistCandidate(Base):
    __tablename__ = "whitelist_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 去重键（业务唯一）；source_tid 用 Integer 与 MagnetDownloadTask 对齐
    source_tid: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    source_magnet: Mapped[str] = mapped_column(Text, nullable=False)

    # 资源元信息（扫描时落盘，提交时无需重查外部库）
    source_title: Mapped[str] = mapped_column(Text)
    source_section: Mapped[str | None] = mapped_column(String(64))
    source_detail_url: Mapped[str | None] = mapped_column(Text)

    # 关键词命中；同一磁力可被多关键词命中各占一行
    # RESTRICT：禁止删除还有 candidate 引用的关键词
    matched_keyword_entry_id: Mapped[int] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="RESTRICT"),
        index=True, nullable=False,
    )
    matched_keyword: Mapped[str] = mapped_column(String(255))
    matched_alias: Mapped[str | None] = mapped_column(String(255))
    match_score: Mapped[float] = mapped_column(Float, default=0.0)

    # 重复检查快照
    last_scanned_tree_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("tree_imports.id", ondelete="SET NULL"),
    )
    duplicate_status: Mapped[str] = mapped_column(String(32))
    duplicate_reason: Mapped[str | None] = mapped_column(Text)
    matched_import_label: Mapped[str | None] = mapped_column(String(255))
    target_path: Mapped[str] = mapped_column(Text)

    # 生命周期
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True,
    )
    magnet_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("magnet_download_tasks.id", ondelete="SET NULL"),
    )
    dismissed_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_scanned_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_tid", "source_magnet", "matched_keyword_entry_id",
            name="uq_whitelist_candidate_source_keyword",
        ),
        Index(
            "ix_whitelist_candidate_lifecycle_keyword",
            "lifecycle_status", "matched_keyword_entry_id",
        ),
    )
```

- [ ] **Step 4: 注册模型到 conftest**

修改 `tests/conftest.py`，把第 11-14 行扩展为：
```python
from app.models import keywords as _keywords_models  # noqa: F401
from app.models import organization as _organization_models  # noqa: F401
from app.models import tasks as _task_models  # noqa: F401
from app.models import tree as _tree_models  # noqa: F401
from app.models import whitelist as _whitelist_models  # noqa: F401
```

- [ ] **Step 5: 运行测试验证模型层通过**

Run: `pytest tests/whitelist/test_model.py -v`
Expected: 2 PASS

- [ ] **Step 6: 创建 Alembic 迁移**

创建 `alembic/versions/20260519_0005_whitelist_candidates.py`：
```python
"""add whitelist_candidates

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whitelist_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_tid", sa.Integer(), nullable=False, index=True),
        sa.Column("source_magnet", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_section", sa.String(64), nullable=True),
        sa.Column("source_detail_url", sa.Text(), nullable=True),
        sa.Column(
            "matched_keyword_entry_id", sa.Integer(),
            sa.ForeignKey("keyword_entries.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("matched_keyword", sa.String(255), nullable=False),
        sa.Column("matched_alias", sa.String(255), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "last_scanned_tree_import_id", sa.Integer(),
            sa.ForeignKey("tree_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("duplicate_status", sa.String(32), nullable=False),
        sa.Column("duplicate_reason", sa.Text(), nullable=True),
        sa.Column("matched_import_label", sa.String(255), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column(
            "lifecycle_status", sa.String(32),
            nullable=False, server_default="pending", index=True,
        ),
        sa.Column(
            "magnet_task_id", sa.Integer(),
            sa.ForeignKey("magnet_download_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source_tid", "source_magnet", "matched_keyword_entry_id",
            name="uq_whitelist_candidate_source_keyword",
        ),
    )
    op.create_index(
        "ix_whitelist_candidate_lifecycle_keyword",
        "whitelist_candidates",
        ["lifecycle_status", "matched_keyword_entry_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whitelist_candidate_lifecycle_keyword",
        table_name="whitelist_candidates",
    )
    op.drop_table("whitelist_candidates")
```

- [ ] **Step 7: 验证迁移可在本地 SQLite 升级 / 降级**

Run:
```bash
cp data/storage_organizer.db data/storage_organizer.db.bak.task1
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```
Expected: 三步均无报错；最后停在 head。

- [ ] **Step 8: 提交**

```bash
git add app/models/whitelist.py alembic/versions/20260519_0005_whitelist_candidates.py tests/conftest.py tests/whitelist/__init__.py tests/whitelist/test_model.py
git commit -m "feat: 新增 whitelist_candidates 表 + WhitelistCandidate 模型

唯一键 (source_tid, source_magnet, matched_keyword_entry_id) 支持
同一磁力被多关键词命中各占一行；matched_keyword_entry_id 外键 RESTRICT
防误删失史。"
```

---

### Task 2: Pydantic schemas

**Files:**
- Create: `app/schemas/whitelist.py`
- Test: `tests/whitelist/test_schemas.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/whitelist/test_schemas.py`：
```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.whitelist import (
    CandidateResponse,
    DismissRequest,
    JobFrame,
    ScanJobRequest,
    ScanSummary,
    SubmitJobRequest,
    SubmitSummary,
)


def test_scan_job_request_defaults():
    req = ScanJobRequest(tree_import_id=42)
    assert req.tree_import_id == 42
    assert req.keyword_entry_ids is None
    assert req.per_keyword_limit == 10


def test_submit_job_request_requires_ids():
    with pytest.raises(ValidationError):
        SubmitJobRequest(candidate_ids=[])


def test_submit_job_request_force_submit_default_false():
    req = SubmitJobRequest(candidate_ids=[1, 2])
    assert req.force_submit is False


def test_dismiss_request_reason_optional():
    assert DismissRequest().reason is None
    assert DismissRequest(reason="误匹配").reason == "误匹配"


def test_scan_summary_fields():
    s = ScanSummary(scanned_keywords=3, new=10, updated=2, skipped=1, failed_keywords=0)
    dumped = s.model_dump()
    assert dumped == {
        "scanned_keywords": 3, "new": 10, "updated": 2, "skipped": 1, "failed_keywords": 0,
    }


def test_submit_summary_fields():
    s = SubmitSummary(submitted=5, failed=1, skipped=2)
    assert s.model_dump() == {"submitted": 5, "failed": 1, "skipped": 2}


def test_job_frame_shape():
    frame = JobFrame(
        job_id="abc-123", job_type="scan", stage="扫描外部库",
        current=10, total=50, done=False, error=None, summary=None,
        started_at="2026-05-19T00:00:00+00:00", finished_at=None,
    )
    assert frame.job_id == "abc-123"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/whitelist/test_schemas.py -v`
Expected: `ModuleNotFoundError: No module named 'app.schemas.whitelist'`

- [ ] **Step 3: 创建 schemas**

创建 `app/schemas/whitelist.py`：
```python
"""白名单批处理 API schemas。详见
docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4.4
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── 请求 ──────────────────────────────────────────────────────────────
class ScanJobRequest(BaseModel):
    tree_import_id: int
    keyword_entry_ids: list[int] | None = None
    per_keyword_limit: int = Field(default=10, ge=1, le=200)


class SubmitJobRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
    force_submit: bool = False


class DismissRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


# ── 汇总 ──────────────────────────────────────────────────────────────
class ScanSummary(BaseModel):
    scanned_keywords: int
    new: int
    updated: int
    skipped: int
    failed_keywords: int


class SubmitSummary(BaseModel):
    submitted: int
    failed: int
    skipped: int


# ── 进度帧 ────────────────────────────────────────────────────────────
class JobFrame(BaseModel):
    job_id: str
    job_type: Literal["scan", "submit"]
    stage: str
    current: int
    total: int
    done: bool
    error: str | None
    summary: dict | None
    started_at: str
    finished_at: str | None


class ActiveJobsResponse(BaseModel):
    scan: JobFrame | None
    submit: JobFrame | None


# ── 候选行 ────────────────────────────────────────────────────────────
class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_tid: int
    source_magnet: str
    source_title: str
    source_section: str | None
    source_detail_url: str | None
    matched_keyword_entry_id: int
    matched_keyword: str
    matched_alias: str | None
    match_score: float
    last_scanned_tree_import_id: int | None
    duplicate_status: str
    duplicate_reason: str | None
    matched_import_label: str | None
    target_path: str
    lifecycle_status: str
    magnet_task_id: int | None
    dismissed_at: datetime | None
    submitted_at: datetime | None
    failure_reason: str | None
    first_seen_at: datetime
    last_scanned_at: datetime


class CandidateListResponse(BaseModel):
    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/whitelist/test_schemas.py -v`
Expected: 7 PASS

- [ ] **Step 5: 提交**

```bash
git add app/schemas/whitelist.py tests/whitelist/test_schemas.py
git commit -m "feat: 添加白名单批处理 Pydantic schemas"
```

---

### Task 3: WhitelistCandidateService.scan 核心算法

**Files:**
- Create: `app/services/whitelist/__init__.py` (空文件)
- Create: `app/services/whitelist/candidate_service.py`
- Test: `tests/whitelist/test_candidate_service_scan.py`

- [ ] **Step 1: 写第一个失败测试 — 首轮扫描插入新候选**

创建空文件 `app/services/whitelist/__init__.py`。

创建 `tests/whitelist/test_candidate_service_scan.py`：
```python
"""WhitelistCandidateService.scan() 的单测。

设计要点：
- 同 (tid, magnet) 不同 keyword 各占一行
- 低成本状态（submitted/dismissed/task_exists）跳过，只刷 last_scanned_at
- 高成本状态（clear/duplicate_found）重新评估
- 每关键词一 commit；单关键词失败不阻断 job
"""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordEntry
from app.models.tree import TreeImport
from app.models.whitelist import WhitelistCandidate
from app.schemas.magnet_tasks import ArticleCandidateResponse
from app.services.whitelist.candidate_service import (
    DuplicateCheckResult,  # 重新导出
    WhitelistCandidateService,
)


def _make_entry(db, name, idx=1):
    e = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type="whitelist",
        status="active",
    )
    db.add(e)
    db.commit()
    return e


def _make_tree(db):
    t = TreeImport(source_filename="t", source_type="manual", status="completed")
    db.add(t)
    db.commit()
    return t


def _fake_article(tid, title="t", magnet=None, keyword="演员A"):
    return ArticleCandidateResponse(
        source_tid=tid,
        source_title=title,
        source_magnet=magnet or f"magnet:?xt=urn:btih:{tid}",
        source_detail_url=f"https://x/{tid}",
        source_section="release",
        source_category=None,
        source_sub_type=None,
        source_size=None,
        matched_keyword=keyword,
        matched_alias=None,
        match_score=0.9,
    )


def _make_service(db, *, candidates_per_entry: dict[int, list], dup_result):
    """返回 WhitelistCandidateService 实例，magnet_svc 是 mock。"""
    magnet_svc = MagicMock()
    def fake_build(*, keyword_entry, limit):
        return candidates_per_entry.get(keyword_entry.id, [])
    magnet_svc.build_candidates_for_keyword_entry.side_effect = fake_build
    magnet_svc._check_single_duplicate.return_value = dup_result
    magnet_svc._build_target_path.side_effect = lambda *, keyword_dir, source_title: f"/已整理/{keyword_dir}/{source_title}"
    return WhitelistCandidateService(db, magnet_svc=magnet_svc), magnet_svc


def test_scan_first_run_inserts_new_candidates(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    svc, _ = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(1), _fake_article(2)]},
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.new == 2
    assert summary.updated == 0
    rows = db_session.scalars(select(WhitelistCandidate)).all()
    assert len(rows) == 2
    assert all(r.lifecycle_status == "pending" for r in rows)
    assert all(r.duplicate_status == "clear" for r in rows)
    assert all(r.last_scanned_tree_import_id == tree.id for r in rows)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/whitelist/test_candidate_service_scan.py::test_scan_first_run_inserts_new_candidates -v`
Expected: `ImportError`

- [ ] **Step 3: 实现 scan() 最小版本**

创建 `app/services/whitelist/candidate_service.py`：
```python
"""白名单候选服务：扫描、提交、列表、丢弃、恢复。

依赖 MagnetDownloadService 的底层 API：
- build_candidates_for_keyword_entry
- _check_single_duplicate
- _build_target_path
- create_and_submit_tasks
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry
from app.models.whitelist import WhitelistCandidate
from app.schemas.magnet_tasks import DuplicateCheckItemRequest
from app.schemas.whitelist import ScanSummary, SubmitSummary
from app.services.tasks.organize_task_service import OrganizeTaskService

logger = logging.getLogger(__name__)


@dataclass
class DuplicateCheckResult:
    status: str
    reason: str | None
    matched_import_label: str | None
    matched_import_id: int | None = None
    matched_nodes: list = None  # type: ignore[assignment]


class WhitelistCandidateService:
    def __init__(self, db: Session, *, magnet_svc):
        self.db = db
        self.magnet_svc = magnet_svc

    def _load_whitelist_entries(self, keyword_entry_ids):
        stmt = (
            select(KeywordEntry)
            .where(KeywordEntry.keyword_type == "whitelist")
            .where(KeywordEntry.status == "active")
            .order_by(KeywordEntry.id.asc())
        )
        if keyword_entry_ids:
            stmt = stmt.where(KeywordEntry.id.in_(keyword_entry_ids))
        entries = list(self.db.scalars(stmt).all())
        if not entries:
            raise ValueError("未找到任何 active 白名单关键词")
        return entries

    def scan(
        self, *,
        tree_import_id: int,
        keyword_entry_ids: list[int] | None,
        per_keyword_limit: int,
        progress_cb: Callable[[str, int, int], None],
    ) -> ScanSummary:
        entries = self._load_whitelist_entries(keyword_entry_ids)
        directory_names = OrganizeTaskService._build_keyword_directory_names(entries)
        progress_cb("加载关键词", 0, len(entries))

        new = updated = skipped = failed = 0

        for idx, entry in enumerate(entries):
            progress_cb("扫描外部库", idx + 1, len(entries))
            try:
                raw_candidates = self.magnet_svc.build_candidates_for_keyword_entry(
                    keyword_entry=entry, limit=per_keyword_limit,
                )
                for cand in raw_candidates:
                    existing = self.db.scalar(select(WhitelistCandidate).where(
                        WhitelistCandidate.source_tid == cand.source_tid,
                        WhitelistCandidate.source_magnet == cand.source_magnet,
                        WhitelistCandidate.matched_keyword_entry_id == entry.id,
                    ))
                    # 低成本状态：刷新 last_scanned_at 但不动其它字段
                    if existing and existing.lifecycle_status in {"submitted", "dismissed"}:
                        existing.last_scanned_at = datetime.now(UTC)
                        skipped += 1
                        continue
                    if existing and existing.duplicate_status == "task_exists":
                        existing.last_scanned_at = datetime.now(UTC)
                        skipped += 1
                        continue

                    # clear / duplicate_found / 新候选 → 重新评估 duplicate
                    dup_input = DuplicateCheckItemRequest(
                        source_tid=cand.source_tid,
                        source_title=cand.source_title,
                        source_magnet=cand.source_magnet,
                        matched_keyword=cand.matched_keyword,
                        matched_alias=cand.matched_alias,
                    )
                    dup = self.magnet_svc._check_single_duplicate(
                        dup_input, tree_import_id=tree_import_id,
                    )
                    target_path = self.magnet_svc._build_target_path(
                        keyword_dir=directory_names[entry.id],
                        source_title=cand.source_title,
                    )

                    if existing is None:
                        self.db.add(WhitelistCandidate(
                            source_tid=cand.source_tid,
                            source_magnet=cand.source_magnet,
                            source_title=cand.source_title,
                            source_section=cand.source_section,
                            source_detail_url=cand.source_detail_url,
                            matched_keyword_entry_id=entry.id,
                            matched_keyword=cand.matched_keyword,
                            matched_alias=cand.matched_alias,
                            match_score=cand.match_score,
                            last_scanned_tree_import_id=tree_import_id,
                            duplicate_status=dup.status,
                            duplicate_reason=dup.reason,
                            matched_import_label=dup.matched_import_label,
                            target_path=target_path,
                            lifecycle_status="pending",
                        ))
                        new += 1
                    else:
                        existing.duplicate_status = dup.status
                        existing.duplicate_reason = dup.reason
                        existing.matched_import_label = dup.matched_import_label
                        existing.target_path = target_path
                        existing.last_scanned_tree_import_id = tree_import_id
                        existing.last_scanned_at = datetime.now(UTC)
                        updated += 1
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("scan 关键词 %s 失败", entry.canonical_name)
                failed += 1

        return ScanSummary(
            scanned_keywords=len(entries),
            new=new, updated=updated, skipped=skipped, failed_keywords=failed,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/whitelist/test_candidate_service_scan.py::test_scan_first_run_inserts_new_candidates -v`
Expected: 1 PASS

- [ ] **Step 5: 添加同 magnet 多关键词测试**

追加到 `tests/whitelist/test_candidate_service_scan.py`：
```python
def test_scan_two_keywords_match_same_magnet_produces_two_rows(db_session):
    entry_a = _make_entry(db_session, "演员A")
    entry_b = _make_entry(db_session, "演员B")
    tree = _make_tree(db_session)
    svc, _ = _make_service(
        db_session,
        candidates_per_entry={
            entry_a.id: [_fake_article(7, keyword="演员A")],
            entry_b.id: [_fake_article(7, keyword="演员B")],
        },
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry_a.id, entry_b.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.new == 2
    rows = db_session.scalars(select(WhitelistCandidate)).all()
    assert len(rows) == 2
    assert {r.matched_keyword_entry_id for r in rows} == {entry_a.id, entry_b.id}
```

- [ ] **Step 6: 运行测试通过**

Run: `pytest tests/whitelist/test_candidate_service_scan.py -v`
Expected: 2 PASS

- [ ] **Step 7: 添加 skip submitted / dismissed 测试**

```python
def test_scan_second_run_skips_submitted_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    earlier = datetime.now(UTC) - timedelta(days=1)
    db_session.add(WhitelistCandidate(
        source_tid=42, source_magnet="magnet:?xt=urn:btih:42",
        source_title="老资源", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="submitted",
        last_scanned_at=earlier,
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(42)]},
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry.id],
        per_keyword_limit=10,
        progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    assert summary.new == 0
    assert summary.updated == 0
    magnet_svc._check_single_duplicate.assert_not_called()

    row = db_session.scalar(select(WhitelistCandidate))
    assert row.lifecycle_status == "submitted"
    assert row.last_scanned_at > earlier


def test_scan_second_run_skips_dismissed_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    earlier = datetime.now(UTC) - timedelta(days=1)
    db_session.add(WhitelistCandidate(
        source_tid=99, source_magnet="magnet:?xt=urn:btih:99",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="dismissed",
        last_scanned_at=earlier,
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(99)]},
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    summary = svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    magnet_svc._check_single_duplicate.assert_not_called()
    row = db_session.scalar(select(WhitelistCandidate))
    assert row.last_scanned_at > earlier


def test_scan_skips_task_exists_and_updates_last_scanned_at(db_session):
    entry = _make_entry(db_session, "演员A")
    tree = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=11, source_magnet="magnet:?xt=urn:btih:11",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name,
        duplicate_status="task_exists", target_path="/x",
        lifecycle_status="pending",
    ))
    db_session.commit()
    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(11)]},
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    summary = svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.skipped == 1
    magnet_svc._check_single_duplicate.assert_not_called()
```

- [ ] **Step 8: 运行通过**

Run: `pytest tests/whitelist/test_candidate_service_scan.py -v`
Expected: 5 PASS

- [ ] **Step 9: 添加 re-evaluate + 失败回滚 + target_path 更新测试**

```python
def test_scan_re_evaluates_clear_status(db_session):
    """已存在 clear 候选，重扫应重新调 _check_single_duplicate。"""
    entry = _make_entry(db_session, "演员A")
    tree_a = _make_tree(db_session)
    tree_b = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=5, source_magnet="magnet:?xt=urn:btih:5",
        source_title="t", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/x", lifecycle_status="pending",
        last_scanned_tree_import_id=tree_a.id,
    ))
    db_session.commit()

    svc, magnet_svc = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(5)]},
        dup_result=DuplicateCheckResult(
            status="duplicate_found", reason="本地命中",
            matched_import_label=f"#{tree_b.id}",
        ),
    )
    summary = svc.scan(
        tree_import_id=tree_b.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.updated == 1
    magnet_svc._check_single_duplicate.assert_called_once()
    row = db_session.scalar(select(WhitelistCandidate))
    assert row.duplicate_status == "duplicate_found"
    assert row.last_scanned_tree_import_id == tree_b.id


def test_scan_keyword_failure_does_not_abort_job(db_session):
    entry_ok = _make_entry(db_session, "OK")
    entry_bad = _make_entry(db_session, "BAD")
    tree = _make_tree(db_session)

    magnet_svc = MagicMock()
    def fake_build(*, keyword_entry, limit):
        if keyword_entry.id == entry_bad.id:
            raise RuntimeError("外部库挂了")
        return [_fake_article(1)]
    magnet_svc.build_candidates_for_keyword_entry.side_effect = fake_build
    magnet_svc._check_single_duplicate.return_value = DuplicateCheckResult(
        status="clear", reason=None, matched_import_label=None,
    )
    magnet_svc._build_target_path.side_effect = lambda *, keyword_dir, source_title: "/x"
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.scan(
        tree_import_id=tree.id,
        keyword_entry_ids=[entry_ok.id, entry_bad.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    assert summary.new == 1
    assert summary.failed_keywords == 1
    assert summary.scanned_keywords == 2


def test_target_path_recomputed_when_keyword_renamed_between_scans(db_session):
    entry = _make_entry(db_session, "原名")
    tree = _make_tree(db_session)
    db_session.add(WhitelistCandidate(
        source_tid=3, source_magnet="magnet:?xt=urn:btih:3",
        source_title="r", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, duplicate_status="clear",
        target_path="/已整理/原名/r", lifecycle_status="pending",
    ))
    db_session.commit()

    entry.canonical_name = "新名"
    db_session.commit()

    svc, _ = _make_service(
        db_session,
        candidates_per_entry={entry.id: [_fake_article(3, title="r")]},
        dup_result=DuplicateCheckResult(status="clear", reason=None, matched_import_label=None),
    )
    svc.scan(
        tree_import_id=tree.id, keyword_entry_ids=[entry.id],
        per_keyword_limit=10, progress_cb=lambda *a: None,
    )
    row = db_session.scalar(select(WhitelistCandidate))
    assert "新名" in row.target_path
```

- [ ] **Step 10: 运行通过**

Run: `pytest tests/whitelist/test_candidate_service_scan.py -v`
Expected: 8 PASS

- [ ] **Step 11: 提交**

```bash
git add app/services/whitelist/__init__.py app/services/whitelist/candidate_service.py tests/whitelist/test_candidate_service_scan.py
git commit -m "feat: WhitelistCandidateService.scan() — 跨次扫描去重 + 状态复用"
```

---

### Task 4: WhitelistCandidateService.submit_selected

**Files:**
- Modify: `app/services/whitelist/candidate_service.py` (append submit_selected)
- Test: `tests/whitelist/test_candidate_service_submit.py`

- [ ] **Step 1: 写第一个失败测试 — 单条提交成功并关联**

创建 `tests/whitelist/test_candidate_service_submit.py`：
```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordEntry
from app.models.tasks import MagnetDownloadTask
from app.models.whitelist import WhitelistCandidate
from app.services.whitelist.candidate_service import WhitelistCandidateService


def _make_entry(db, name="演员A"):
    e = KeywordEntry(
        canonical_name=name, canonical_name_normalized=name.lower(),
        keyword_type="whitelist", status="active",
    )
    db.add(e)
    db.commit()
    return e


def _make_candidate(db, entry, *, lifecycle="pending", tid=1, score=0.9):
    c = WhitelistCandidate(
        source_tid=tid, source_magnet=f"magnet:?xt=urn:btih:{tid}",
        source_title=f"r{tid}", matched_keyword_entry_id=entry.id,
        matched_keyword=entry.canonical_name, match_score=score,
        duplicate_status="clear", target_path=f"/已整理/{entry.canonical_name}/r{tid}",
        lifecycle_status=lifecycle,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_task(tid, status):
    """构造一个 MagnetDownloadTask 实例（不进 DB，模拟 create_and_submit_tasks 返回）。"""
    t = MagnetDownloadTask(
        source_tid=tid, source_title=f"r{tid}", source_magnet=f"magnet:?xt=urn:btih:{tid}",
        duplicate_status="clear", status=status,
    )
    return t


def test_submit_creates_magnet_task_and_links(db_session):
    entry = _make_entry(db_session)
    cand = _make_candidate(db_session, entry)

    magnet_svc = MagicMock()
    submitted = _make_task(1, "submitted")
    submitted.id = 999  # 模拟数据库分配的 id
    magnet_svc.create_and_submit_tasks.return_value = [submitted]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[cand.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    assert summary.submitted == 1
    assert summary.failed == 0

    db_session.refresh(cand)
    assert cand.lifecycle_status == "submitted"
    assert cand.magnet_task_id == 999
    assert cand.submitted_at is not None
```

- [ ] **Step 2: 运行失败**

Run: `pytest tests/whitelist/test_candidate_service_submit.py::test_submit_creates_magnet_task_and_links -v`
Expected: `AttributeError: 'WhitelistCandidateService' object has no attribute 'submit_selected'`

- [ ] **Step 3: 实现 submit_selected**

追加到 `app/services/whitelist/candidate_service.py`：

```python
    def submit_selected(
        self, *,
        candidate_ids: list[int],
        force_submit: bool,
        progress_cb: Callable[[str, int, int], None],
    ) -> SubmitSummary:
        if not candidate_ids:
            raise ValueError("未选择有效的候选项")
        candidates = list(self.db.scalars(
            select(WhitelistCandidate).where(WhitelistCandidate.id.in_(candidate_ids))
        ).all())
        if not candidates:
            raise ValueError("未选择有效的候选项")

        submitted = failed = skipped = 0
        for idx, cand in enumerate(candidates):
            progress_cb("提交到 115", idx, len(candidates))
            # 防御并发：scan 可能并行改写过 cand，重读最新状态
            self.db.refresh(cand)
            if cand.lifecycle_status != "pending":
                skipped += 1
                continue
            try:
                task = self.magnet_svc.create_and_submit_tasks(
                    items=[_candidate_to_create_item(cand)],
                    force_submit=force_submit,
                    tree_import_id=cand.last_scanned_tree_import_id,
                )[0]
                cand.magnet_task_id = task.id
                if task.status == "submitted":
                    cand.lifecycle_status = "submitted"
                    cand.submitted_at = datetime.now(UTC)
                    submitted += 1
                elif task.status == "duplicate_skipped":
                    cand.lifecycle_status = "submitted"  # 已存在视同已处理
                    cand.submitted_at = datetime.now(UTC)
                    skipped += 1
                else:  # "failed"
                    cand.lifecycle_status = "failed"
                    cand.failure_reason = task.failure_reason
                    failed += 1
                self.db.commit()
            except Exception as exc:
                # 关键：异常可能发生在 create_and_submit_tasks 内部的 flush/commit；
                # session 已 failed，必须 rollback 才能继续写 cand
                self.db.rollback()
                cand = self.db.merge(cand)
                cand.lifecycle_status = "failed"
                cand.failure_reason = str(exc)
                self.db.commit()
                failed += 1

        return SubmitSummary(submitted=submitted, failed=failed, skipped=skipped)


def _candidate_to_create_item(cand: WhitelistCandidate):
    """把 WhitelistCandidate 转成 MagnetTaskCreateItem。"""
    from app.schemas.magnet_tasks import MagnetTaskCreateItem
    return MagnetTaskCreateItem(
        source_tid=cand.source_tid,
        source_title=cand.source_title,
        source_magnet=cand.source_magnet,
        source_detail_url=cand.source_detail_url,
        source_section=cand.source_section,
        matched_keyword=cand.matched_keyword,
        matched_alias=cand.matched_alias,
        match_score=cand.match_score,
        keyword_entry_id=cand.matched_keyword_entry_id,
        target_path=cand.target_path,
    )
```

- [ ] **Step 4: 运行单测通过**

Run: `pytest tests/whitelist/test_candidate_service_submit.py::test_submit_creates_magnet_task_and_links -v`
Expected: 1 PASS

- [ ] **Step 5: 添加其余测试**

追加到 `tests/whitelist/test_candidate_service_submit.py`：
```python
def test_submit_handles_single_failure_continues(db_session):
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    failed = _make_task(1, "failed"); failed.id = 11; failed.failure_reason = "boom"
    submitted = _make_task(2, "submitted"); submitted.id = 22
    magnet_svc.create_and_submit_tasks.side_effect = [[failed], [submitted]]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False, progress_cb=lambda *a: None,
    )
    assert summary.submitted == 1
    assert summary.failed == 1
    db_session.refresh(c1); db_session.refresh(c2)
    assert c1.lifecycle_status == "failed"
    assert c1.failure_reason == "boom"
    assert c2.lifecycle_status == "submitted"


def test_submit_rolls_back_on_create_and_submit_failure(db_session):
    """模拟 create_and_submit_tasks 内部抛异常（session 已 failed 状态）"""
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    success = _make_task(2, "submitted"); success.id = 22

    call_count = {"n": 0}
    def fake_create(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 模拟内部 flush/commit 把 session 标 failed
            db_session.execute(__import__("sqlalchemy").text("SELECT * FROM nonexistent_xyz"))
        return [success]
    magnet_svc.create_and_submit_tasks.side_effect = fake_create
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False, progress_cb=lambda *a: None,
    )
    # c1 失败但 c2 必须能继续 → 验证 rollback 路径生效
    assert summary.submitted == 1
    assert summary.failed == 1


def test_submit_skips_non_pending_candidates(db_session):
    entry = _make_entry(db_session)
    c_dis = _make_candidate(db_session, entry, tid=1, lifecycle="dismissed")
    c_sub = _make_candidate(db_session, entry, tid=2, lifecycle="submitted")

    magnet_svc = MagicMock()
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)
    summary = svc.submit_selected(
        candidate_ids=[c_dis.id, c_sub.id], force_submit=False,
        progress_cb=lambda *a: None,
    )
    assert summary.skipped == 2
    assert summary.submitted == 0
    magnet_svc.create_and_submit_tasks.assert_not_called()


def test_submit_uses_none_tree_import_id_when_candidate_never_scanned(db_session):
    """last_scanned_tree_import_id 为 None 时 create_and_submit_tasks 收到 None。"""
    entry = _make_entry(db_session)
    cand = _make_candidate(db_session, entry)
    cand.last_scanned_tree_import_id = None
    db_session.commit()

    magnet_svc = MagicMock()
    submitted = _make_task(1, "submitted"); submitted.id = 1
    magnet_svc.create_and_submit_tasks.return_value = [submitted]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)
    svc.submit_selected(
        candidate_ids=[cand.id], force_submit=False, progress_cb=lambda *a: None,
    )
    call = magnet_svc.create_and_submit_tasks.call_args
    assert call.kwargs["tree_import_id"] is None


def test_submit_refreshes_cand_before_acting(db_session):
    """循环开始后 cand 在外部被改成 dismissed，submit 应跳过。"""
    entry = _make_entry(db_session)
    c1 = _make_candidate(db_session, entry, tid=1)
    c2 = _make_candidate(db_session, entry, tid=2)

    magnet_svc = MagicMock()
    submitted = _make_task(2, "submitted"); submitted.id = 22
    magnet_svc.create_and_submit_tasks.return_value = [submitted]
    svc = WhitelistCandidateService(db_session, magnet_svc=magnet_svc)

    # 模拟并发：第二轮 progress_cb 触发后，把 c2 改 dismissed
    def progress(stage, current, total):
        if stage == "提交到 115" and current == 1:
            from sqlalchemy import update
            db_session.execute(
                update(WhitelistCandidate)
                .where(WhitelistCandidate.id == c2.id)
                .values(lifecycle_status="dismissed")
            )
            db_session.commit()

    summary = svc.submit_selected(
        candidate_ids=[c1.id, c2.id], force_submit=False, progress_cb=progress,
    )
    # c1 提交成功，c2 被并发改成 dismissed，skipped 计数 +1
    assert summary.submitted == 1
    assert summary.skipped == 1
```

- [ ] **Step 6: 运行所有测试通过**

Run: `pytest tests/whitelist/test_candidate_service_submit.py -v`
Expected: 6 PASS

- [ ] **Step 7: 提交**

```bash
git add app/services/whitelist/candidate_service.py tests/whitelist/test_candidate_service_submit.py
git commit -m "feat: WhitelistCandidateService.submit_selected — 失败跳过 + 显式 rollback + refresh 防并发"
```

---

### Task 5: WhitelistCandidateService 辅助方法（list / dismiss / restore）

**Files:**
- Modify: `app/services/whitelist/candidate_service.py`
- Test: `tests/whitelist/test_candidate_service_list_dismiss.py`

- [ ] **Step 1: 写 list_candidates 测试**

创建 `tests/whitelist/test_candidate_service_list_dismiss.py`：
```python
from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.keywords import KeywordEntry
from app.models.whitelist import WhitelistCandidate
from app.services.whitelist.candidate_service import WhitelistCandidateService


def _make_entry(db, name="A"):
    e = KeywordEntry(
        canonical_name=name, canonical_name_normalized=name.lower(),
        keyword_type="whitelist", status="active",
    )
    db.add(e); db.commit()
    return e


def _make_cand(db, entry, *, tid, lifecycle="pending", dup="clear", score=0.5):
    c = WhitelistCandidate(
        source_tid=tid, source_magnet=f"m{tid}", source_title=f"r{tid}",
        matched_keyword_entry_id=entry.id, matched_keyword=entry.canonical_name,
        match_score=score, duplicate_status=dup, target_path="/x",
        lifecycle_status=lifecycle,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_list_candidates_filters_by_lifecycle(db_session):
    e = _make_entry(db_session)
    _make_cand(db_session, e, tid=1, lifecycle="pending")
    _make_cand(db_session, e, tid=2, lifecycle="submitted")
    _make_cand(db_session, e, tid=3, lifecycle="dismissed")

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status="pending", matched_keyword_entry_id=None,
        duplicate_status=None, search=None, page=1, page_size=100,
    )
    assert total == 1
    assert items[0].source_tid == 1


def test_list_candidates_filters_by_keyword_and_duplicate(db_session):
    e1 = _make_entry(db_session, "A")
    e2 = _make_entry(db_session, "B")
    _make_cand(db_session, e1, tid=1, dup="clear")
    _make_cand(db_session, e1, tid=2, dup="duplicate_found")
    _make_cand(db_session, e2, tid=3, dup="clear")

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=e1.id,
        duplicate_status="clear", search=None, page=1, page_size=100,
    )
    assert total == 1
    assert items[0].source_tid == 1


def test_list_candidates_paginates(db_session):
    e = _make_entry(db_session)
    for i in range(25):
        _make_cand(db_session, e, tid=i)

    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    items, total = svc.list_candidates(
        lifecycle_status=None, matched_keyword_entry_id=None,
        duplicate_status=None, search=None, page=2, page_size=10,
    )
    assert total == 25
    assert len(items) == 10


def test_dismiss_pending_candidate(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="pending")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.dismiss(candidate_id=c.id, reason="误匹配")
    db_session.refresh(c)
    assert c.lifecycle_status == "dismissed"
    assert c.dismissed_at is not None


def test_dismiss_submitted_candidate_raises(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="submitted")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="已提交"):
        svc.dismiss(candidate_id=c.id, reason=None)


def test_restore_dismissed_candidate(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="dismissed")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.restore(candidate_id=c.id)
    db_session.refresh(c)
    assert c.lifecycle_status == "pending"
    assert c.dismissed_at is None


def test_restore_failed_candidate(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="failed")
    c.failure_reason = "old error"
    db_session.commit()
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    svc.restore(candidate_id=c.id)
    db_session.refresh(c)
    assert c.lifecycle_status == "pending"
    assert c.failure_reason is None


def test_restore_submitted_candidate_raises(db_session):
    e = _make_entry(db_session)
    c = _make_cand(db_session, e, tid=1, lifecycle="submitted")
    svc = WhitelistCandidateService(db_session, magnet_svc=MagicMock())
    with pytest.raises(ValueError, match="已提交"):
        svc.restore(candidate_id=c.id)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/whitelist/test_candidate_service_list_dismiss.py -v`
Expected: 失败（方法不存在）

- [ ] **Step 3: 实现 list / dismiss / restore**

追加到 `app/services/whitelist/candidate_service.py`（在 class 内）：

```python
    def list_candidates(
        self, *,
        lifecycle_status: str | None,
        matched_keyword_entry_id: int | None,
        duplicate_status: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[WhitelistCandidate], int]:
        from sqlalchemy import func as _func, or_
        base = select(WhitelistCandidate)
        if lifecycle_status:
            base = base.where(WhitelistCandidate.lifecycle_status == lifecycle_status)
        if matched_keyword_entry_id:
            base = base.where(WhitelistCandidate.matched_keyword_entry_id == matched_keyword_entry_id)
        if duplicate_status:
            base = base.where(WhitelistCandidate.duplicate_status == duplicate_status)
        if search:
            pattern = f"%{search}%"
            base = base.where(or_(
                WhitelistCandidate.source_title.ilike(pattern),
                WhitelistCandidate.matched_keyword.ilike(pattern),
            ))

        total = self.db.scalar(
            select(_func.count()).select_from(base.subquery())
        ) or 0
        items = list(self.db.scalars(
            base.order_by(WhitelistCandidate.match_score.desc(), WhitelistCandidate.id.desc())
            .limit(page_size).offset((page - 1) * page_size)
        ).all())
        return items, total

    def dismiss(self, *, candidate_id: int, reason: str | None) -> WhitelistCandidate:
        cand = self.db.get(WhitelistCandidate, candidate_id)
        if cand is None:
            raise LookupError("候选不存在")
        if cand.lifecycle_status == "submitted":
            raise ValueError("已提交的候选不能丢弃")
        cand.lifecycle_status = "dismissed"
        cand.dismissed_at = datetime.now(UTC)
        self.db.commit()
        return cand

    def restore(self, *, candidate_id: int) -> WhitelistCandidate:
        cand = self.db.get(WhitelistCandidate, candidate_id)
        if cand is None:
            raise LookupError("候选不存在")
        if cand.lifecycle_status == "submitted":
            raise ValueError("已提交的候选不能 restore")
        if cand.lifecycle_status not in {"dismissed", "failed"}:
            raise ValueError(f"当前状态 {cand.lifecycle_status} 不能 restore")
        cand.lifecycle_status = "pending"
        cand.dismissed_at = None
        cand.failure_reason = None
        self.db.commit()
        return cand
```

- [ ] **Step 4: 运行测试通过**

Run: `pytest tests/whitelist/test_candidate_service_list_dismiss.py -v`
Expected: 8 PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/whitelist/candidate_service.py tests/whitelist/test_candidate_service_list_dismiss.py
git commit -m "feat: WhitelistCandidateService.list_candidates / dismiss / restore"
```

---

### Task 6: HTTP 路由 + Job 编排（含 sweeper）

**Files:**
- Create: `app/api/routes/whitelist_batch.py`
- Modify: `app/main.py:63-84` (import + register)
- Modify: `app/main.py:23-56` (lifespan 启动 sweeper)
- Test: `tests/whitelist/test_whitelist_batch_routes.py`

- [ ] **Step 1: 写第一个路由测试 — POST /scan-jobs 立即返回 + 第二次返回 409**

创建 `tests/whitelist/test_whitelist_batch_routes.py`：
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
from app.models import whitelist as _wl  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", "/tmp/test_auth_wb.json")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")

    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api.routes import whitelist_batch as _wb
    from app.api import deps

    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db

    # 重置模块级状态
    _wb._jobs.clear()
    if _wb._scan_lock.locked():
        _wb._scan_lock = asyncio.Lock()
    if _wb._submit_lock.locked():
        _wb._submit_lock = asyncio.Lock()

    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def _seed_keyword(client):
    """通过 SQLAlchemy 直接插入测试关键词，返回 id。"""
    from app.api.routes import whitelist_batch as _wb
    from app.models.keywords import KeywordEntry
    sess = next(_wb.get_db_for_test_only()) if hasattr(_wb, "get_db_for_test_only") else None
    # 用 client 的依赖 override
    db = next(client.app.dependency_overrides[
        list(client.app.dependency_overrides)[0]]())
    e = KeywordEntry(
        canonical_name="演员A", canonical_name_normalized="演员a",
        keyword_type="whitelist", status="active",
    )
    db.add(e); db.commit()
    return e.id


def test_scan_jobs_returns_409_when_scan_locked(client, monkeypatch):
    from app.api.routes import whitelist_batch as _wb
    monkeypatch.setattr(_wb._scan_lock, "locked", lambda: True)

    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 409


def test_submit_jobs_returns_409_when_submit_locked(client, monkeypatch):
    from app.api.routes import whitelist_batch as _wb
    monkeypatch.setattr(_wb._submit_lock, "locked", lambda: True)

    resp = client.post("/whitelist-batch/submit-jobs", json={
        "candidate_ids": [1], "force_submit": False,
    })
    assert resp.status_code == 409


def test_job_id_is_uuid_not_sequential_integer(client, monkeypatch):
    """job_id 应是 UUID 字符串（含连字符），不是递增整数。"""
    from app.api.routes import whitelist_batch as _wb
    import uuid as _uuid

    async def fake_run(job_id, payload):
        _wb._jobs[job_id]["done"] = True

    monkeypatch.setattr(_wb, "_run_scan_job", fake_run)
    resp = client.post("/whitelist-batch/scan-jobs", json={
        "tree_import_id": 1, "per_keyword_limit": 5,
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    _uuid.UUID(job_id)  # 不抛即为合法 uuid


def test_sse_progress_streams_done_frame(client):
    from app.api.routes import whitelist_batch as _wb
    from datetime import datetime, UTC

    jid = "test-job-1"
    _wb._jobs[jid] = {
        "job_id": jid, "job_type": "scan",
        "stage": "完成", "current": 5, "total": 5,
        "done": True, "error": None,
        "summary": {"scanned_keywords": 1, "new": 5, "updated": 0, "skipped": 0, "failed_keywords": 0},
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    with client.stream("GET", f"/whitelist-batch/jobs/{jid}/progress") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        frames = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[len("data:"):].strip()))
                if len(frames) >= 1:
                    break
    assert frames[0]["done"] is True


def test_sse_progress_returns_error_for_unknown_job(client):
    with client.stream("GET", "/whitelist-batch/jobs/no-such-job/progress") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                assert payload.get("error") == "not found"
                break


def test_get_active_jobs_returns_running_jobs(client):
    from app.api.routes import whitelist_batch as _wb
    from datetime import datetime, UTC

    _wb._jobs["scan-running"] = {
        "job_id": "scan-running", "job_type": "scan", "stage": "扫描外部库",
        "current": 1, "total": 10, "done": False, "error": None, "summary": None,
        "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
    }
    resp = client.get("/whitelist-batch/jobs/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan"] is not None
    assert data["scan"]["job_id"] == "scan-running"
    assert data["submit"] is None


def test_dismiss_then_restore_round_trip(client):
    """dismiss → restore；用 ORM 直接插一行候选。"""
    from sqlalchemy.orm import Session
    from app import main as _main
    from app.api import deps

    db_factory = client.app.dependency_overrides[deps.get_db]
    sess: Session = next(db_factory())
    try:
        from app.models.keywords import KeywordEntry
        from app.models.whitelist import WhitelistCandidate
        e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                         keyword_type="whitelist", status="active")
        sess.add(e); sess.commit()
        c = WhitelistCandidate(
            source_tid=1, source_magnet="m", source_title="t",
            matched_keyword_entry_id=e.id, matched_keyword="A",
            duplicate_status="clear", target_path="/x", lifecycle_status="pending",
        )
        sess.add(c); sess.commit(); cid = c.id
    finally:
        sess.close()

    resp = client.post(f"/whitelist-batch/candidates/{cid}/dismiss", json={"reason": "误匹配"})
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "dismissed"

    resp = client.post(f"/whitelist-batch/candidates/{cid}/restore")
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "pending"


def test_dismiss_submitted_candidate_returns_400(client):
    from app.api import deps
    db_factory = client.app.dependency_overrides[deps.get_db]
    sess = next(db_factory())
    try:
        from app.models.keywords import KeywordEntry
        from app.models.whitelist import WhitelistCandidate
        e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                         keyword_type="whitelist", status="active")
        sess.add(e); sess.commit()
        c = WhitelistCandidate(
            source_tid=1, source_magnet="m", source_title="t",
            matched_keyword_entry_id=e.id, matched_keyword="A",
            duplicate_status="clear", target_path="/x", lifecycle_status="submitted",
        )
        sess.add(c); sess.commit(); cid = c.id
    finally:
        sess.close()

    resp = client.post(f"/whitelist-batch/candidates/{cid}/dismiss", json={})
    assert resp.status_code == 400


def test_list_candidates_filters_by_lifecycle(client):
    from app.api import deps
    db_factory = client.app.dependency_overrides[deps.get_db]
    sess = next(db_factory())
    try:
        from app.models.keywords import KeywordEntry
        from app.models.whitelist import WhitelistCandidate
        e = KeywordEntry(canonical_name="A", canonical_name_normalized="a",
                         keyword_type="whitelist", status="active")
        sess.add(e); sess.commit()
        for tid, lc in [(1, "pending"), (2, "submitted"), (3, "dismissed")]:
            sess.add(WhitelistCandidate(
                source_tid=tid, source_magnet=f"m{tid}", source_title=f"t{tid}",
                matched_keyword_entry_id=e.id, matched_keyword="A",
                duplicate_status="clear", target_path="/x", lifecycle_status=lc,
            ))
        sess.commit()
    finally:
        sess.close()

    resp = client.get("/whitelist-batch/candidates?lifecycle_status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["source_tid"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/whitelist/test_whitelist_batch_routes.py -v`
Expected: 失败（路由 module 不存在）

- [ ] **Step 3: 创建路由模块**

创建 `app/api/routes/whitelist_batch.py`：
```python
"""白名单批处理路由：扫描 / 提交 / 候选列表 / 丢弃 / 恢复 + SSE 进度。

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db, get_source_article_db
from app.schemas.whitelist import (
    ActiveJobsResponse,
    CandidateListResponse,
    CandidateResponse,
    DismissRequest,
    JobFrame,
    ScanJobRequest,
    SubmitJobRequest,
)
from app.services.magnet_download_service import MagnetDownloadService
from app.services.whitelist.candidate_service import WhitelistCandidateService

router = APIRouter(prefix="/whitelist-batch", tags=["whitelist-batch"])
logger = logging.getLogger(__name__)

# 并发保护：scan 和 submit 各一把，互不阻塞但同类型同时只跑一个
_scan_lock = asyncio.Lock()
_submit_lock = asyncio.Lock()
# job_id 用 uuid4，避免重启后 itertools.count 复用 id 与陈旧前端订阅冲突
_jobs: dict[str, dict] = {}
_JOB_RETENTION_SECONDS = 600   # done 后 10 分钟可被 SSE/active 查到，再由 sweeper 清理


def _new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "job_type": job_type,
        "stage": "等待开始",
        "current": 0, "total": 0,
        "done": False, "error": None,
        "summary": None,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
    }
    return job_id


# ── Scan job ────────────────────────────────────────────────────────────
@router.post("/scan-jobs")
async def start_scan_job(
    payload: ScanJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _scan_lock.locked():
        raise HTTPException(409, "已有扫描任务在运行，请等待完成")
    job_id = _new_job("scan")
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_scan_job(job_id: str, payload: ScanJobRequest) -> None:
    async with _scan_lock:
        await asyncio.to_thread(_blocking_scan, job_id, payload)


def _blocking_scan(job_id: str, payload: ScanJobRequest) -> None:
    from app.db.session import SessionLocal
    from app.services.source_article_db import SourceArticleDatabaseService
    from app.services.client_115.client import Real115Client

    session = SessionLocal()
    try:
        def cb(stage, current, total):
            _jobs[job_id].update(stage=stage, current=current, total=total)
        magnet_svc = MagnetDownloadService(
            session,
            article_db=SourceArticleDatabaseService(),
            client_115=Real115Client(),
        )
        svc = WhitelistCandidateService(session, magnet_svc=magnet_svc)
        summary = svc.scan(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            progress_cb=cb,
        )
        _jobs[job_id].update(stage="完成", summary=summary.model_dump(), done=True)
    except Exception as exc:
        logger.exception("scan job %s 失败", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()


# ── Submit job ──────────────────────────────────────────────────────────
@router.post("/submit-jobs")
async def start_submit_job(
    payload: SubmitJobRequest,
    db: Session = Depends(get_db),
) -> dict:
    if _submit_lock.locked():
        raise HTTPException(409, "已有提交任务在运行，请等待完成")
    job_id = _new_job("submit")
    asyncio.create_task(_run_submit_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}


async def _run_submit_job(job_id: str, payload: SubmitJobRequest) -> None:
    async with _submit_lock:
        await asyncio.to_thread(_blocking_submit, job_id, payload)


def _blocking_submit(job_id: str, payload: SubmitJobRequest) -> None:
    from app.db.session import SessionLocal
    from app.services.source_article_db import SourceArticleDatabaseService
    from app.services.client_115.client import Real115Client

    session = SessionLocal()
    try:
        def cb(stage, current, total):
            _jobs[job_id].update(stage=stage, current=current, total=total)
        magnet_svc = MagnetDownloadService(
            session,
            article_db=SourceArticleDatabaseService(),
            client_115=Real115Client(),
        )
        svc = WhitelistCandidateService(session, magnet_svc=magnet_svc)
        summary = svc.submit_selected(
            candidate_ids=payload.candidate_ids,
            force_submit=payload.force_submit,
            progress_cb=cb,
        )
        _jobs[job_id].update(stage="完成", summary=summary.model_dump(), done=True)
    except Exception as exc:
        logger.exception("submit job %s 失败", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()


# ── SSE 进度 + active jobs ──────────────────────────────────────────────
@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: str) -> StreamingResponse:
    """SSE 每秒一帧；空闲时 20s 一帧 keepalive；done 后再推一帧并断开。
    不在此处 pop，由 _sweep_jobs 后台清理。
    """
    async def event_stream():
        last_emit = asyncio.get_event_loop().time()
        sent_done_once = False
        while True:
            state = _jobs.get(job_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            last_emit = asyncio.get_event_loop().time()
            if state["done"]:
                if sent_done_once:
                    break
                sent_done_once = True
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(1)
            if asyncio.get_event_loop().time() - last_emit >= 20:
                yield ": keepalive\n\n"
                last_emit = asyncio.get_event_loop().time()
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/jobs/active", response_model=ActiveJobsResponse)
async def active_jobs() -> ActiveJobsResponse:
    scan = next((j for j in _jobs.values()
                 if j["job_type"] == "scan" and not j["done"]), None)
    submit = next((j for j in _jobs.values()
                   if j["job_type"] == "submit" and not j["done"]), None)
    return ActiveJobsResponse(
        scan=JobFrame(**scan) if scan else None,
        submit=JobFrame(**submit) if submit else None,
    )


# ── Sweeper ─────────────────────────────────────────────────────────────
async def _sweep_jobs() -> None:
    """每 60s 扫描一次，回收已完成超过 _JOB_RETENTION_SECONDS 的 job。"""
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(UTC)
            expired = [
                jid for jid, j in _jobs.items()
                if j["done"] and j["finished_at"]
                and (now - datetime.fromisoformat(j["finished_at"])).total_seconds() > _JOB_RETENTION_SECONDS
            ]
            for jid in expired:
                _jobs.pop(jid, None)
                logger.info("sweep: 回收 job %s", jid)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sweep cycle 失败")


# ── Candidates CRUD ─────────────────────────────────────────────────────
@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates(
    lifecycle_status: str | None = Query(default=None),
    matched_keyword_entry_id: int | None = Query(default=None),
    duplicate_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CandidateListResponse:
    svc = WhitelistCandidateService(db, magnet_svc=None)  # list 不用 magnet_svc
    items, total = svc.list_candidates(
        lifecycle_status=lifecycle_status,
        matched_keyword_entry_id=matched_keyword_entry_id,
        duplicate_status=duplicate_status,
        search=search, page=page, page_size=page_size,
    )
    return CandidateListResponse(
        items=[CandidateResponse.model_validate(c) for c in items],
        total=total, page=page, page_size=page_size,
    )


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(
    candidate_id: int,
    payload: DismissRequest,
    db: Session = Depends(get_db),
) -> dict:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    try:
        cand = svc.dismiss(candidate_id=candidate_id, reason=payload.reason)
    except LookupError:
        raise HTTPException(404, "Candidate not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"candidate_id": cand.id, "lifecycle_status": cand.lifecycle_status}


@router.post("/candidates/{candidate_id}/restore")
def restore_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
) -> dict:
    svc = WhitelistCandidateService(db, magnet_svc=None)
    try:
        cand = svc.restore(candidate_id=candidate_id)
    except LookupError:
        raise HTTPException(404, "Candidate not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"candidate_id": cand.id, "lifecycle_status": cand.lifecycle_status}


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models.whitelist import WhitelistCandidate
    cand = db.get(WhitelistCandidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "Candidate not found")
    db.delete(cand)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: 注册路由到 `app/main.py`**

在 `app/main.py` 的 import 块（约第 63-84 行）中追加：
```python
from app.api.routes import (  # noqa: E402 — import after app creation
    auth,
    auth_code,
    cleanup,
    extractor,
    files_115,
    home,
    imports,
    jobs,
    keywords,
    local_cleanup,
    local_organize,
    local_tree_export,
    magnet_tasks,
    nodes,
    open_auth,
    path_picker,
    plans,
    qr_login,
    strategy,
    tasks,
    whitelist_batch,  # 新增
)
```

并在 router 注册块（`app.include_router(...)` 的尾部）追加：
```python
app.include_router(whitelist_batch.router)
```

- [ ] **Step 5: 在 lifespan 启动 sweeper**

修改 `app/main.py` 的 `lifespan` 函数，在 `yield` 之前追加：
```python
    # 启动白名单批处理的 job sweeper
    from app.api.routes.whitelist_batch import _sweep_jobs
    app.state.whitelist_job_sweeper = asyncio.create_task(_sweep_jobs())
    logger.info("白名单 sweeper 启动")
```

在 `yield` 之后追加：
```python
    if hasattr(app.state, "whitelist_job_sweeper"):
        app.state.whitelist_job_sweeper.cancel()
```

并确保文件顶部 import 中有 `import asyncio`（已有则跳过）。

- [ ] **Step 6: 运行路由测试通过**

Run: `pytest tests/whitelist/test_whitelist_batch_routes.py -v`
Expected: 8 PASS

- [ ] **Step 7: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿（94 + 新增 ~25 = ~119 项）

- [ ] **Step 8: 提交**

```bash
git add app/api/routes/whitelist_batch.py app/main.py tests/whitelist/test_whitelist_batch_routes.py
git commit -m "feat: 白名单批处理路由 + Job 编排 + SSE + sweeper"
```

---

### Task 7: 删除旧 API（magnet_download_service + magnet_tasks 路由）

**Files:**
- Modify: `app/services/magnet_download_service.py:644-760`
- Modify: `app/api/routes/magnet_tasks.py:153-224`
- Modify: `app/schemas/magnet_tasks.py` (删除 WhitelistBatch* schemas)

- [ ] **Step 1: 找出受影响测试**

Run:
```bash
grep -rn "preview_whitelist_batch\|submit_whitelist_batch\|WhitelistBatchRequest\|WhitelistBatchPreviewResponse\|WhitelistBatchSubmitResponse\|WhitelistBatchCandidate" app/ tests/
```
Expected: 列出引用清单。所有引用都要清理（旧用户代码已不会再调用）。

- [ ] **Step 2: 删除 magnet_download_service 中的两个方法**

打开 `app/services/magnet_download_service.py`，删除以下两段代码：
- `def preview_whitelist_batch(...)` (~ 644-736 行)
- `def submit_whitelist_batch(...)` (~ 738-760 行)

同时删除文件顶部多余的 import（如 `WhitelistBatchPreviewItem`、`WhitelistBatchPreviewRun` 如果只此处用）。

- [ ] **Step 3: 删除 magnet_tasks 路由中两个端点**

打开 `app/api/routes/magnet_tasks.py`，删除：
- `@router.post("/whitelist-batch/preview", ...)` 整段（~ 153-193 行）
- `@router.post("/whitelist-batch/submit", ...)` 整段（~ 196-224 行）

同时清理 imports（`WhitelistBatchRequest` 等）。

- [ ] **Step 4: 删除旧 schemas**

打开 `app/schemas/magnet_tasks.py`，删除：
- `class WhitelistBatchRequest(...)`
- `class WhitelistBatchPreviewResponse(...)`
- `class WhitelistBatchSubmitResponse(...)`
- `class WhitelistBatchCandidateResponse(...)`
- 内部 dataclass `WhitelistBatchPreviewItem` / `WhitelistBatchPreviewRun` （如在此文件）

- [ ] **Step 5: 删除受影响的旧测试**

Run:
```bash
ls tests/ | xargs -I {} grep -l "whitelist_batch\|preview_whitelist_batch" tests/{} 2>/dev/null
```
对每个匹配文件，删除/改写引用旧 API 的测试用例。

- [ ] **Step 6: 跑全套测试**

Run: `pytest -q`
Expected: 全绿。如有引用旧符号的残留，按报错点继续清理。

- [ ] **Step 7: 提交**

```bash
git add -u
git commit -m "refactor: 删除旧白名单批处理 API（preview / submit + schemas）"
```

---

### Task 8: nginx 配置更新（SSE 长连接）

**Files:**
- Modify: `docker/nginx.conf`

- [ ] **Step 1: 打开 docker/nginx.conf，修改 `/api/` location**

把现有：
```nginx
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
```
改成：
```nginx
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;

        # SSE 长连接支持
        proxy_buffering off;
        proxy_cache off;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        chunked_transfer_encoding on;
        gzip off;
    }
```

- [ ] **Step 2: 验证 nginx 语法（本地不易测；提交后服务器重启时验证）**

留待 Task 13 部署阶段验证。

- [ ] **Step 3: 提交**

```bash
git add docker/nginx.conf
git commit -m "fix: nginx /api/ 加 SSE 长连接配置（关闭缓冲/缓存/gzip + HTTP1.1 keepalive）"
```

---

### Task 9: 前端 API 包装

**Files:**
- Create: `frontend/src/api/whitelistBatch.ts`

- [ ] **Step 1: 创建 API 包装**

创建 `frontend/src/api/whitelistBatch.ts`：
```typescript
import { api } from './client'

// ── 类型 ────────────────────────────────────────────────────────────────
export interface ScanJobRequest {
  tree_import_id: number
  keyword_entry_ids?: number[]
  per_keyword_limit?: number
}

export interface SubmitJobRequest {
  candidate_ids: number[]
  force_submit?: boolean
}

export interface JobFrame {
  job_id: string
  job_type: 'scan' | 'submit'
  stage: string
  current: number
  total: number
  done: boolean
  error: string | null
  summary: Record<string, number> | null
  started_at: string
  finished_at: string | null
}

export interface ActiveJobs {
  scan: JobFrame | null
  submit: JobFrame | null
}

export interface WhitelistCandidate {
  id: number
  source_tid: number
  source_magnet: string
  source_title: string
  source_section: string | null
  source_detail_url: string | null
  matched_keyword_entry_id: number
  matched_keyword: string
  matched_alias: string | null
  match_score: number
  last_scanned_tree_import_id: number | null
  duplicate_status: string
  duplicate_reason: string | null
  matched_import_label: string | null
  target_path: string
  lifecycle_status: string
  magnet_task_id: number | null
  dismissed_at: string | null
  submitted_at: string | null
  failure_reason: string | null
  first_seen_at: string
  last_scanned_at: string
}

export interface CandidateListResponse {
  items: WhitelistCandidate[]
  total: number
  page: number
  page_size: number
}

export interface CandidateListParams {
  lifecycle_status?: string
  matched_keyword_entry_id?: number
  duplicate_status?: string
  search?: string
  page?: number
  page_size?: number
}

// ── API 调用 ────────────────────────────────────────────────────────────
export function startScanJob(payload: ScanJobRequest) {
  return api.post<{ job_id: string; status: string }>(
    '/whitelist-batch/scan-jobs', payload,
  )
}

export function startSubmitJob(payload: SubmitJobRequest) {
  return api.post<{ job_id: string; status: string }>(
    '/whitelist-batch/submit-jobs', payload,
  )
}

export function getActiveJobs() {
  return api.get<ActiveJobs>('/whitelist-batch/jobs/active')
}

export function listCandidates(params: CandidateListParams = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  return api.get<CandidateListResponse>(
    `/whitelist-batch/candidates${q.toString() ? '?' + q.toString() : ''}`,
  )
}

export function dismissCandidate(id: number, reason?: string) {
  return api.post<{ candidate_id: number; lifecycle_status: string }>(
    `/whitelist-batch/candidates/${id}/dismiss`,
    { reason: reason ?? null },
  )
}

export function restoreCandidate(id: number) {
  return api.post<{ candidate_id: number; lifecycle_status: string }>(
    `/whitelist-batch/candidates/${id}/restore`,
  )
}

export function deleteCandidate(id: number) {
  return api.delete<{ ok: boolean }>(`/whitelist-batch/candidates/${id}`)
}

// SSE 订阅辅助：返回 unsubscribe 函数
export function subscribeJobProgress(
  jobId: string,
  onFrame: (frame: JobFrame | { error: string }) => void,
  onDone?: () => void,
): () => void {
  const es = new EventSource(`/api/whitelist-batch/jobs/${jobId}/progress`)
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    onFrame(data)
    if (data.done) {
      es.close()
      onDone?.()
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: 无类型错误。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/whitelistBatch.ts
git commit -m "feat: 前端 whitelistBatch API 包装"
```

---

### Task 10: 前端新页面 WhitelistBatchPage

**Files:**
- Create: `frontend/src/pages/WhitelistBatchPage.tsx`

- [ ] **Step 1: 创建页面**

创建 `frontend/src/pages/WhitelistBatchPage.tsx`：
```typescript
import { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Empty, Input, Pagination, Popconfirm, Progress,
  Select, Space, Statistic, Table, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudDownloadOutlined, DeleteOutlined, ReloadOutlined,
  ScanOutlined, UndoOutlined,
} from '@ant-design/icons'

import { api } from '../api/client'
import {
  dismissCandidate, getActiveJobs, listCandidates, restoreCandidate,
  startScanJob, startSubmitJob, subscribeJobProgress,
  type JobFrame, type WhitelistCandidate,
} from '../api/whitelistBatch'

const { Title } = Typography

interface TreeImportSummary { id: number; source_filename: string }
interface KeywordEntry { id: number; canonical_name: string }

const LIFECYCLE_OPTIONS = [
  { label: '全部', value: '' },
  { label: '待提交 pending', value: 'pending' },
  { label: '已提交 submitted', value: 'submitted' },
  { label: '已丢弃 dismissed', value: 'dismissed' },
  { label: '失败 failed', value: 'failed' },
]

const DUPLICATE_OPTIONS = [
  { label: '全部', value: '' },
  { label: 'clear', value: 'clear' },
  { label: 'duplicate_found', value: 'duplicate_found' },
  { label: 'task_exists', value: 'task_exists' },
]

export default function WhitelistBatchPage() {
  const [treeImports, setTreeImports] = useState<TreeImportSummary[]>([])
  const [selectedTreeImportId, setSelectedTreeImportId] = useState<number | undefined>()
  const [keywords, setKeywords] = useState<KeywordEntry[]>([])
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<number[]>([])
  const [perKeywordLimit, setPerKeywordLimit] = useState(10)

  const [scanJob, setScanJob] = useState<JobFrame | null>(null)
  const [submitJob, setSubmitJob] = useState<JobFrame | null>(null)

  const [candidates, setCandidates] = useState<WhitelistCandidate[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(100)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const [filterLifecycle, setFilterLifecycle] = useState('pending')
  const [filterKeywordId, setFilterKeywordId] = useState<number | undefined>()
  const [filterDuplicate, setFilterDuplicate] = useState('')
  const [searchText, setSearchText] = useState('')

  // ── 加载基础数据 ────────────────────────────────────────────────────
  useEffect(() => {
    api.get<{ items?: TreeImportSummary[]; tree_imports?: TreeImportSummary[] }>(
      '/imports?page=1&page_size=50'
    ).then((r) => {
      const list = (r.items ?? r.tree_imports ?? []) as TreeImportSummary[]
      setTreeImports(list)
      if (list.length > 0 && selectedTreeImportId === undefined) {
        setSelectedTreeImportId(list[0].id)
      }
    }).catch(() => message.error('加载目录树列表失败'))

    api.get<{ items?: KeywordEntry[]; keyword_entries?: KeywordEntry[] }>(
      '/keywords?keyword_type=whitelist&status=active&limit=5000'
    ).then((r) => {
      setKeywords((r.items ?? r.keyword_entries ?? []) as KeywordEntry[])
    }).catch(() => message.error('加载白名单关键词失败'))

    refreshActiveJobs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function refreshActiveJobs() {
    getActiveJobs().then((data) => {
      if (data.scan) {
        setScanJob(data.scan)
        subscribeJobProgress(data.scan.job_id, (frame) => {
          if ('error' in frame) return
          setScanJob(frame)
        }, () => loadCandidates())
      }
      if (data.submit) {
        setSubmitJob(data.submit)
        subscribeJobProgress(data.submit.job_id, (frame) => {
          if ('error' in frame) return
          setSubmitJob(frame)
        }, () => loadCandidates())
      }
    })
  }

  // ── 加载候选 ────────────────────────────────────────────────────────
  useEffect(() => {
    loadCandidates()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filterLifecycle, filterKeywordId, filterDuplicate, searchText])

  function loadCandidates() {
    listCandidates({
      lifecycle_status: filterLifecycle || undefined,
      matched_keyword_entry_id: filterKeywordId,
      duplicate_status: filterDuplicate || undefined,
      search: searchText || undefined,
      page, page_size: pageSize,
    }).then((r) => {
      setCandidates(r.items)
      setTotal(r.total)
    }).catch(() => message.error('加载候选失败'))
  }

  // ── 启动扫描 ────────────────────────────────────────────────────────
  async function handleScan() {
    if (!selectedTreeImportId) {
      message.warning('请先选择目录树批次')
      return
    }
    try {
      const resp = await startScanJob({
        tree_import_id: selectedTreeImportId,
        keyword_entry_ids: selectedKeywordIds.length ? selectedKeywordIds : undefined,
        per_keyword_limit: perKeywordLimit,
      })
      setScanJob({
        job_id: resp.job_id, job_type: 'scan', stage: '等待开始',
        current: 0, total: 0, done: false, error: null, summary: null,
        started_at: new Date().toISOString(), finished_at: null,
      })
      subscribeJobProgress(resp.job_id, (frame) => {
        if ('error' in frame) {
          message.error(`SSE 错误：${frame.error}`); return
        }
        setScanJob(frame)
      }, () => {
        message.success('扫描完成')
        loadCandidates()
      })
    } catch (e: any) {
      if (e?.response?.status === 409) message.warning('已有扫描任务在运行')
      else message.error('扫描启动失败')
    }
  }

  // ── 启动提交 ────────────────────────────────────────────────────────
  async function handleSubmit() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) {
      message.warning('请先勾选要提交的候选项')
      return
    }
    try {
      const resp = await startSubmitJob({ candidate_ids: ids })
      setSubmitJob({
        job_id: resp.job_id, job_type: 'submit', stage: '等待开始',
        current: 0, total: ids.length, done: false, error: null, summary: null,
        started_at: new Date().toISOString(), finished_at: null,
      })
      subscribeJobProgress(resp.job_id, (frame) => {
        if ('error' in frame) return
        setSubmitJob(frame)
      }, () => {
        const s = (submitJob?.summary || {}) as any
        message.success(`提交完成：成功 ${s.submitted ?? 0}，失败 ${s.failed ?? 0}，跳过 ${s.skipped ?? 0}`)
        setSelectedIds(new Set())
        loadCandidates()
      })
    } catch (e: any) {
      if (e?.response?.status === 409) message.warning('已有提交任务在运行')
      else message.error('提交启动失败')
    }
  }

  // ── 单行操作 ────────────────────────────────────────────────────────
  async function handleDismiss(cand: WhitelistCandidate) {
    try {
      await dismissCandidate(cand.id)
      message.success(`已丢弃 ${cand.source_title}`)
      loadCandidates()
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? '丢弃失败')
    }
  }

  async function handleRestore(cand: WhitelistCandidate) {
    try {
      await restoreCandidate(cand.id)
      message.success('已恢复为 pending')
      loadCandidates()
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? '恢复失败')
    }
  }

  const columns: ColumnsType<WhitelistCandidate> = [
    { title: '资源标题', dataIndex: 'source_title', width: 280, ellipsis: true },
    { title: '命中关键词', dataIndex: 'matched_keyword', width: 120 },
    {
      title: 'duplicate', dataIndex: 'duplicate_status', width: 110,
      render: (s: string, row) => {
        const color = s === 'clear' ? 'green' : s === 'duplicate_found' ? 'orange' : 'red'
        return <Tag color={color} title={row.duplicate_reason ?? undefined}>{s}</Tag>
      },
    },
    {
      title: 'lifecycle', dataIndex: 'lifecycle_status', width: 110,
      render: (s: string) => {
        const color = s === 'pending' ? 'blue' : s === 'submitted' ? 'green' :
                       s === 'dismissed' ? 'default' : 'red'
        return <Tag color={color}>{s}</Tag>
      },
    },
    { title: 'score', dataIndex: 'match_score', width: 80, render: (v: number) => v.toFixed(2) },
    {
      title: '操作', key: 'op', width: 180,
      render: (_: unknown, row) => {
        if (row.lifecycle_status === 'pending') {
          return (
            <Popconfirm title="确认丢弃？下次扫描不会再出现" onConfirm={() => handleDismiss(row)}>
              <Button size="small" danger>丢弃</Button>
            </Popconfirm>
          )
        }
        if (row.lifecycle_status === 'dismissed' || row.lifecycle_status === 'failed') {
          return <Button size="small" icon={<UndoOutlined />} onClick={() => handleRestore(row)}>恢复</Button>
        }
        if (row.lifecycle_status === 'submitted' && row.magnet_task_id) {
          return (
            <Button size="small" onClick={() => window.open(`/magnet-tasks?task_id=${row.magnet_task_id}`, '_blank')}>
              查看任务
            </Button>
          )
        }
        return null
      },
    },
  ]

  const submitDisabled = selectedIds.size === 0 || !!submitJob && !submitJob.done

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Title level={3}>白名单批处理</Title>

      <Card title="扫描控制台" className="soft-card">
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Space wrap>
            <Select
              style={{ minWidth: 260 }}
              placeholder="选择目录树批次"
              value={selectedTreeImportId}
              onChange={setSelectedTreeImportId}
              options={treeImports.map(t => ({ value: t.id, label: `#${t.id} ${t.source_filename}` }))}
            />
            <Select
              mode="multiple"
              style={{ minWidth: 320 }}
              placeholder="留空 = 所有 active 白名单"
              value={selectedKeywordIds}
              onChange={setSelectedKeywordIds}
              options={keywords.map(k => ({ value: k.id, label: k.canonical_name }))}
              maxTagCount="responsive"
            />
            <Input
              addonBefore="每词上限" type="number" style={{ width: 160 }}
              value={perKeywordLimit}
              onChange={e => setPerKeywordLimit(Number(e.target.value) || 10)}
            />
            <Button
              type="primary" icon={<ScanOutlined />} onClick={handleScan}
              loading={!!scanJob && !scanJob.done}
            >
              开始扫描
            </Button>
          </Space>

          {scanJob && (
            <Card size="small" type="inner" title={`扫描进度（${scanJob.stage}）`}>
              <Progress percent={scanJob.total ? Math.round((scanJob.current / scanJob.total) * 100) : 0}
                        status={scanJob.error ? 'exception' : scanJob.done ? 'success' : 'active'} />
              <div>{scanJob.current}/{scanJob.total}</div>
              {scanJob.summary && (
                <Space size="large" style={{ marginTop: 8 }}>
                  <Statistic title="新增" value={(scanJob.summary as any).new ?? 0} />
                  <Statistic title="更新" value={(scanJob.summary as any).updated ?? 0} />
                  <Statistic title="跳过" value={(scanJob.summary as any).skipped ?? 0} />
                  <Statistic title="失败关键词" value={(scanJob.summary as any).failed_keywords ?? 0} />
                </Space>
              )}
              {scanJob.error && <div style={{ color: 'red' }}>错误：{scanJob.error}</div>}
            </Card>
          )}
        </Space>
      </Card>

      <Card title="候选列表" className="soft-card"
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} onClick={loadCandidates}>刷新</Button>
                <Button type="primary" icon={<CloudDownloadOutlined />}
                        disabled={submitDisabled} onClick={handleSubmit}>
                  提交勾选（{selectedIds.size}）
                </Button>
              </Space>
            }>
        <Space style={{ marginBottom: 12 }} wrap>
          <Select style={{ width: 160 }} value={filterLifecycle}
                  onChange={(v) => { setFilterLifecycle(v); setPage(1) }}
                  options={LIFECYCLE_OPTIONS} />
          <Select style={{ width: 200 }} value={filterKeywordId} allowClear
                  placeholder="按关键词筛选"
                  onChange={(v) => { setFilterKeywordId(v); setPage(1) }}
                  options={keywords.map(k => ({ value: k.id, label: k.canonical_name }))} />
          <Select style={{ width: 180 }} value={filterDuplicate}
                  onChange={(v) => { setFilterDuplicate(v); setPage(1) }}
                  options={DUPLICATE_OPTIONS} />
          <Input.Search placeholder="搜索标题/关键词" style={{ width: 240 }}
                        onSearch={(v) => { setSearchText(v); setPage(1) }} />
        </Space>

        {candidates.length === 0 ? (
          <Empty description="没有候选" />
        ) : (
          <>
            <Table
              size="small" rowKey="id" pagination={false}
              columns={columns} dataSource={candidates}
              rowSelection={{
                selectedRowKeys: Array.from(selectedIds),
                onChange: (keys) => setSelectedIds(new Set(keys as number[])),
                getCheckboxProps: (row) => ({ disabled: row.lifecycle_status !== 'pending' }),
              }}
            />
            <Pagination
              style={{ marginTop: 12, textAlign: 'right' }}
              current={page} pageSize={pageSize} total={total}
              showSizeChanger={false}
              onChange={setPage}
            />
          </>
        )}
      </Card>

      {submitJob && (
        <Card title={`提交进度（${submitJob.stage}）`} className="soft-card">
          <Progress percent={submitJob.total ? Math.round((submitJob.current / submitJob.total) * 100) : 0}
                    status={submitJob.error ? 'exception' : submitJob.done ? 'success' : 'active'} />
          <div>{submitJob.current}/{submitJob.total}</div>
          {submitJob.summary && (
            <Space size="large" style={{ marginTop: 8 }}>
              <Statistic title="成功" value={(submitJob.summary as any).submitted ?? 0} />
              <Statistic title="失败" value={(submitJob.summary as any).failed ?? 0} />
              <Statistic title="跳过" value={(submitJob.summary as any).skipped ?? 0} />
            </Space>
          )}
          {submitJob.error && <div style={{ color: 'red' }}>错误：{submitJob.error}</div>}
        </Card>
      )}
    </Space>
  )
}
```

- [ ] **Step 2: 验证类型检查**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: 编译通过（可能有 antd 警告但无 type error）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/WhitelistBatchPage.tsx
git commit -m "feat: 前端 WhitelistBatchPage 新页面"
```

---

### Task 11: App.tsx 路由 + 菜单 + 清理 MagnetTasksPage

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/MagnetTasksPage.tsx` (删除白名单批处理 Card)
- Modify: `frontend/src/api/types.ts` (删除旧类型)

- [ ] **Step 1: App.tsx 注册新页面**

修改 `frontend/src/App.tsx`：

在 import 块加：
```typescript
import WhitelistBatchPage from './pages/WhitelistBatchPage'
```

在 `const NAV = [...]` 中（约第 40-52 行），在 `磁力下载` 项之前插入：
```typescript
  { key: '/whitelist-batch', label: '白名单批处理', icon: <TagsOutlined /> },
```

在 `<Routes>` 块（约第 231-260 行）中加：
```tsx
<Route path="/whitelist-batch" element={<WhitelistBatchPage />} />
```

- [ ] **Step 2: 删除 MagnetTasksPage 中白名单批处理代码**

打开 `frontend/src/pages/MagnetTasksPage.tsx`，删除：

- 整个 `<Card title="白名单批处理">...` JSX 块（约第 529-620 行）
- 相关 state hooks：`whitelistEntries`、`selectedWhitelistKeywordIds`、`perKeywordLimit`、`totalPreviewLimit`、`submitLimit`、`batchPreview`、`batchStats`、`batchPreviewSearch`、`batchDuplicateFilter`、`selectedBatchPreviewKeys`
- 相关 handlers：`handleRefreshWhitelist`、`handlePreviewBatch`、`handleSubmitBatch`
- 相关 `useMemo`、`useEffect`、列定义 `batchPreviewColumns`
- imports：`KeywordEntry`、`KeywordEntryListResponse`、`WhitelistBatchCandidate`、`WhitelistBatchPreviewResponse`、`WhitelistBatchSubmitResponse`、`getBatchPreviewRowKey` 等仅此处用的符号

清理完后行数应该从 803 降到 ~600。

- [ ] **Step 3: 清理 types.ts 中旧类型**

打开 `frontend/src/api/types.ts`，删除：
- `WhitelistBatchCandidate`
- `WhitelistBatchPreviewResponse`
- `WhitelistBatchSubmitResponse`
- `WhitelistBatchRequestPayload`（如有）

- [ ] **Step 4: 验证编译**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: 编译通过。如有引用残留按报错修。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.tsx frontend/src/pages/MagnetTasksPage.tsx frontend/src/api/types.ts
git commit -m "refactor: App.tsx 注册 /whitelist-batch 路由，MagnetTasksPage 删除白名单批处理 Card"
```

---

### Task 12: 部署 + 端到端验证

**Files:** 服务器 `root@192.168.70.138:/mnt/user/docker1/18xv2`

- [ ] **Step 1: 推送 + 服务器拉取**

```bash
git push origin feat/conflict-resolution
ssh root@192.168.70.138 "cd /mnt/user/docker1/18xv2 && git -c core.fileMode=false pull --ff-only"
```
Expected: 成功 fast-forward。

- [ ] **Step 2: 重建镜像并重启**

```bash
ssh root@192.168.70.138 "cd /mnt/user/docker1/18xv2 && docker compose -f docker/docker-compose.yml build --no-cache app && docker compose -f docker/docker-compose.yml up -d"
```
Expected: 构建 + 启动成功。

- [ ] **Step 3: 检查健康 + alembic 已应用 0005**

```bash
ssh root@192.168.70.138 "
  curl -s http://localhost:8010/api/healthz
  echo
  docker exec docker-postgres-1 psql -U postgres -d organizer -c '\d whitelist_candidates' | head -30
  docker exec docker-postgres-1 psql -U postgres -d organizer -c 'SELECT version_num FROM alembic_version'
"
```
Expected: healthz `ok`；表存在；alembic version 是 `0005`。

- [ ] **Step 4: 手动验收（按 spec §7.3 清单）**

逐项执行：
1. ✅ 浏览器打开 `http://192.168.70.138:8010/whitelist-batch`，页面正常显示
2. ✅ 选 1 个目录树 + 1-2 个白名单关键词 + per_keyword_limit=5，点扫描；SSE 进度条秒级更新
3. ✅ 候选列表勾 3 条，点提交；提交进度条逐条更新，间隔 = offline_submit_interval_seconds
4. ✅ 中途刷新页面：getActiveJobs 接回进行中的 job，进度条恢复
5. ✅ 第二次扫描同关键词：summary.skipped > 0；submitted 行的 lifecycle 不变
6. ✅ 整流程 `uptime` load avg < 1，`docker stats docker-app-1` CPU < 30%
7. ✅ 丢弃一条 → 重扫：丢弃项不再出现
8. ✅ 故意提交 1 条已不存在的资源（构造场景）：列表显示红色 failed badge + summary.failed=1
9. ✅ 打开第二个浏览器 tab，订阅同一 job 的 SSE：两个 tab 都能收到 done 帧（无 not found 错误）

- [ ] **Step 5: 终稿提交（无需改代码就略过）**

如果验收暴露问题，按修复后单独提交；否则跳过。

---

## Self-Review

### Spec 覆盖检查

| Spec 节 | 内容 | 对应 Task |
|---|---|---|
| §3.1 | WhitelistCandidate 模型 + 唯一约束 + 索引 | Task 1 |
| §3.3 | Alembic 迁移 | Task 1 |
| §4.1 | 服务目录结构 | Task 3-5 |
| §4.2 | scan 算法（多关键词独立行 / 低成本跳过 / 高成本重算 / 每词一 commit / 失败不阻断） | Task 3 |
| §4.3 | submit_selected（refresh / rollback / 跳过非 pending） | Task 4 |
| §4.4 | HTTP 接口（scan-jobs / submit-jobs / progress / active / candidates / dismiss / restore / delete） | Task 6 |
| §4.4 | force_submit 透传 | Task 4 + Task 6 |
| §4.5 | UUID job_id / asyncio.Lock / SSE 心跳 / sweeper | Task 6 |
| §4.6 | lifespan 启动 sweeper | Task 6 Step 5 |
| §5.1-5.4 | 前端页面 / API / 路由 / SSE 订阅 | Task 9-11 |
| §6 错误矩阵 | 各分支测试覆盖 | Task 3-6 测试 |
| §7.1 测试清单 | 全部测试 | Task 3-6 |
| §7.3 手动验收 | 9 项手动验收 | Task 12 |
| §8 文件清单 | 13 个新文件 + 8 个修改 | Task 1-11 |

### Type 一致性

- `source_tid: int`（与 MagnetDownloadTask 一致）✓
- `job_id: str`（UUID 字符串）✓
- `progress_cb: Callable[[str, int, int], None]`（stage, current, total）✓
- `ScanSummary` / `SubmitSummary` 字段在 schemas + 测试 + 前端 statistic 字段名一致 ✓

### Placeholder 扫描

无 TBD / TODO / "implement later" / "similar to" 引用。所有 code block 都是可执行的。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-05-19-whitelist-batch.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
