# 白名单批处理独立化 + 持久化候选账本 设计文档

**日期**：2026-05-19
**作者**：王易川 / Claude
**状态**：设计阶段

---

## 1. 背景与目标

### 当前问题

白名单批处理（whitelist batch）目前挂在磁力下载页面 `MagnetTasksPage`（803 行），与磁力任务台、批次列表、手动单条搜词等功能耦合，并存在三个使用痛点：

1. **页面拥挤**：四个功能挤在一个页面，操作流不清晰。
2. **预览总数上限无意义**：第一轮匹配 + 去重的结果本身就需要人工审核，再加 `total_limit` 截断只会让用户错过候选。
3. **单次提交后必须手动再点**：`submit_limit` 把勾选项切成几批，每批跑完后用户得手动再点"提交"。用户不可能坐在电脑前等一轮又一轮。
4. **预览结果仅在内存**：每次扫描都重跑外部库 + 重新去重，扫过的候选下次还会再出现。未来无法接定时扫描任务。

### 本次迭代目标

- 把白名单批处理拆出为独立页面 `/whitelist-batch`
- 引入持久化候选账本 `whitelist_candidates`，跨次扫描去重 + 状态复用
- 扫描和提交都改为后台 job + SSE 推送，复用 §async-import（2026-05-18）已落地的模式
- 用户勾选后一次启动提交 job，后台自动循环至所有勾选项处理完
- 为下一迭代的定时扫描任务铺好数据基础（本次不实现 cron）

### 非目标

- 定时扫描 cron（下一迭代）
- 多用户并发 / 多用户权限
- 候选行内编辑 target_path（保留只读）
- 候选合并 / 拆分
- WebSocket 推送（SSE 够用）

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│  /whitelist-batch (新独立页面)                                       │
│                                                                      │
│   [开始扫描]  [候选列表 + 勾选 + 丢弃]  [开始提交]  ◀──── SSE 进度条 │
└────────┬─────────────────────────────────────┬───────────────────────┘
         │ POST /whitelist-batch/scan-jobs     │ POST /whitelist-batch/submit-jobs
         │ GET  /jobs/{id}/progress (SSE)      │ GET  /jobs/{id}/progress (SSE)
         │ GET  /whitelist-batch/candidates    │ POST /candidates/{id}/dismiss
         ▼                                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│  WhitelistCandidateService                                           │
│  scan(tree_import_id, keyword_ids)  ──► 写/更新 whitelist_candidate │
│  submit(candidate_ids)              ──► 调 MagnetDownloadService    │
│                                          建 MagnetDownloadTask + 回填 │
└──────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                ┌─────────────────────────────────┐
                │  whitelist_candidate (新表)     │
                │  UNIQUE(source_tid,             │
                │         source_magnet)          │
                │  lifecycle_status:              │
                │    pending / submitted /        │
                │    dismissed / failed           │
                │  magnet_task_id → MagnetDownload│
                │                          Task   │
                └─────────────────────────────────┘
