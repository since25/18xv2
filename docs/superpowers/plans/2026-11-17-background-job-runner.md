# 后台任务统一启动器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 9 个后台长任务的“判重 → 建记录 → 后台执行 → 写进度 → 成败收尾 → 推送 → 清理”收敛到服务层一个统一启动器，并让后台任务改用全局 115 客户端。

**Architecture:** 新增 `app/services/job_runner.py`，以 `app/services/jellyfin/job_runner.py` 现有写法为蓝本。路由只负责参数校验、把 `JobAlreadyRunning` 转成 409、把“干活函数”交给启动器。进度只认 `background_jobs` 表。

**Tech Stack:** FastAPI、SQLAlchemy 2（同步 Session）、pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-11-17-background-job-runner-design.md`（执行前必须先读）

## Global Constraints

- 不改任何接口地址、请求参数、返回格式；`frontend/` 下一个文件都不改。
- 不改数据库表结构，不新增 alembic 迁移。
- 不改常驻循环的调度逻辑（`app/main.py` 的下载器同步循环、`jellyfin_daily_loop`、`jellyfin_cover_daily_loop`）。
- 单进程前提；判重 = 进程内 `threading.Lock` + 查库同类型未完成任务。
- 代码注释、docstring 用中文。保持现有代码风格，不顺手重构无关代码。
- **不做任何 git 操作**（不 add、不 commit、不切分支）。每个任务结束只跑测试。
- 测试只在 Spark 上跑：`scripts/remote-test.sh backend [pytest 参数]`。每次只启动一次并前台等待结束，不要 sleep/tail 轮询。本机不跑 pytest。
- 对外展示的任务类型名不变：白名单仍是 `scan` / `submit`，去重仍是 `scan` / `confirm` / `delete`（库里存 `whitelist:scan`、`dedupe:scan` 等带前缀的名字）。
- 现有测试改写时，每个用例验证的行为必须保留；不允许靠删除用例让测试通过。

## Review Focus

1. 干活函数在数据库事务出错后抛异常（会话处于失败状态）→ 启动器必须先回滚再写失败记录，记录最终 `done=True` 且带错误信息。（Task 1 测试）
2. 两次启动同类型任务 → 第二次抛 `JobAlreadyRunning`，库里只有一条未完成记录。（Task 1 测试）
3. 干活函数返回 `None`、或返回无法转成 JSON 的摘要 → 任务仍被标记完成，不留“运行中”记录。（Task 1 测试）
4. 推送进行中任务记录被清理循环删除 → 推送一帧“未找到”后正常结束，不抛异常。（Task 1 测试）
5. 目录导入判重失败 → 不留下状态为 `pending` 的导入批次记录。（Task 4 测试）

---

## File Structure

- 新建 `app/services/job_runner.py`：统一启动器（判重、建记录、执行、收尾、推送、清理）。
- 新建 `tests/services/test_job_runner.py`：启动器测试。
- 修改 `app/api/routes/whitelist_batch.py`、`app/api/routes/dedupe.py`、`app/api/routes/imports.py`、`app/api/routes/jellyfin.py`：改用启动器。
- 修改 `app/services/jellyfin/job_runner.py`：判重上移，保留干活函数和每日循环。
- 修改 `app/main.py`：只启动一个清理循环，从服务层导入。
- 修改对应测试：`tests/whitelist/test_whitelist_batch_routes.py`、`tests/api/test_dedupe_routes.py`、`tests/api/test_imports_async.py`、`tests/jellyfin/test_job_runner.py`、`tests/jellyfin/test_routes.py`（按需）。

---

### Task 1: 统一启动器

**Files:**
- Create: `app/services/job_runner.py`
- Test: `tests/services/test_job_runner.py`

**Interfaces（后续任务都依赖这些名字）:**

```python
class JobAlreadyRunning(Exception): ...          # 同类型任务已在运行

ProgressCallback = Callable[[str, int, int], None]   # (stage, current, total)
JobWork = Callable[[Session, ProgressCallback], Any] # 返回摘要：dict / pydantic 模型 / dataclass / None

def create_job(db: Session, job_type: str, *, job_id: str | None = None) -> str
    # 进程内锁保护下：BackgroundJobService.list_active(db, job_type) 非空则抛 JobAlreadyRunning；
    # 否则 BackgroundJobService.create(db, job_id or uuid4 字符串, job_type)，返回 job_id。