```

### 核心设计决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 异步模型 | asyncio.Lock + asyncio.to_thread + SSE | 复用刚做完的 async-import 模式，0 新依赖 |
| 失败策略 | 跳过失败项继续，末尾汇总 | 单条失败不阻断整批；用户最后看 summary 决定重试 |
| 候选持久化 | 新表 `whitelist_candidates` | 跨次扫描去重；为 cron 任务铺底；与 MagnetDownloadTask 职责分离 |
| 与现有任务的关系 | 通过 `magnet_task_id` 外键（方案 A） | 边界清晰，跳转方便；不需要重写 MagnetDownloadTask 状态机 |
| 扫描复用粒度 | 低成本状态直接跳过，高成本重新评估 | 已 submitted/dismissed/task_exists 跳；clear/duplicate_found 重跑 duplicate 检查 |
| 扫描作业模式 | 也走 job + SSE | 扫几百关键词可能跑数分钟，同样需要异步 |
| 并发边界 | scan_lock + submit_lock 各一把（互不阻塞） | scan 期间允许同时提交"上次扫的候选" |
| candidate 与 tree_import | 不绑定，记录 last_scanned_tree_import_id | 同一 magnet 可被多棵树检查过；下次复用决策按"是否同一棵树"判 |

---

## 3. 数据模型

### 3.1 新表 `whitelist_candidates`

```python
# app/models/whitelist.py
class WhitelistCandidate(Base):
    __tablename__ = "whitelist_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 去重键（业务唯一）
    source_tid: Mapped[str] = mapped_column(String(64), index=True)
    source_magnet: Mapped[str] = mapped_column(Text)

    # 资源元信息（扫描时落盘，提交时无需重查外部库）
    source_title: Mapped[str] = mapped_column(Text)
    source_section: Mapped[str | None] = mapped_column(String(64))
    source_detail_url: Mapped[str | None] = mapped_column(Text)

    # 关键词命中
    matched_keyword_entry_id: Mapped[int] = mapped_column(
        ForeignKey("keyword_entries.id", ondelete="CASCADE"), index=True)
    matched_keyword: Mapped[str] = mapped_column(String(255))
    matched_alias: Mapped[str | None] = mapped_column(String(255))
    match_score: Mapped[float] = mapped_column(Float, default=0.0)

    # 重复检查快照
    last_scanned_tree_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("tree_imports.id", ondelete="SET NULL"))
    duplicate_status: Mapped[str] = mapped_column(String(32))
    # ↑ "clear" / "duplicate_found" / "task_exists"
    duplicate_reason: Mapped[str | None] = mapped_column(Text)
    matched_import_label: Mapped[str | None] = mapped_column(String(255))
    target_path: Mapped[str] = mapped_column(Text)

    # 生命周期
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True)
    # ↑ "pending" / "submitted" / "dismissed" / "failed"
    magnet_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("magnet_download_tasks.id", ondelete="SET NULL"))
    dismissed_at: Mapped[datetime | None]
    dismissed_reason: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    first_seen_at: Mapped[datetime] = mapped_column(default=func.now())
    last_scanned_at: Mapped[datetime] = mapped_column(default=func.now())

    __table_args__ = (
        UniqueConstraint("source_tid", "source_magnet",
                         name="uq_whitelist_candidate_source"),
        Index("ix_whitelist_candidate_lifecycle_keyword",
              "lifecycle_status", "matched_keyword_entry_id"),
    )
```

### 3.2 状态机

```
lifecycle_status 状态流转：

    [扫描首次命中]
          │
          ▼
       pending  ─────[用户勾选 + 提交成功]─────▶  submitted ────[查看任务详情]
          │                                            ▲
          │                                            │
          ├─────[用户提交但 115 失败]─────▶ failed   [duplicate_skipped 视同]
          │                                  │
          │                                  │
          │                              [DELETE /candidates/{id}
          │                               或手动重置后回到 pending]
          │
          └─────[用户点丢弃]─────────▶  dismissed
                                          │
                                          │
                                      [POST /candidates/{id}/restore]
                                          │
                                          ▼
                                       pending
```

**duplicate_status 与 lifecycle_status 的关系**：
- `duplicate_status` 描述"目录树/任务表中是否已有该资源"
- `lifecycle_status` 描述"用户处置该 candidate 的进度"
- 两者独立，但 `duplicate_status='task_exists'` 时 scan 自动跳过（视为已处理）

### 3.3 Alembic 迁移

新增 revision `versions/xxxx_add_whitelist_candidates_table.py`：
- `op.create_table("whitelist_candidates", ...)` 含全部字段
- 创建唯一约束 `uq_whitelist_candidate_source`
- 创建复合索引 `ix_whitelist_candidate_lifecycle_keyword`
- 无数据迁移（旧 in-memory preview 无持久化数据）
- downgrade：`op.drop_table("whitelist_candidates")`

---

## 4. 后端实现

### 4.1 服务层目录结构

```
app/services/whitelist/                       # 新 package
├── __init__.py
├── candidate_service.py                       # WhitelistCandidateService
├── upsert.py                                  # 单候选 upsert 纯函数
└── job_runner.py                              # 协程封装（被 routes 调用）

app/services/magnet_download_service.py        # 删除
                                               #   preview_whitelist_batch
                                               #   submit_whitelist_batch
                                               # 保留 create_and_submit_tasks
                                               #     build_candidates_for_keyword_entry
                                               #     _check_single_duplicate
                                               #     _build_target_path