def run_job(job_id: str, work: JobWork) -> None
    # 在当前线程同步执行。自己开独立数据库会话（运行时从 app.db.session 取 SessionLocal，
    # 不要在模块顶层绑定，测试会替换它）。进度回调调用 BackgroundJobService.update(session, job_id, stage=, current=, total=)。
    # 成功：stage="完成"、done=True、error=None、summary=归一化后的摘要、finished_at=now(UTC)；不改 current/total。
    # 失败：先 session.rollback()，再写 stage="失败"、error=str(exc)、done=True、finished_at；logger.exception。
    # 任何情况下不向外抛异常。

def submit_job(job_id: str, work: JobWork) -> threading.Thread
    # 起一个 daemon 线程执行 run_job(job_id, work)，返回该线程（测试用 join 等待）。

async def job_event_stream(job_id: str, *, transform: Callable[[dict], dict] | None = None) -> AsyncIterator[str]
    # 每秒读库一次，产出 "data: <json>\n\n"（ensure_ascii=False）。
    # 记录不存在：产出 {"error": "not found"} 后结束。done 后再产出一帧然后结束。

async def sweep_expired_jobs(*, interval_seconds: int = 60, retention_seconds: int = 600) -> None
    # 循环：sleep(interval) → BackgroundJobService.purge_expired(session, retention)。
    # CancelledError 时退出；其它异常 logger.exception 后继续。
```

摘要归一化：pydantic 模型用 `model_dump()`，dataclass 用 `dataclasses.asdict`，dict 原样，`None` 原样；归一化或 JSON 序列化失败时摘要记为 `None`，任务仍按成功收尾。

- [ ] **Step 1: 写失败测试** `tests/services/test_job_runner.py`。数据库夹具参照 `tests/jellyfin/test_job_runner.py` 的做法。用例与断言：
  - `test_run_job_marks_success_with_summary`：work 返回 `{"n": 3}` → 记录 `done is True`、`stage == "完成"`、`summary == {"n": 3}`、`error is None`、`finished_at` 非空。
  - `test_run_job_progress_callback_persists`：work 内调用 `cb("扫描", 2, 5)` → 执行中读库得到 `stage == "扫描"`、`current == 2`、`total == 5`。
  - `test_run_job_marks_failure_and_does_not_raise`：work 抛 `RuntimeError("boom")` → `run_job` 不抛；记录 `done is True`、`stage == "失败"`、`error == "boom"`。
  - `test_run_job_rolls_back_broken_session_before_marking_failure`：work 内执行一条必然失败的 SQL（如查询不存在的表）后让异常抛出 → 记录仍被写成失败且 `done is True`。
  - `test_run_job_none_or_unserializable_summary_still_completes`：work 返回 `None`，以及返回 `{"x": object()}` 两种 → 均 `done is True`、`stage == "完成"`、`summary is None`。
  - `test_run_job_accepts_pydantic_and_dataclass_summary`：分别返回 pydantic 模型和 dataclass → `summary` 为对应字典。
  - `test_create_job_rejects_second_job_of_same_type`：同类型第二次 `create_job` 抛 `JobAlreadyRunning`；库里该类型未完成记录数为 1；不同类型可以并存。
  - `test_create_job_allows_new_job_after_previous_done`：前一个完成后可再建。
  - `test_create_job_uses_given_job_id`：传 `job_id="42"` 返回 `"42"`。
  - `test_submit_job_runs_in_background_thread`：`submit_job(...).join(timeout=5)` 后记录 `done is True`。
  - `test_job_event_stream_unknown_job`：产出一帧含 `"not found"` 后结束。
  - `test_job_event_stream_done_job_emits_then_stops`：对已完成任务，产出的帧都含 `"done": true`，且生成器会结束（把 `asyncio.sleep` 替换掉避免真等）。
  - `test_job_event_stream_applies_transform`：transform 把 `job_type` 改名后，帧里是改后的值。
  - `test_job_event_stream_row_deleted_midway`：第一帧后删除记录 → 下一帧是 `not found`，随后结束。
- [ ] **Step 2: 跑测试确认失败** `scripts/remote-test.sh backend tests/services/test_job_runner.py`，预期因模块不存在而失败。
- [ ] **Step 3: 实现** `app/services/job_runner.py`，按上面的 Interfaces。
- [ ] **Step 4: 跑测试确认通过** 同 Step 2 命令，预期全部通过。

### Task 2: 白名单批处理迁移（含 115 客户端）

**Files:**
- Modify: `app/api/routes/whitelist_batch.py`
- Test: `tests/whitelist/test_whitelist_batch_routes.py`

**Interfaces:** Consumes Task 1 的 `create_job`、`submit_job`、`job_event_stream`、`JobAlreadyRunning`。Produces: 无。

- [ ] **Step 1: 改写测试**。把直接操作 `_wb._jobs`、`_wb._scan_lock`、`_wb._submit_lock` 的用例改成通过 `background_jobs` 记录构造和断言（如“已有扫描在跑返回 409”改为先插入一条未完成的 `whitelist:scan` 记录）。新增 `test_scan_and_submit_jobs_use_singleton_115_client`：用 `app.dependency_overrides[get_115_client]` 注入一个哨兵对象，断言干活函数构造 `MagnetDownloadService` 时拿到的 `client_115` 就是该哨兵。
- [ ] **Step 2: 跑测试确认失败** `scripts/remote-test.sh backend tests/whitelist`。
- [ ] **Step 3: 改实现**：
  - 删除 `_scan_lock`、`_submit_lock`、`_jobs`、`_new_job`、`_run_scan_job`、`_run_submit_job`、`_run_blocking_job`、`_blocking_scan`、`_blocking_submit`、`_sweep_jobs` 及相关常量。
  - `start_scan_job` / `start_submit_job`：增加依赖 `client: Real115Client = Depends(get_115_client)`；`create_job(db, "whitelist:scan" | "whitelist:submit")`，`JobAlreadyRunning` → 409（文案沿用现有两句）；`submit_job(job_id, work)`，work 内构造 `WhitelistCandidateService` 并调用 `scan` / `submit_selected`，返回其摘要。返回体仍为 `{"job_id": ..., "status": "pending"}`。
  - `_make_magnet_svc(session, client)`：改为接收传入的 client，不再 `Real115Client()`。
  - `job_progress`：返回 `StreamingResponse(job_event_stream(job_id, transform=_public_state), media_type="text/event-stream")`。
  - `active_jobs`：只查库，去掉内存回退。保留 `_public_state`、`_job_type_matches`。
- [ ] **Step 4: 跑测试确认通过** `scripts/remote-test.sh backend tests/whitelist tests/services/test_job_runner.py`。

### Task 3: 文件去重迁移（含 115 客户端）

**Files:**
- Modify: `app/api/routes/dedupe.py`
- Test: `tests/api/test_dedupe_routes.py`

**Interfaces:** 同 Task 2。

- [ ] **Step 1: 改写测试**，方式同 Task 2。新增 `test_confirm_and_delete_jobs_use_singleton_115_client`：注入哨兵 client，断言 `DedupeConfirmationService` 和 `DedupeDeletePlanService` 收到的就是它。
- [ ] **Step 2: 跑测试确认失败** `scripts/remote-test.sh backend tests/api/test_dedupe_routes.py`。
- [ ] **Step 3: 改实现**：
  - 删除三把锁、`_jobs`、`_new_job`、三组 `_run_*_job` / `_blocking_*`、`_sweep_jobs`。
  - 三个启动接口用 `create_job(db, "dedupe:scan" | "dedupe:confirm" | "dedupe:delete")` + `submit_job`；409 文案沿用现有三句。`start_confirm_job`、`start_delete_job` 增加依赖 `client: Real115Client = Depends(get_115_client)` 并传入服务。
  - 为保持现有进度显示，干活函数在开始和结束时调用进度回调，值与现状一致：扫描开始 `cb("本地文件名扫描", 0, 0)`、结束 `cb("完成", summary.total_files, summary.total_files)`；确认开始 `cb("远端确认", 0, len(candidate_ids))`、结束 `cb("完成", summary.requested, summary.requested)`；删除开始 `cb("限流删除", 0, 0)`、结束 `cb("完成", summary.total, summary.total)`。摘要直接返回 dataclass。
  - `start_delete_job` 的 `confirm` 校验（400）保持在判重之前。
  - `job_progress` 用 `job_event_stream(job_id, transform=_public_state)`；`_active_job` 只查库。
- [ ] **Step 4: 跑测试确认通过** `scripts/remote-test.sh backend tests/api/test_dedupe_routes.py tests/dedupe`。

### Task 4: 目录导入迁移

**Files:**
- Modify: `app/api/routes/imports.py`
- Test: `tests/api/test_imports_async.py`

**Interfaces:** 同 Task 2。

- [ ] **Step 1: 改写测试**。去掉对 `_imports._progress`、`_imports._import_lock` 的直接操作。新增 `test_remote_fetch_conflict_leaves_no_pending_import`：库里已有未完成的 `remote_import` 任务时请求返回 409，且 `tree_imports` 表没有新增记录。
- [ ] **Step 2: 跑测试确认失败** `scripts/remote-test.sh backend tests/api/test_imports_async.py`。
- [ ] **Step 3: 改实现**：
  - 删除 `_import_lock`、`_progress`、`_PROGRESS_RETENTION_SECONDS`、`_prune_progress`、`_run_import`、`_blocking_import`。
  - `remote_fetch_tree`：`db.add(tree_import)` 后 `db.flush()` 取得编号 → `create_job(db, "remote_import", job_id=str(tree_import.id))`；抛 `JobAlreadyRunning` 时 `db.rollback()` 并返回 409（文案沿用）。成功后 `submit_job`。返回体仍为 `{"import_id": ..., "status": "pending"}`。保留 `BackgroundJobService.purge_expired(db)` 调用。
  - 干活函数：调用 `RemoteTreeFetchService(session).fetch_subtree(..., progress_cb=cb)`；捕获异常时把该 `TreeImport.status` 置为 `"failed"` 并提交（这一步自身失败只记 warning），然后把原异常继续抛出交给启动器。
  - `import_progress`：`job_event_stream(str(import_id))`。
- [ ] **Step 4: 跑测试确认通过** `scripts/remote-test.sh backend tests/api/test_imports_async.py tests/importer`。

### Task 5: Jellyfin 迁移

**Files:**
- Modify: `app/services/jellyfin/job_runner.py`、`app/api/routes/jellyfin.py`
- Test: `tests/jellyfin/test_job_runner.py`、`tests/jellyfin/test_routes.py`

**Interfaces:** Consumes Task 1。Produces（保持现有名字，供每日循环和测试继续使用）：`start_job(db, job_type) -> str`、`run_scan_job(job_id)`、`run_sync_job(job_id)`、`run_cover_job(job_id)`、`JobAlreadyRunning`（从 `app.services.job_runner` 重新导出，保证是同一个类）。

- [ ] **Step 1: 先跑现有测试作为基线** `scripts/remote-test.sh backend tests/jellyfin`，预期全部通过。
- [ ] **Step 2: 改实现**：
  - `start_job` 改为直接调用 `create_job`；删除 `_job_start_lock` 和本地的 `JobAlreadyRunning` 定义。
  - 三个 `run_*_job(job_id)` 改为 `run_job(job_id, <干活函数>)`；干活函数里保留各自的配置检查和客户端生命周期管理，开始时 `cb("扫描中" | "同步中" | "生成封面中", 0, 0)`，结束时 `cb("完成", 1, 1)`，返回摘要字典。删除 `_mark_success`、`_mark_failure`。
  - 路由 `trigger_scan` / `trigger_sync`：去掉 `BackgroundTasks` 参数，改为 `submit_job(job_id, <干活函数>)`。状态码和返回体不变。
  - 两个每日循环不改调度逻辑，仍用 `asyncio.to_thread(run_*_job, job_id)`。
- [ ] **Step 3: 调整测试**中因内部结构变化而失效的替换点（如替换 `SessionLocal` 的位置），每个用例验证的行为保持不变。
- [ ] **Step 4: 跑测试确认通过** `scripts/remote-test.sh backend tests/jellyfin`。

### Task 6: 启动代码收尾与全量验证

**Files:**
- Modify: `app/main.py`
- Modify（如有相关描述）: `docs/DEVELOPMENT_GUIDE.md`

- [ ] **Step 1: 改 `app/main.py`**：删除从 `app.api.routes.whitelist_batch` 和 `app.api.routes.dedupe` 导入 `_sweep_jobs` 的两段；改为从 `app.services.job_runner` 导入 `sweep_expired_jobs`，只启动一个，存到 `app.state.job_sweeper`；关闭时取消它。删除 `app.state.whitelist_job_sweeper`、`app.state.dedupe_job_sweeper`。若有测试引用旧属性名，同步修改。
- [ ] **Step 2: 检查残留**：在 `app/` 下搜索 `Real115Client()`，除 `app/main.py` 的 lifespan 外不应再有；搜索 `_sweep_jobs`、`_jobs`、`_progress`、`BackgroundTasks`，路由文件中不应再有。
- [ ] **Step 3: 更新文档**：`docs/DEVELOPMENT_GUIDE.md` 中若有后台任务/异步导入写法的说明，改为指向 `app/services/job_runner.py` 并写明新增长任务的做法（三步：`create_job` → `submit_job` → 用 `job_event_stream` 推送）；没有相关章节则新增一小节。不写真实数据。
- [ ] **Step 4: 全量后端测试** `scripts/remote-test.sh backend`，预期退出码 0。
- [ ] **Step 5: 全量前端测试** `scripts/remote-test.sh frontend`，预期退出码 0（确认前端未受影响）。
- [ ] **Step 6: 汇报**：列出改动文件、每个任务的测试结果（通过数、日志路径）、与计划不一致的地方及原因、未能完成或未验证的部分。