```

### 4.2 `WhitelistCandidateService.scan` 核心算法

```python
def scan(
    self, *,
    tree_import_id: int,
    keyword_entry_ids: list[int] | None,
    per_keyword_limit: int,
    progress_cb: Callable[[str, int, int], None],
) -> ScanSummary:
    entries = self._load_whitelist_entries(keyword_entry_ids)
    progress_cb("加载关键词", 0, len(entries))

    new_count = updated_count = skipped_count = failed_keywords = 0

    for idx, entry in enumerate(entries):
        progress_cb("扫描外部库", idx + 1, len(entries))
        try:
            raw_candidates = self.magnet_svc.build_candidates_for_keyword_entry(
                keyword_entry=entry, limit=per_keyword_limit
            )
            for cand in raw_candidates:
                existing = self.db.scalar(select(WhitelistCandidate).where(
                    WhitelistCandidate.source_tid == cand.source_tid,
                    WhitelistCandidate.source_magnet == cand.source_magnet,
                ))
                # 低成本状态直接跳过
                if existing and existing.lifecycle_status in {"submitted", "dismissed"}:
                    skipped_count += 1
                    continue
                if existing and existing.duplicate_status == "task_exists":
                    skipped_count += 1
                    continue

                # clear / duplicate_found / 新候选 → 重新评估 duplicate
                dup = self.magnet_svc._check_single_duplicate(
                    duplicate_input=_to_dup_input(cand),
                    tree_import_id=tree_import_id,
                )
                target_path = self.magnet_svc._build_target_path(...)

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
                    new_count += 1
                else:
                    existing.duplicate_status = dup.status
                    existing.duplicate_reason = dup.reason
                    existing.matched_import_label = dup.matched_import_label
                    existing.target_path = target_path
                    existing.last_scanned_tree_import_id = tree_import_id
                    existing.last_scanned_at = datetime.now(UTC)
                    updated_count += 1
            self.db.commit()   # 每关键词一 commit
        except Exception as exc:
            self.db.rollback()
            logger.exception("scan 关键词 %s 失败", entry.keyword)
            failed_keywords += 1

    return ScanSummary(
        scanned_keywords=len(entries),
        new=new_count,
        updated=updated_count,
        skipped=skipped_count,
        failed_keywords=failed_keywords,
    )
```

### 4.3 `WhitelistCandidateService.submit_selected` 核心算法

```python
def submit_selected(
    self, candidate_ids: list[int], *,
    force_submit: bool = False,
    progress_cb: Callable[[str, int, int], None],
) -> SubmitSummary:
    candidates = self.db.scalars(select(WhitelistCandidate).where(
        WhitelistCandidate.id.in_(candidate_ids),
    )).all()
    if not candidates:
        raise ValueError("未选择有效的候选项")

    submitted = failed = skipped = 0
    for idx, cand in enumerate(candidates):
        progress_cb("提交到 115", idx, len(candidates))
        if cand.lifecycle_status != "pending":
            skipped += 1
            continue
        try:
            task = self.magnet_svc.create_and_submit_tasks(
                items=[_to_create_item(cand)],
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
                skipped += 1
            else:  # "failed"
                cand.lifecycle_status = "failed"
                cand.failure_reason = task.failure_reason
                failed += 1
            self.db.commit()
        except Exception as exc:
            cand.lifecycle_status = "failed"
            cand.failure_reason = str(exc)
            self.db.commit()
            failed += 1
        # offline_submit_interval_seconds 由 create_and_submit_tasks 内部处理
    return SubmitSummary(submitted=submitted, failed=failed, skipped=skipped)
```

### 4.4 HTTP 接口

| Method & Path | 作用 | Payload / Query | Response |
|---|---|---|---|
| `POST /whitelist-batch/scan-jobs` | 启动扫描 job | `{tree_import_id, keyword_entry_ids?, per_keyword_limit}` | `{job_id, status: "pending"}` |
| `POST /whitelist-batch/submit-jobs` | 启动提交 job | `{candidate_ids[], force_submit?}` | `{job_id, status: "pending"}` |
| `GET /whitelist-batch/jobs/{job_id}/progress` | SSE 进度推送 | — | `text/event-stream` |
| `GET /whitelist-batch/jobs/active` | 查询进行中的 job（页面刷新时用） | — | `{scan?: {...}, submit?: {...}}` |
| `GET /whitelist-batch/candidates` | 列出候选 | `lifecycle_status?, matched_keyword_entry_id?, duplicate_status?, search?, page, page_size` | `{items: [...], total, page, page_size}` |
| `POST /whitelist-batch/candidates/{id}/dismiss` | 标记丢弃 | `{reason?}` | `{candidate_id, lifecycle_status: "dismissed"}` |
| `POST /whitelist-batch/candidates/{id}/restore` | 反丢弃 | — | `{candidate_id, lifecycle_status: "pending"}` |
| `DELETE /whitelist-batch/candidates/{id}` | 物理删除 | — | `{ok: true}` |

#### 错误规范

```python
# 409 Conflict — 同类型任务正在跑
{"detail": "已有扫描任务在运行，请等待完成"}
{"detail": "已有提交任务在运行，请等待完成"}

# 400 Bad Request
{"detail": "未找到任何 active 白名单关键词"}
{"detail": "未选择有效的候选项"}
{"detail": "已提交的候选不能丢弃"}

# 404 Not Found
{"detail": "Job not found"}     # SSE 首帧推 {"error": "not found"} 再断
{"detail": "Candidate not found"}
```

### 4.5 Job 运行机制

```python
# app/api/routes/whitelist_batch.py
import asyncio, itertools, json, logging
from app.services.whitelist.candidate_service import WhitelistCandidateService

router = APIRouter(prefix="/whitelist-batch", tags=["whitelist-batch"])
logger = logging.getLogger(__name__)

_scan_lock = asyncio.Lock()
_submit_lock = asyncio.Lock()
_jobs: dict[int, dict] = {}
_job_id_counter = itertools.count(1)

def _new_job(job_type: str) -> int:
    job_id = next(_job_id_counter)
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

@router.post("/scan-jobs")
async def start_scan_job(payload: ScanJobRequest, db: Session = Depends(get_db)):
    if _scan_lock.locked():
        raise HTTPException(409, "已有扫描任务在运行，请等待完成")
    job_id = _new_job("scan")
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}

async def _run_scan_job(job_id, payload):
    async with _scan_lock:
        await asyncio.to_thread(_blocking_scan, job_id, payload)

def _blocking_scan(job_id, payload):
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        def cb(stage, current, total):
            _jobs[job_id].update(stage=stage, current=current, total=total)
        svc = WhitelistCandidateService(session, ...)
        summary = svc.scan(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            progress_cb=cb,
        )
        _jobs[job_id].update(stage="完成", summary=summary.dict(), done=True)
    except Exception as exc:
        logger.exception("scan job %s 失败", job_id)
        _jobs[job_id].update(stage="失败", error=str(exc), done=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.now(UTC).isoformat()
        session.close()

# submit_jobs / _run_submit_job / _blocking_submit 同模板

@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: int) -> StreamingResponse:
    async def event_stream():
        while True:
            state = _jobs.get(job_id)
            if state is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            if state["done"]:
                await asyncio.sleep(5)
                _jobs.pop(job_id, None)
                break
            await asyncio.sleep(1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/jobs/active")
async def active_jobs():
    scan = next((j for j in _jobs.values() if j["job_type"] == "scan" and not j["done"]), None)
    submit = next((j for j in _jobs.values() if j["job_type"] == "submit" and not j["done"]), None)
    return {"scan": scan, "submit": submit}
```

### 4.6 服务启动清理

```python
# app/main.py lifespan 已经清理 TreeImport pending，这里追加：
from app.models.whitelist import WhitelistCandidate

with _SessionLocal() as _s:
    # 兜底：清理 duplicate_status 为 NULL 的残留（理论上不该出现，
    # 因为 scan 是每关键词一 commit；这是双保险）
    interrupted_cand = _s.query(WhitelistCandidate).filter(
        WhitelistCandidate.duplicate_status.is_(None)
    ).delete()
    _s.commit()
    if interrupted_cand:
        logger.info("lifespan: 清理 %d 条扫描中断的残留候选", interrupted_cand)
```

---

## 5. 前端实现

### 5.1 路由 & 导航

```tsx
// frontend/src/App.tsx
const NAV = [
  { key: '/imports', ... },
  ...
  { key: '/whitelist-batch', label: '白名单批处理', icon: <TagsOutlined /> },  // 新增
  { key: '/magnet-tasks',   label: '磁力下载', icon: <CloudDownloadOutlined /> },
  ...
]

<Route path="/whitelist-batch" element={<WhitelistBatchPage />} />
```

`MagnetTasksPage` 删除整个"白名单批处理" Card（~200 行），只保留磁力任务台、批次列表、手动单条搜词。

### 5.2 新页面 `WhitelistBatchPage.tsx`（预计 ~600 行）

布局：
```
┌─ 白名单批处理 ───────────────────────────────────────────────────────┐
│  ┌─ 扫描控制台 ─────────────────────────────────────────────────┐  │
│  │ 目录树：[Select tree_import ▼]                                │  │
│  │ 关键词：[多选，留空=全部] ▼                                   │  │
│  │ 每词上限：[Input 10]            [▶ 开始扫描]                  │  │
│  │ ─── 扫描进度（SSE）───                                         │  │
│  │ ▰▰▰▰▰▰▱▱▱▱  扫描外部库  120/250                              │  │
│  │ 已新增 45 / 更新 67 / 跳过 8                                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  ┌─ 候选列表 ──────────────────────────────────────────────────────┐ │
│  │ 筛选：[关键词▼] [duplicate▼] [lifecycle▼] [搜索...]            │ │
│  │ 操作：[✓ 全选页内可提交]  [⤴ 提交勾选 (12)]                    │ │
│  │ ┌──┬─────────────┬─────────┬─────────┬─────────┬───────────┐ │ │
│  │ │☑│ 资源标题     │命中关键词│duplicate│lifecycle│ 操作      │ │ │
│  │ ├──┼─────────────┼─────────┼─────────┼─────────┼───────────┤ │ │
│  │ │☑│ XXX-001 ...  │ 演员A   │ clear   │ pending │ 丢弃      │ │ │
│  │ │  │ YYY-002 ...  │ 演员B   │duplicate│ pending │ 详情/丢弃 │ │ │
│  │ │  │ ZZZ-003 ...  │ 演员A   │  -      │submitted│ 查看任务  │ │ │
│  │ │  │ AAA-004 ...  │ 演员C   │  -      │dismissed│ 恢复      │ │ │
│  │ └──┴─────────────┴─────────┴─────────┴─────────┴───────────┘ │ │
│  │ Pagination ◀ 1 2 3 ... ▶                                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  ┌─ 提交进度（提交 job 运行时才显示）──────────────────────────────┐│
│  │ ▰▰▰▰▱▱▱▱▱▱  提交到 115  8/20                                   ││
│  │ 成功 7  失败 1  跳过 0                                          ││
│  └────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### 5.3 关键交互

**页面加载**：
```ts
useEffect(() => {
  loadTreeImports()
  loadWhitelistKeywords()
  loadCandidates({page: 1, lifecycle_status: 'pending'})
  loadActiveJobs()   // 接回正在跑的 job 并订阅 SSE
}, [])
```

**SSE 订阅辅助函数**：
```ts
function subscribeJob(jobId: number, onFrame: (frame: JobFrame) => void) {
  const es = new EventSource(`/api/whitelist-batch/jobs/${jobId}/progress`)
  es.onmessage = (ev) => {
    const frame = JSON.parse(ev.data) as JobFrame
    onFrame(frame)
    if (frame.done) {
      es.close()
      loadCandidates()  // job 完成后刷新列表
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}
```

**启动扫描**：
```ts
async function handleScan() {
  const resp = await api.post('/whitelist-batch/scan-jobs', {
    tree_import_id: selectedTreeImportId,
    keyword_entry_ids: selectedKeywordIds,
    per_keyword_limit: perKeywordLimit,
  })
  setScanJob({ jobId: resp.job_id, ...emptyFrame })
  subscribeJob(resp.job_id, (frame) => setScanJob({ jobId: resp.job_id, ...frame }))
}
```

**启动提交**：
```ts
async function handleSubmit() {
  const ids = Array.from(selectedCandidateIds)
  if (ids.length === 0) {
    message.warning('请先勾选要提交的候选项')
    return
  }
  const resp = await api.post('/whitelist-batch/submit-jobs', { candidate_ids: ids })
  subscribeJob(resp.job_id, (frame) => {
    setSubmitJob({ jobId: resp.job_id, ...frame })
    if (frame.done) {
      const s = frame.summary || {}
      message.success(`提交完成：成功 ${s.submitted}，失败 ${s.failed}，跳过 ${s.skipped}`)
      setSelectedCandidateIds(new Set())
    }
  })
}
```

**丢弃 / 恢复 / 查看任务**：
- 行内按钮 → `POST /candidates/{id}/dismiss` → 局部更新该行
- 二次确认弹框（可选填原因）
- submitted 行点击 → 跳转 `/magnet-tasks?task_id=xxx`
- failed 行点击 → 弹框显示 failure_reason + "重置为 pending"按钮

### 5.4 状态管理

- useState + useEffect，不引入 react-query（与项目其他页面一致）
- SSE 订阅在 useEffect cleanup 里 close
- 候选列表后端分页，page_size=100

---

## 6. 错误处理矩阵

| 场景 | 行为 | 用户看到 |
|---|---|---|
| 扫描中外部库 timeout | 当前关键词跳过，进度推 warning，整 job 继续 | summary `failed_keywords: N` |
| 扫描中 DB 写失败 | 回滚该关键词，logger.exception，下一关键词继续 | summary `failed_keywords: N` |
| 提交中单条 115 报错 | 标 `lifecycle='failed'` + `failure_reason`，下一条继续 | summary `failed: N`，列表红色 badge |
| Job 外层抛异常 | `_jobs[job_id].update(error, done=True)`，SSE 推一帧后断 | message.error + 进度条变红 |
| Job 完成后 5s 内 | `_jobs.pop()` 前 sleep 5s，给前端读最后一帧 | 无感 |
| 服务器重启 → `_jobs` 丢失 | 刷新页面 → `GET /jobs/active` 返回空 → UI 进入"未运行"态 | 不卡死。candidate 表是事实来源 |
| 用户提交时 candidate_ids 含非 pending 项 | `submit_selected` 跳过这些，summary `skipped: N` | 不报 400，仅 skipped 计数 |
| `dismiss` 已 submitted 的候选 | 返回 400 | message.error |

---

## 7. 测试清单

### 7.1 后端 pytest

**`tests/whitelist/test_candidate_service_scan.py`**
- `test_scan_first_run_inserts_new_candidates`
- `test_scan_second_run_skips_submitted`
- `test_scan_second_run_skips_dismissed`
- `test_scan_re_evaluates_clear_status`
- `test_scan_re_evaluates_duplicate_found_status`
- `test_scan_skips_task_exists`
- `test_scan_progress_cb_called_per_keyword`
- `test_scan_commits_per_keyword`
- `test_scan_keyword_failure_does_not_abort_job`

**`tests/whitelist/test_candidate_service_submit.py`**
- `test_submit_creates_magnet_task_and_links`
- `test_submit_handles_single_failure_continues`
- `test_submit_skips_non_pending_candidates`
- `test_submit_summary_counts_correct`
- `test_submit_respects_offline_interval`
- `test_submit_dismissed_or_submitted_id_in_payload_is_skipped`

**`tests/whitelist/test_candidate_routes.py`**
- `test_scan_jobs_returns_409_when_scan_locked`
- `test_submit_jobs_returns_409_when_submit_locked`
- `test_scan_and_submit_can_run_concurrently`
- `test_jobs_progress_sse_streams_done_frame`
- `test_dismiss_then_restore_round_trip`
- `test_dismiss_submitted_candidate_returns_400`
- `test_get_active_jobs_returns_running_jobs`
- `test_list_candidates_filters_by_lifecycle_and_keyword`

### 7.2 前端

不写自动化测试（与项目其他页面一致），按"手动验收清单"走人工验收。

### 7.3 手动验收清单

部署到服务器后逐项执行：

1. **nginx SSE 支持**：检查 `docker/nginx.conf` 中 `/api/` location 添加 `proxy_buffering off;` `proxy_cache off;`，否则 SSE 会被缓冲
2. **扫描 1 个关键词**：看 SSE 实时推，进度条秒级更新
3. **候选勾 3 条 → 提交**：看到逐条进度，间隔 = `offline_submit_interval_seconds`
4. **中途切走再回页面**：进度条按 `GET /jobs/active` 恢复
5. **重复扫描同关键词**：已 submitted 的不变，clear/duplicate 重新评估
6. **服务器 load avg < 1**：整个流程负载不飙升
7. **丢弃 → 重新扫**：dismissed 项不再出现在结果里
8. **提交失败一条**：列表红色 badge + 末尾 summary `failed: 1`

---

## 8. 文件清单（实现时建/改）

### 新建

- `app/models/whitelist.py` —— WhitelistCandidate 模型
- `app/services/whitelist/__init__.py`
- `app/services/whitelist/candidate_service.py` —— WhitelistCandidateService
- `app/services/whitelist/upsert.py` —— 单候选 upsert 纯函数
- `app/services/whitelist/job_runner.py` —— 协程封装
- `app/schemas/whitelist.py` —— Pydantic schemas (ScanJobRequest, SubmitJobRequest, ScanSummary, SubmitSummary, CandidateResponse, ...)
- `app/api/routes/whitelist_batch.py` —— 全部 HTTP 接口
- `migrations/versions/xxxx_add_whitelist_candidates_table.py`
- `frontend/src/pages/WhitelistBatchPage.tsx`
- `frontend/src/api/whitelistBatch.ts` —— 前端 API 包装
- `tests/whitelist/__init__.py`
- `tests/whitelist/test_candidate_service_scan.py`
- `tests/whitelist/test_candidate_service_submit.py`
- `tests/whitelist/test_candidate_routes.py`

### 修改

- `app/main.py` —— 注册 whitelist_batch 路由 + lifespan 兜底清理
- `app/models/__init__.py` —— 导出 WhitelistCandidate
- `app/services/magnet_download_service.py` —— 删除 `preview_whitelist_batch` 和 `submit_whitelist_batch`
- `app/api/routes/magnet_tasks.py` —— 删除 `/whitelist-batch/preview` 和 `/whitelist-batch/submit` 路由
- `app/schemas/magnet_tasks.py` —— 删除 `WhitelistBatchRequest` `WhitelistBatchPreviewResponse` 等 schema
- `frontend/src/App.tsx` —— 添加路由 + 菜单项
- `frontend/src/pages/MagnetTasksPage.tsx` —— 删除整个"白名单批处理" Card
- `frontend/src/api/types.ts` —— 删除旧白名单批处理相关类型
- `docker/nginx.conf` —— `/api/` location 加 `proxy_buffering off;`

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 大量候选（万级）扫描 commit 频繁 | 每关键词一 commit，commit 频率 ≈ 关键词数（百级），可接受 |
| SSE 被 nginx 缓冲 | nginx.conf 加 `proxy_buffering off;` 并写进手动验收清单 |
| asyncio.Lock 的 locked()+create_task 非原子 | 同 §async-import：单用户场景下可接受，注释明确说明 |
| 删除旧 API 破坏外部调用方 | 项目仅有前端调用，前端同步修改即可 |
| 旧 in-memory 预览数据丢失 | 旧数据本来就不持久化，无影响 |
| Postgres ON CONFLICT 与 SQLite 行为差异 | 用 ORM `select + add/update`，不依赖数据库特定 ON CONFLICT 语法 |

---

## 10. 后续工作（不在本次范围）

1. 定时扫描 cron job：周期性触发 scan，依赖本次的 candidate 表
2. 候选合并 / 拆分（如果遇到同一资源被多关键词命中需要保留多条记录）
3. 候选历史回溯（now/历史 duplicate_status 对比）
4. Web Push 通知 job 完成
5. 关键词命中度统计页面

---

## 11. 设计决策依据汇总

回答用户在 brainstorm 过程中的关键问题：

1. **架构**：后台 job + SSE → 复用已落地的 async-import 模式，零新依赖
2. **错误**：跳过失败项继续，末尾汇总 → 单条不阻断
3. **预览复用**：候选持久化 + UI 勾选发 candidate_ids → 后台不重跑预览
4. **范围**：同时做账本 + 页面拆分 + 自动循环 → 为 cron 任务铺底
5. **扫描复用粒度**：低成本状态跳过 + 高成本重新评估
6. **扫描作业模式**：scan 也是 job
7. **dismissed 语义**：标 dismissed 状态，下次跳过，支持恢复
8. **并发**：scan_lock + submit_lock 各一把，互不阻塞
9. **tree_import 关系**：candidate 不绑定 tree_import，记录 last_scanned_tree_import_id
10. **数据模型**：新表 + magnet_task_id 外键（方案 A）
