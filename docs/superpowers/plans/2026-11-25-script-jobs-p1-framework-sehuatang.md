# 脚本中心第一段（执行框架 + sehuatang）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 18x 能调度、执行、停止、监控脚本，并实时看日志、调整参数；先把 sehuatang 完整搬进来，替代 Unraid 上的 `sehuatang` 定时脚本。

**Architecture:**
- 18x 进程里有一个执行器单例和一个调度协程。执行器为每次运行起一个独立子进程（自成进程组），日志直接写文件；子进程结束后，调用对应任务的收尾函数，把结果写进阶段 6 的 `script_runs` / `script_run_items`。
- sehuatang 是仓库内的独立模块，子进程入口只依赖站点抓取、qB 接口和标准库，不连数据库：
  - 输入：执行器写好的 `input.json`（参数、黑名单词、已提交帖子编号）；
  - 输出：`result.json`。
- MOVE、DEL 在本段只把配置建进库，并接管“到点没跑”的判断，执行留给第二、三段计划。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、pytest、`curl_cffi`、`beautifulsoup4`、`httpx`；React + antd + vitest。

**Spec:** `docs/superpowers/specs/2026-11-25-scripts-into-18x-design.md`（已批准）。阶段 6 的设计见 `docs/superpowers/specs/2026-11-02-script-run-reports-design.md`。

**拆分说明：** 设计覆盖三个脚本。本计划是第一段，做框架和 sehuatang；第二段（MOVE）、第三段（DEL 和 docker 挂载）在 sehuatang 切换完成后，各写一份计划。

## Global Constraints

- 代码注释、docstring、文档、提交说明都用中文。
- 测试只在 Spark 上跑：后端用 `scripts/remote-test.sh backend [pytest 参数]`，前端用 `scripts/remote-test.sh frontend`。本机不跑 pytest 和 vitest。
- 后端接口或数据模型改动后，运行 `scripts/gen-api-types.sh`，把 `frontend/openapi.json` 和 `frontend/src/api/schema.gen.ts` 一起提交；`tests/api/test_openapi_snapshot.py` 会检查两者是否一致。
- 脚本名固定为 `sehuatang`、`MOVE_SSD_CACHE_TO_DISK2`、`DEL_SOMETHING`，和阶段 6 已有记录保持一致。
- 时区一律按 `Asia/Shanghai` 判断“今天”和运行时间；数据库存 UTC。
- 默认运行时间：`sehuatang` 01:28、`MOVE_SSD_CACHE_TO_DISK2` 01:01、`DEL_SOMETHING` 12:09。三条配置的执行方初始都是 `unraid`。
- 超时：sehuatang 3600 秒，MOVE 21600 秒，DEL 10800 秒。停止时先发 SIGTERM，30 秒后仍在运行再发 SIGKILL。
- 补跑窗口：预定时间后 2 小时内。
- 名单最多保存 5000 条、保留 90 天；日志保留 30 天。
- cookie、User-Agent 以外的会话内容、qB 密码，不能出现在日志、接口返回、运行名单、测试夹具或仓库里。测试夹具里的标题和路径全部虚构。
- 不新增 WebSocket；实时日志靠前端每 2 秒轮询一次。
- 未经用户在对话里明确同意，不做 `git push`、不部署、不改生产机。

## Review Focus

1. **uvicorn 被 supervisord 重启、但容器没重启时，旧的子进程还在跑。** 启动恢复要先按记录里的 pid 结束整个进程组，再把记录标成“中断”。否则补跑会和旧进程同时跑。测试放在 Task 4。
2. **日志里中文多字节字符正好被切在读取边界上。** 按偏移读取时，不能出现乱码，也不能丢字。测试放在 Task 4。
3. **还没设置站点 cookie 就运行了 sehuatang。** 运行应该以“尚未设置站点 cookie”失败，页面红条显示这句话，而不是子进程崩溃退出。测试放在 Task 7。
4. **标题里的黑名单词是全角字母或大小写混写**（例如 `ＡＩ增强`、`Ai增强`）。也要拦下：标题和词都先做 NFKC 归一，再去空格、转小写。测试放在 Task 6。
5. **qB 登录失败。** 本次运行记为失败，任何帖子都不能记成“已提交”，第二天还会重新尝试提交。测试放在 Task 7 和 Task 8。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `alembic/versions/20261125_0018_script_jobs.py` | 新表、新字段、三条默认配置 |
| `app/models/script_runs.py`（改） | `ScriptRun` 新字段；新增 `ScriptJobConfig`、`ScriptJobConfigChange`、`SehuatangPost` |
| `app/schemas/script_runs.py`（改） | 状态、计数和名单类别的扩展 |
| `app/schemas/script_jobs.py` | 配置、参数、手动运行、日志、站点会话的请求和响应 |
| `app/services/script_jobs/definitions.py` | 三个任务的定义：默认值、互斥组、超时、参数模型、是否可在 18x 执行 |
| `app/services/script_jobs/config_service.py` | 读取和修改配置，记录修改前后 |
| `app/services/script_jobs/run_store.py` | 运行记录的创建、收尾和状态汇总（阶段 6 的 `_counts_dict` 等搬到这里） |
| `app/services/script_jobs/logs.py` | 运行目录、按偏移读日志、30 天清理 |
| `app/services/script_jobs/runner.py` | 执行器：启动、排队、互斥、停止、超时、收尾、启动恢复 |
| `app/services/script_jobs/scheduler.py` | `due_jobs` 判断和调度协程 |
| `app/services/script_jobs/site_session.py` | sehuatang 站点 cookie 和 User-Agent 的文件存取 |
| `app/services/script_jobs/sehuatang_task.py` | sehuatang 在 18x 侧的准备（写 `input.json`）和收尾（读 `result.json`、写帖子表） |
| `app/services/script_jobs/sehuatang/matching.py` | 标题和文件名的归一与命中 |
| `app/services/script_jobs/sehuatang/torrent.py` | 解析种子里的文件名 |
| `app/services/script_jobs/sehuatang/pages.py` | 解析列表页、帖子页、安全验证页和 Cloudflare 挑战页 |
| `app/services/script_jobs/sehuatang/site.py` | 基于 `curl_cffi` 的站点访问 |
| `app/services/script_jobs/sehuatang/qb.py` | 基于 `httpx` 的 qB WebAPI 访问 |
| `app/services/script_jobs/sehuatang/job.py` | 主流程 `run_job` |
| `app/services/script_jobs/sehuatang/main.py` | 子进程入口 |
| `app/api/routes/script_runs.py`（改） | 汇总改按配置表；新增停止和日志接口 |
| `app/api/routes/script_jobs.py` | 配置、手动运行、站点会话接口 |
| `app/main.py`（改） | 注册路由；lifespan 启动执行器、调度协程和启动恢复 |
| `app/core/config.py`（改） | `QB_URL`、`QB_USERNAME`、`QB_PASSWORD`、`SCRIPT_JOBS_DIR`、`SEHUATANG_SESSION_PATH`；删除 `SCRIPT_REPORT_SCHEDULES` |
| `scripts/seed_sehuatang_posts.py` | 切换时导入最近 14 天 CSV 里的帖子编号 |
| `frontend/src/api/scriptJobs.ts`、`frontend/src/api/scriptRuns.ts`（改） | 前端接口 |
| `frontend/src/pages/ScriptRunsPage.tsx`（改）和 `frontend/src/pages/scriptCenter/*` | 「脚本中心」页面 |
| `docs/script-jobs.md`、`docs/unraid-script-reports.md`（改） | 部署和使用说明 |

---

### Task 1: 数据模型、迁移和依赖

**Files:**
- Create: `alembic/versions/20261125_0018_script_jobs.py`
- Modify: `app/models/script_runs.py`、`pyproject.toml`、`tests/conftest.py`（不用改：`script_runs` 模型模块已经导入）
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces（模型，字段名后面各任务都会用到）：
  - `ScriptRun` 新增 `trigger: str`（`report` / `scheduled` / `manual`，默认 `report`）、`dry_run: bool`（默认 False）、`log_path: str | None`、`error_reason: str | None`、`pid: int | None`；`finished_at`、`exit_code` 改为可空。`status` 取值扩展为 `queued`、`running`、`success`、`warning`、`failed`、`stopped`、`interrupted`。
  - `ScriptJobConfig(job_name: str 唯一, executor: str, enabled: bool, run_time: str, params: dict, updated_at: datetime)`，表名 `script_job_configs`。
  - `ScriptJobConfigChange(job_name: str, changed_at: datetime, before: dict, after: dict)`，表名 `script_job_config_changes`。
  - `SehuatangPost(tid: str 唯一, title: str, url: str, first_seen_at: datetime, last_outcome: str, last_run_id: int | None 外键 script_runs.id ON DELETE SET NULL, submitted_at: datetime | None, updated_at: datetime)`，表名 `sehuatang_posts`。

- [ ] **Step 1: 写失败的迁移测试** `test_script_jobs_migration_upgrades_and_downgrades`

照 `test_script_runs_migration_upgrades_and_downgrades` 的写法：先执行 0017，再执行 0018。断言：
- 三张新表存在；`script_runs` 有 `trigger`、`dry_run`、`log_path`、`error_reason`、`pid` 五列；
- `script_job_configs` 正好 3 行，`job_name` 集合是 `{"sehuatang", "MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING"}`，`executor` 全是 `unraid`，`enabled` 全是 False，`run_time` 分别是 `01:28`、`01:01`、`12:09`；
- sehuatang 的 `params` 等于 `{"pages": 4, "forum_url": "https://sehuatang.org/forum.php?mod=forumdisplay&fid=2&typeid=684&filter=typeid&page={page}", "qb_category": "国产BT"}`；
- 执行 0018 downgrade 后，三张新表消失、五个新列消失，0017 的表仍然在。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/test_migrations.py -q`
Expected: FAIL，提示找不到 `20261125_0018_script_jobs.py`。

- [ ] **Step 3: 写迁移和模型**

- 迁移：`revision="20261125_0018"`，`down_revision="20261102_0017"`。修改 `script_runs` 用 `op.batch_alter_table`，SQLite 和 PostgreSQL 都要能跑。
- 默认数据：在迁移里用字面量写入，不能 import 应用代码。
- MOVE 的 `params`：`{"source_dir": "/mnt/cache/docker1/SSD_cache/已整理", "target_dir": "/mnt/disk2/qbbtdn/已整理"}`。
- DEL 的 `params`：
  - `delete_dirs`：`target_dirs.csv` 里的 3 条，写法见设计第六节第 2 小节；
  - `organize_jobs`：7 条 `{"scan_root": ..., "target_root": ...}`，顺序和设计第六节第 2 小节一致；
  - `merge_on_conflict: true`；
  - `fix_permissions: true`。
- `pyproject.toml` 的 dependencies 加 `"curl_cffi>=0.7.0"` 和 `"beautifulsoup4>=4.12.0"`。

- [ ] **Step 4: 运行，确认通过**

Run: `scripts/remote-test.sh backend tests/test_migrations.py -q`
Expected: PASS，而且 Spark（ARM64）上能装上 `curl_cffi`。

- [ ] **Step 5: 提交**

```bash
git add alembic/versions/20261125_0018_script_jobs.py app/models/script_runs.py pyproject.toml tests/test_migrations.py
git commit -m "feat: 脚本中心数据表与 sehuatang 依赖"
```

---

### Task 2: 任务定义和配置接口

**Files:**
- Create: `app/services/script_jobs/__init__.py`、`definitions.py`、`config_service.py`、`app/schemas/script_jobs.py`、`app/api/routes/script_jobs.py`
- Modify: `app/main.py`（注册路由，挂载方式和 `script_runs` 路由相同）
- Test: `tests/script_jobs/test_config_service.py`、`tests/api/test_script_jobs_routes.py`

**Interfaces:**
- Produces:
  - `definitions.py`：
    - `JOB_NAMES: tuple[str, ...]`，按 `("sehuatang", "MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING")` 排序；
    - `ALLOWED_ROOTS = ("/mnt/cache/docker1/SSD_cache", "/mnt/disk2/qbbtdn")`；
    - `@dataclass(frozen=True) JobDefinition(name, label, group, timeout_seconds, runnable, params_model)`；
    - `get_definition(name: str) -> JobDefinition`，名称未知时抛 `KeyError`。
    - 取值：

      | 任务 | label | group | runnable（本段） |
      |---|---|---|---|
      | sehuatang | 色花堂抓取 | sehuatang | True |
      | MOVE_SSD_CACHE_TO_DISK2 | 搬运脚本 | media | False |
      | DEL_SOMETHING | 整理脚本 | media | False |

  - 参数模型（pydantic）：
    - `SehuatangParams(pages: int 取 1–20, forum_url: str 必须以 https:// 开头并包含 "{page}", qb_category: str 1–64 字且去掉首尾空白后不为空)`；
    - `MoveParams(source_dir, target_dir)`；
    - `OrganizeJob(scan_root, target_root)`；
    - `DelParams(delete_dirs: list[str] 1–20 条, organize_jobs: list[OrganizeJob] 0–30 条, merge_on_conflict: bool, fix_permissions: bool)`。
    - 所有目录必须是绝对路径，规范化后与原值相同（不含 `..`），并且等于或位于 `ALLOWED_ROOTS` 之一下面。
  - `config_service.py`：
    - `list_configs(db) -> list[ScriptJobConfig]`；
    - `get_config(db, job_name) -> ScriptJobConfig`；
    - `update_config(db, job_name, *, enabled: bool | None, run_time: str | None, executor: str | None, params: dict | None) -> ScriptJobConfig`。参数校验失败抛 `ValueError`（中文原因）；`executor="18x"` 而任务 `runnable=False` 时抛 `ValueError("该脚本尚未支持在 18x 执行")`；值有变化时写一条 `ScriptJobConfigChange`，before 和 after 是完整配置字典。
  - 接口：
    - `GET /script-jobs` 返回 `{"items": [ScriptJobView...]}`，字段在本任务先返回 `job_name, label, executor, enabled, run_time, params, runnable, next_run_at`；Task 5 补 `active_run`、`latest_run`、`alert`，Task 8 补 `site_session`。
    - `PUT /script-jobs/{job_name}` 的请求体 `ScriptJobUpdate`（四个字段都可选），校验失败返回 400，响应是 `detail` 中文原因。
    - `GET /script-jobs/{job_name}/changes?limit=20` 返回修改记录。
    - `next_run_at`：执行方为 18x 且已启用时，给出下一次的 UTC ISO 时间；否则为 null。

- [ ] **Step 1: 写失败测试**

```python
def test_update_rejects_dir_outside_allowed_roots(db_session):
    seed_default_configs(db_session)  # 测试辅助：插入与迁移相同的三条默认配置
    with pytest.raises(ValueError, match="挂载"):
        update_config(db_session, "MOVE_SSD_CACHE_TO_DISK2", enabled=None, run_time=None, executor=None,
                      params={"source_dir": "/mnt/user/other", "target_dir": "/mnt/disk2/qbbtdn/已整理"})

def test_update_rejects_parent_traversal(db_session): ...  # "/mnt/disk2/qbbtdn/../x" 被拒
def test_update_rejects_18x_executor_for_unrunnable_job(db_session): ...  # DEL 改 executor="18x" 抛 ValueError
def test_update_records_change_with_before_and_after(db_session):
    # sehuatang pages 4→6 后，changes 有 1 条，before["params"]["pages"]==4，after==6
def test_update_without_change_writes_no_record(db_session): ...
def test_run_time_must_be_hh_mm(db_session): ...  # "1:28"、"24:00"、"aa" 都被拒，"01:28" 通过
def test_forum_url_requires_page_placeholder(db_session): ...
```

接口测试 `tests/api/test_script_jobs_routes.py`，客户端夹具照抄 `test_script_runs_routes.py`：
- `GET /script-jobs` 返回 3 项，顺序和 `JOB_NAMES` 一致；
- `PUT` 不合法参数返回 400，并且 `detail` 含中文；
- 执行方为 unraid 时 `next_run_at is None`；改成 18x 并启用后，`next_run_at` 不为空。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs tests/api/test_script_jobs_routes.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现上面 Interfaces 里列的函数和路由**

- [ ] **Step 4: 运行，确认通过**（同 Step 2 的命令，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs app/schemas/script_jobs.py app/api/routes/script_jobs.py app/main.py tests/script_jobs tests/api/test_script_jobs_routes.py
git commit -m "feat: 脚本中心任务定义与配置接口"
```

---

### Task 3: 运行记录扩展与“到点没跑”改按配置表

**Files:**
- Create: `app/services/script_jobs/run_store.py`
- Modify: `app/schemas/script_runs.py`、`app/api/routes/script_runs.py`、`app/core/config.py`（删除 `script_report_schedules`）
- Test: `tests/api/test_script_runs_routes.py`（已有用例保持通过，另加新用例）、`tests/script_jobs/test_run_store.py`

**Interfaces:**
- Produces（`run_store.py`，阶段 6 路由里的 `_as_utc`、`_iso`、`_counts_dict`、`_status_for`、`_run_response` 搬到这里，改成公开名）：
  - `as_utc(dt)`、`iso(dt) -> str`；
  - `counts_dict(raw, script_name=None) -> dict[str, int]`；
  - `run_response(run) -> dict`；
  - `create_run(db, *, job_name: str, trigger: str, dry_run: bool, status: str) -> ScriptRun`：`run_key = f"{job_name}:{trigger}:{iso(now)}:{uuid4().hex[:8]}"`，`started_at = now`。
  - `finish_run(db, run, *, exit_code: int | None, status: str, counts: dict, items: list[dict], error_reason: str | None) -> None`：名单截断到 5000 条并设置 `items_truncated`；同时清理 90 天前的名单。
  - `ACTIVE_STATUSES = ("queued", "running")`。
- schema 扩展：
  - `ScriptName` 加 `"sehuatang"`；
  - `ScriptRunItemKind` 加 `"submitted"`、`"title_blocked"`、`"torrent_blocked"`、`"submit_failed"`、`"parse_failed"`；
  - `ScriptRunCounts` 加 `pages_ok`、`pages_failed`、`posts_found`、`title_blocked`、`torrent_blocked`、`skipped_seen`、`submitted`、`submit_failed`、`parse_failed`（都是 `int`，默认 0）；
  - `ScriptRunResponse.status` 扩展到七个取值；`finished_at: str | None`、`exit_code: int | None`；新增 `trigger`、`dry_run`、`error_reason`、`has_log: bool`。
- `GET /script-runs/summary` 的变化：
  - `scripts` 改为按配置表三项输出，每项加 `executor`、`enabled`；
  - `today_status` 按顺序判断：
    1. 今天有非演练记录 → 取最新一条的 `status`；
    2. 执行方为 18x 且未启用 → `disabled`；
    3. 任务是 sehuatang 且执行方为 unraid → `not_tracked`；
    4. 其余 → 照旧 `pending` / `missing`（预定时间加 2 小时前算 `pending`），预定时间取配置表的 `run_time`。
  - 趋势 `days` 只统计非演练记录。

- [ ] **Step 1: 写失败测试**

```python
def test_summary_uses_config_run_time(client, db_session):
    # 把 DEL 的 run_time 改成 "23:59"，在 2026-11-25 13:00（上海时间）请求时 DEL today_status == "pending"
def test_summary_dry_runs_excluded_from_trend_and_today(client, db_session): ...
def test_summary_disabled_18x_job_shows_disabled(client, db_session): ...
def test_summary_sehuatang_under_unraid_is_not_tracked(client, db_session): ...
def test_unraid_report_post_still_accepted_with_trigger_report(client): ...  # 原 POST 返回 trigger=="report"、dry_run is False
def test_finish_run_truncates_items_and_keeps_counts(db_session): ...  # 5001 条 → 保存 5000，items_truncated True
```

当前时间用 monkeypatch 注入。路由里取现在时间统一走 `run_store.now_utc()`，便于测试替换。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/api/test_script_runs_routes.py tests/script_jobs/test_run_store.py -q`
Expected: 新用例 FAIL，旧用例 PASS。

- [ ] **Step 3: 实现**（照 Interfaces；删掉 `SCRIPT_REPORT_SCHEDULES` 和 `_parse_schedules`）

- [ ] **Step 4: 运行，确认全部通过**（同 Step 2 的命令）

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs/run_store.py app/schemas/script_runs.py app/api/routes/script_runs.py app/core/config.py tests/api/test_script_runs_routes.py tests/script_jobs/test_run_store.py
git commit -m "feat: 运行记录支持 18x 执行状态，漏跑判断改按配置表"
```

---

### Task 4: 执行器、日志和停止

**Files:**
- Create: `app/services/script_jobs/logs.py`、`app/services/script_jobs/runner.py`
- Modify: `app/services/script_jobs/definitions.py`（加 `prepare` / `finalize` 钩子类型）、`app/api/routes/script_runs.py`、`app/api/routes/script_jobs.py`、`app/core/config.py`（新增 `script_jobs_dir: str = "data/script-jobs"`，别名 `SCRIPT_JOBS_DIR`）
- Test: `tests/script_jobs/test_logs.py`、`tests/script_jobs/test_runner.py`

**Interfaces:**
- Consumes: Task 2 的 `get_definition`、`get_config`；Task 3 的 `create_run`、`finish_run`、`ACTIVE_STATUSES`。
- Produces:
  - `logs.py`：
    - `run_dir(base: Path, job_name: str, run_id: int) -> Path`，目录是 `<base>/<job_name>/<run_id>/`，日志文件名 `output.log`；
    - `read_log(path: Path, offset: int, limit: int = 65536, *, finished: bool) -> tuple[str, int]`：返回文本和新的偏移。未结束时只返回到最后一个换行；返回的文本一定是完整的 UTF-8 字符；结束后返回剩余全部内容，坏字节用 replace 处理。
    - `cleanup_old_runs(base: Path, now: datetime, days: int = 30) -> int`，按目录修改时间清理。
  - `definitions.py`：
    - `PreparedCommand(argv: list[str], env: dict[str, str])`；
    - `RunContext(run_id: int, job_name: str, params: dict, dry_run: bool, run_dir: Path)`；
    - `RunOutcome(status: str, counts: dict[str, int], items: list[dict], error_reason: str | None)`；
    - `JobDefinition` 增加 `prepare: Callable[[Session, RunContext], PreparedCommand] | None` 和 `finalize: Callable[[Session, RunContext, int], RunOutcome] | None`（第三个参数是退出码）。
  - `runner.py`：
    - 类 `ScriptJobRunner(session_factory, base_dir: Path, *, popen=subprocess.Popen, killpg=os.killpg, clock=run_store.now_utc)`；
    - `start(job_name, *, trigger, dry_run) -> int`：返回 run_id。同名任务已有排队或运行中的记录时抛 `JobBusy`；`runnable=False` 时抛 `ValueError`；执行方为 unraid 且不是演练时抛 `ValueError("由 Unraid 运行的脚本只能演练")`；同组有别的任务在跑时状态为 `queued`，否则立即启动。
    - `stop(run_id) -> None`：排队中的直接记为 `stopped`；运行中的发 SIGTERM 并记下截止时间；不在这两种状态时抛 `RunNotActive`。
    - `poll() -> None`：
      - 回收已结束的进程，调用 `finalize`；
      - 停止请求超过 30 秒还没结束的发 SIGKILL；
      - 超时的按停止处理，最终记为 `failed`，`error_reason="超过运行时限（N 分钟）"`；
      - 同组空闲时启动最早排队的那条。
    - `recover_on_startup() -> int`：对 `running` 且有 pid 的记录先 `killpg(pid, SIGTERM)`，忽略 `ProcessLookupError` 和 `PermissionError`；然后把所有 `running` / `queued` 记为 `interrupted`，`error_reason="18x 重启，任务被中断"`。
  - 启动子进程：`popen(argv, env=..., stdout=日志文件, stderr=subprocess.STDOUT, start_new_session=True, cwd=run_dir)`，pid 写进记录。
  - 用户主动停止的最终状态是 `stopped`，不调 `finalize`，`counts` 为空字典。
  - `finalize` 抛异常时，记为 `failed`，`error_reason="结果整理失败"`，堆栈只写应用日志。
  - 接口：
    - `POST /script-jobs/{job_name}/runs`，请求体 `{"dry_run": bool}`，返回 201 `{"run_id": int, "status": str}`；`JobBusy` 返回 409，`ValueError` 返回 400。
    - `POST /script-runs/{run_id}/stop`，`RunNotActive` 返回 409。
    - `GET /script-runs/{run_id}/log?offset=0`，返回 `{"text": str, "next_offset": int, "finished": bool}`；没有日志时返回 404。
  - 路由通过依赖 `get_script_job_runner(request) -> ScriptJobRunner` 取 `request.app.state.script_job_runner`。

- [ ] **Step 1: 写失败测试**

日志：

```python
def test_read_log_never_splits_multibyte(tmp_path):
    p = tmp_path / "output.log"; p.write_bytes("第一行\n第二".encode())  # 末尾“第二”没有换行
    text, off = read_log(p, 0, finished=False)
    assert text == "第一行\n" and off == len("第一行\n".encode())
    text2, _ = read_log(p, off, finished=True)
    assert text2 == "第二"

def test_read_log_limit_cut_inside_char_backs_off(tmp_path): ...  # limit 落在汉字中间时，回退到字符边界
def test_cleanup_old_runs_removes_only_older_than_30_days(tmp_path): ...
```

执行器（用假的 `popen` 和 `killpg`。假进程类有 `pid`、`poll()`、`send_signal()`，测试可以手动设置退出码；时间用可推进的假时钟）：

```python
def test_second_start_same_job_raises_busy(...)
def test_media_group_queues_second_job_and_starts_after_first_finishes(...)  # 用测试专用的两个 runnable 定义注入
def test_stop_running_sends_sigterm_then_sigkill_after_30s(...)
def test_stop_queued_marks_stopped_without_spawning(...)
def test_timeout_marks_failed_with_reason(...)
def test_finalize_exception_marks_failed(...)
def test_unraid_executor_rejects_real_run_allows_dry_run(...)
def test_recover_on_startup_kills_process_group_then_marks_interrupted(...)  # Review Focus 1：断言 killpg 收到记录里的 pid
```

`test_runner.py` 里用可注入的定义表替换 `get_definition`，不依赖 sehuatang。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs/test_logs.py tests/script_jobs/test_runner.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现**

执行器内部状态（pid 到进程对象、停止截止时间）只放在内存里，数据库是状态的权威来源。所有数据库读写用 `session_factory()` 短会话。

- [ ] **Step 4: 加接口测试并运行**

在 `tests/api/test_script_jobs_routes.py` 里加：手动运行返回 201，重复运行返回 409，停止返回 200，日志读取正常。runner 用假的 `popen` 注入到 `app.state`。

Run: `scripts/remote-test.sh backend tests/script_jobs tests/api -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs/logs.py app/services/script_jobs/runner.py app/services/script_jobs/definitions.py app/core/config.py app/api/routes tests/script_jobs tests/api/test_script_jobs_routes.py
git commit -m "feat: 脚本执行器（子进程、互斥排队、停止、超时、日志）"
```

---

### Task 5: 调度协程、启动恢复和任务视图

**Files:**
- Create: `app/services/script_jobs/scheduler.py`
- Modify: `app/main.py`（lifespan）、`app/api/routes/script_jobs.py`（补 `active_run`、`latest_run`、`alert`）
- Test: `tests/script_jobs/test_scheduler.py`、`tests/api/test_script_jobs_routes.py`

**Interfaces:**
- Consumes: Task 4 的 `ScriptJobRunner`。
- Produces:
  - `due_jobs(configs: list[ScriptJobConfig], today_runs: list[ScriptRun], now: datetime) -> list[str]`（纯函数）。一个任务到期，要同时满足：
    - 执行方是 `18x` 且已启用；
    - 今天的预定时间 ≤ now < 预定时间 + 2 小时（上海时间）；
    - 今天还没有“定时触发、非演练、状态属于 `queued`/`running`/`success`/`warning`/`failed`/`stopped`”的记录。手动运行不算；`interrupted` 不算。
  - `async def script_jobs_loop(runner: ScriptJobRunner, session_factory, *, poll_seconds=2, schedule_seconds=60)`：
    - 每 2 秒调用一次 `runner.poll()`（用 `asyncio.to_thread`）；
    - 每 60 秒算一次 `due_jobs`，逐个 `runner.start(trigger="scheduled", dry_run=False)`，`JobBusy` 时跳过；
    - 每天清理一次 30 天前的运行目录。
    - 单轮出错只记应用日志，循环继续。
  - lifespan：
    - 创建 `ScriptJobRunner(SessionLocal, Path(settings.script_jobs_dir))`，放到 `app.state.script_job_runner`；
    - 调用 `recover_on_startup()`；
    - 启动 `script_jobs_loop`，关闭时取消。写法照 Jellyfin 循环。
  - 任务视图补充：
    - `active_run`：这个任务排队中或运行中的记录（`run_response`），没有时为 null；
    - `latest_run`：最近一条已结束记录，含演练；
    - `alert`：`latest_run` 的状态是 `failed` 时取它的 `error_reason`，否则为 null。

- [ ] **Step 1: 写失败测试**

```python
def test_due_at_run_time(...)                 # 01:28:00 到期
def test_not_due_before_run_time(...)
def test_catch_up_within_two_hours(...)       # 03:27 仍到期
def test_no_catch_up_after_two_hours(...)     # 03:28 不再到期
def test_interrupted_run_allows_rerun(...)
def test_failed_or_stopped_scheduled_run_blocks_rerun(...)
def test_manual_real_run_does_not_block_schedule(...)
def test_dry_run_does_not_block_schedule(...)
def test_unraid_executor_or_disabled_never_due(...)
def test_job_view_alert_from_latest_failed_run(client, db_session): ...
```

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs/test_scheduler.py tests/api/test_script_jobs_routes.py -q`

- [ ] **Step 3: 实现**

- [ ] **Step 4: 运行后端全量**

Run: `scripts/remote-test.sh backend`
Expected: 全部通过。如果有与本任务无关的既有失败，记下来，不算本任务失败，但要在进度日志里写明。

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs/scheduler.py app/main.py app/api/routes/script_jobs.py tests/script_jobs/test_scheduler.py tests/api/test_script_jobs_routes.py
git commit -m "feat: 脚本定时调度、补跑与启动恢复"
```

---

### Task 6: sehuatang 纯逻辑（命中、种子解析、页面解析）

**Files:**
- Create: `app/services/script_jobs/sehuatang/__init__.py`、`matching.py`、`torrent.py`、`pages.py`
- Test: `tests/script_jobs/sehuatang/test_matching.py`、`test_torrent.py`、`test_pages.py`。HTML 夹具放 `tests/script_jobs/sehuatang/fixtures/`，用虚构标题手写的最小页面。

**Interfaces:**
- Produces:
  - `matching.normalize(text: str) -> str`：NFKC，去掉半角、全角空格和制表符，再 `casefold()`。
  - `matching.Term = tuple[str, str]`，即 `(显示词, 归一后)`。
  - `matching.find_hit(text: str, terms: list[Term]) -> str | None`：返回命中词里归一后最长的那个的显示词；长度相同取列表里靠前的；没命中返回 None。
  - `torrent.list_names(data: bytes) -> list[str]`：返回 `info.name`，以及多文件种子里每个文件的 `"/".join(path)`（优先 `path.utf-8`）。不是合法 bencode 或缺 `info` 时抛 `TorrentParseError`。
  - `pages.ListPost(tid: str, title: str, url: str)`，`pages.ThreadLinks(magnets: list[str], attachment_urls: list[str])`：
    - `pages.parse_list(html: str) -> list[ListPost]`：选择器 `a.s.xst`；tid 从 `thread-(\d+)-` 或 `tid=(\d+)` 取；url 以 `https://sehuatang.org/` 开头；同一页里 tid 去重。
    - `pages.parse_thread(html: str) -> ThreadLinks`：磁力正则 `magnet:\?xt=urn:btih:[a-zA-Z0-9]+`，保持顺序去重；附件选 `a[href*="mod=attachment"]`，且文字含 `torrent`（不分大小写）或含 `下载附件`。
    - `pages.extract_safeid(html: str) -> str | None`：页面含 `static/safe/js` 时，取 `var safeid='...'`。
    - `pages.is_challenge(status: int, html: str) -> bool`：含 `_cf_chl_opt`，或状态码是 403 / 503。

- [ ] **Step 1: 写失败测试**

```python
TERMS = [("AI增强", normalize("AI增强")), ("示例演员", normalize("示例演员")), ("示例", normalize("示例"))]

def test_fullwidth_and_mixed_case_hit():   # Review Focus 4
    assert find_hit("【新作】ＡＩ 增强 版", TERMS) == "AI增强"
    assert find_hit("ai增強", [("AI增強", normalize("AI增強"))]) == "AI增強"
def test_longest_term_wins():
    assert find_hit("示例演员的新作", TERMS) == "示例演员"
def test_no_hit_returns_none(): ...
def test_list_names_multi_file_prefers_utf8_path(): ...  # 手工构造 bencode 字节
def test_list_names_rejects_non_bencode(): ...           # b"<html>" 抛 TorrentParseError
def test_parse_list_extracts_tid_title_url_and_dedupes(): ...
def test_parse_thread_magnets_dedup_and_attachment_filter(): ...
def test_extract_safeid_only_on_safe_page(): ...
def test_is_challenge(): ...
```

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs/sehuatang -q`

- [ ] **Step 3: 实现**

bencode 解析自写，不加依赖。

- [ ] **Step 4: 运行，确认通过**（同 Step 2 的命令）

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs/sehuatang tests/script_jobs/sehuatang
git commit -m "feat: sehuatang 标题命中、种子解析与页面解析"
```

---

### Task 7: sehuatang 主流程与子进程入口

**Files:**
- Create: `app/services/script_jobs/sehuatang/site.py`、`qb.py`、`job.py`、`main.py`、`app/services/script_jobs/site_session.py`
- Test: `tests/script_jobs/sehuatang/test_job.py`、`test_qb.py`、`test_main.py`、`tests/script_jobs/test_site_session.py`

**Interfaces:**
- Consumes: Task 6 的全部函数。
- Produces:
  - `site.SiteClient`（Protocol）：`get(url: str, timeout: int) -> SiteResponse(status: int, text: str, content: bytes)`。
  - `site.CurlSiteClient(cookies: dict[str, str], user_agent: str)`：
    - `impersonate="chrome110"`，请求头照搬 `gc.py`，只把 `user-agent` 换成参数；
    - `get` 里按 `gc.py` 的 safe_get 逻辑处理安全验证页：最多重试 2 次，设置 `_safe` cookie。
  - `qb.QbClient(base_url: str, username: str, password: str, *, transport=None)`：
    - `login() -> None`：失败抛 `QbError("qB 登录失败（HTTP 状态码）")`；
    - `add_torrent(data: bytes, filename: str, category: str) -> None`；
    - `add_magnet(url: str, category: str) -> None`；
    - 响应体不是 `Ok.` 时抛 `QbError`，信息只含状态码和响应体前 50 个字符，不含请求内容。
  - `job.JobInput(dry_run: bool, pages: int, forum_url: str, qb_category: str, terms: list[Term], submitted_tids: set[str])`。
  - `job.JobResult(counts: dict[str, int], items: list[dict], fatal_reason: str | None)`：
    - `items` 每项是 `{kind, tid, title, url, keyword, message}`；
    - `counts` 的键见 Task 3 新增的 9 个。
  - `job.run_job(inp: JobInput, site: SiteClient, qb: QbClient | None, *, log: Callable[[str], None], sleep: Callable[[float], None]) -> JobResult`，流程按设计第六节第 4 小节：
    1. 逐页抓列表：状态码 200 记 `pages_ok`，否则记 `pages_failed`；遇到挑战页记下来。翻页后随机等待 10–20 秒。
    2. 所有列表页解析出的帖子数之和记为 `posts_found`。标题命中 → `title_blocked`；tid 在 `submitted_tids` 里 → `skipped_seen`（只计数，不进名单）。
    3. 进帖子前等待 2–4 秒。帖子页抓取或解析出错 → `parse_failed`。
    4. 有种子附件就下载：能解析时，任一文件名命中就记 `torrent_blocked`，否则用种子提交；种子下载或解析失败时退回用磁力。既没有可用种子也没有磁力 → `parse_failed`，message 写“未找到种子或磁力”。
    5. 提交成功 → `submitted`，`message` 写“种子”或“磁力”；`QbError` → `submit_failed`。
    6. `fatal_reason`：
       - `pages_ok == 0` 或 `posts_found == 0` 或出现过挑战页时，写“站点 cookie 可能失效：<具体情况>”，并且不再进帖子；
       - qB 登录失败时写“qB 登录失败”，所有本该提交的帖子都记为 `submit_failed`，不记 `submitted`。
    7. 演练模式：不调用 qB，可以提交的记为 `submitted`，`message` 写“演练，未实际提交”。
  - `site_session.py`：
    - `save_site_session(path: Path, cookie_header: str, user_agent: str) -> datetime`：把 `a=b; c=d` 解析成字典，文件权限 0600；
    - `load_site_session(path: Path) -> SiteSession(cookies: dict[str, str], user_agent: str) | None`；
    - `site_session_status(path: Path) -> {"configured": bool, "updated_at": str | None}`。
  - `main.py`：
    - 命令行 `python -m app.services.script_jobs.sehuatang.main --input <path> --result <path>`；
    - 读取环境变量 `QB_URL`、`QB_USERNAME`、`QB_PASSWORD`、`SEHUATANG_SESSION_PATH`；
    - 用 `site_session.load_site_session`（本任务新建，接口见下）读取 cookie。会话文件不存在时，写一份 `fatal_reason="尚未设置站点 cookie"` 的结果，退出码 0。
    - 正常结束写 `result.json`，退出码 0；未捕获的异常退出码 1。
    - 不 import `app.main`、`app.db` 和任何模型。
    - 打印的内容里不能出现 cookie、密码和完整请求头。

- [ ] **Step 1: 写失败测试**

用假 `SiteClient`（URL 到响应的字典）和假 `QbClient`（记录调用，可设置失败）：

```python
def test_flow_title_block_seen_skip_torrent_block_and_submit(...):
    # 4 个帖子：1 标题命中，1 tid 已提交，1 种子内文件名命中，1 正常
    # 断言 counts == {"title_blocked":1,"skipped_seen":1,"torrent_blocked":1,"submitted":1, ...}，qB 只收到 1 次 add_torrent
def test_prefers_torrent_over_magnet_and_never_submits_both(...)
def test_falls_back_to_magnet_when_torrent_invalid(...)
def test_cookie_invalid_when_all_list_pages_fail(...)    # fatal_reason 以“站点 cookie 可能失效”开头，且没有访问帖子页
def test_challenge_page_sets_fatal_reason(...)
def test_qb_login_failure_marks_all_submit_failed(...)   # Review Focus 5：counts["submitted"] == 0
def test_dry_run_never_calls_qb(...)
def test_qb_error_message_has_no_request_body(...)       # test_qb.py：httpx.MockTransport 返回 "Fails."
def test_save_and_load_site_session_roundtrip_and_mode_0600(tmp_path): ...
def test_status_never_contains_cookie(tmp_path): ...
def test_main_without_session_file_writes_fatal_result(tmp_path, monkeypatch):  # Review Focus 3
    # 运行 main()，result.json 的 fatal_reason == "尚未设置站点 cookie"，退出码 0
def test_main_output_never_contains_secrets(tmp_path, monkeypatch, capsys):
    # 会话文件 cookie 含 "SECRET-COOKIE-123"，QB_PASSWORD="SECRET-PW-456"，用假站点跑完，
    # 标准输出和 result.json 都不含这两个串
```

`sleep` 注入成空函数，测试不真的等待。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs/sehuatang -q`

- [ ] **Step 3: 实现**

- [ ] **Step 4: 运行，确认通过**（同 Step 2 的命令）

- [ ] **Step 5: 提交**

```bash
git add app/services/script_jobs/sehuatang app/services/script_jobs/site_session.py tests/script_jobs/sehuatang tests/script_jobs/test_site_session.py
git commit -m "feat: sehuatang 抓取、过滤与 qB 提交主流程"
```

---

### Task 8: sehuatang 接入执行器、站点会话接口

**Files:**
- Create: `app/services/script_jobs/sehuatang_task.py`
- Modify: `app/services/script_jobs/definitions.py`（给 sehuatang 挂上 `prepare` / `finalize`）、`app/core/config.py`、`app/api/routes/script_jobs.py`、`.env.example`（加 `QB_URL=`、`QB_USERNAME=`、`QB_PASSWORD=`，不填值）
- Test: `tests/script_jobs/test_sehuatang_task.py`、`tests/api/test_script_jobs_routes.py`

**Interfaces:**
- Consumes: Task 4 的 `RunContext`、`PreparedCommand`、`RunOutcome`；Task 7 的 `JobInput` 字段和 `result.json` 结构。
- Produces:
  - `config.py` 新增：
    - `qb_url: str | None`（别名 `QB_URL`）、`qb_username: str | None`、`qb_password: str | None`；
    - `sehuatang_session_path: str = "data/sehuatang/site_session.json"`。
  - `site_session.py` 的三个函数由 Task 7 提供。
  - `sehuatang_task.load_block_terms(db) -> list[Term]`：取启用的 blacklist 词条的规范名和所有别名，去掉首尾空白后不足 2 个字的跳过，去重。
  - `sehuatang_task.prepare(db, ctx) -> PreparedCommand`：
    - 写 `input.json`，内容是 `JobInput` 的字段；`submitted_tids` 来自 `SehuatangPost.last_outcome == "submitted"`。
    - argv 是 `[sys.executable, "-m", "app.services.script_jobs.sehuatang.main", "--input", ..., "--result", ...]`。
    - env 是当前进程环境加上 `QB_*`、`SEHUATANG_SESSION_PATH`、`PYTHONUNBUFFERED=1`。
  - `sehuatang_task.finalize(db, ctx, exit_code) -> RunOutcome`：
    - 状态：没有 `result.json` 或退出码不为 0 → `failed`，“运行异常退出”；有 `fatal_reason` → `failed`，原因就是它；`submit_failed` 或 `parse_failed` 大于 0 → `warning`；其余 → `success`。
    - 名单映射：`path=title`、`target_path=url`、`keyword`、`message`。
    - 非演练时更新 `sehuatang_posts`：按 tid 新增或更新 `title`、`url`、`last_outcome`、`last_run_id`；`submitted` 的同时写 `submitted_at`。已经是 `submitted` 的帖子，不能被之后的其他结果覆盖成别的状态。
  - 接口：
    - `PUT /script-jobs/sehuatang/site-session`，请求体 `{"cookie": str（至少 1 字）, "user_agent": str（至少 10 字）}`，返回 `site_session_status`；
    - `GET /script-jobs` 的 sehuatang 项加 `site_session` 字段，只含 configured 和 updated_at，永远不回显 cookie。

- [ ] **Step 1: 写失败测试**

```python
def test_load_block_terms_includes_aliases_skips_short_and_inactive(db_session): ...
def test_prepare_writes_input_with_submitted_tids_and_no_secrets(db_session, tmp_path, monkeypatch):
    # QB_PASSWORD 设为 "SECRET-PW"，断言 input.json 不含它；env 里有 QB_PASSWORD
def test_finalize_maps_status_and_items(db_session, tmp_path): ...
def test_finalize_qb_login_failure_leaves_posts_not_submitted(db_session, tmp_path): ...  # Review Focus 5
def test_finalize_dry_run_does_not_touch_posts(db_session, tmp_path): ...
def test_submitted_post_not_downgraded_later(db_session, tmp_path): ...
def test_put_site_session_then_get_shows_configured_without_cookie(client): ...
```

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs tests/api/test_script_jobs_routes.py -q`

- [ ] **Step 3: 实现**

- [ ] **Step 4: 运行后端全量，确认通过**

Run: `scripts/remote-test.sh backend`

- [ ] **Step 5: 更新接口类型并提交**

```bash
scripts/gen-api-types.sh
git add app/services/script_jobs app/core/config.py app/api/routes/script_jobs.py tests/script_jobs tests/api/test_script_jobs_routes.py frontend/openapi.json frontend/src/api/schema.gen.ts
git commit -m "feat: sehuatang 接入执行器，站点 cookie 页面可换"
```

`.env.example` 一并 `git add`。

---

### Task 9: 迁移导入脚本（最近 14 天已提交帖子）

**Files:**
- Create: `scripts/seed_sehuatang_posts.py`
- Test: `tests/script_jobs/test_seed_sehuatang_posts.py`

**Interfaces:**
- Produces:
  - `seed_from_csv_dir(db, csv_dir: Path, *, days: int = 14, today: date) -> int`：
    - 读取文件名为 `shuhuatang_YYYY_MM_DD_HHMM.csv`、日期在 `today - days` 之后的文件；
    - 第二列是链接，从中取出 tid；
    - 已存在的 tid 跳过；新的插入 `last_outcome="submitted"`、`title="（迁移导入）"`、`submitted_at=None`；
    - 返回新增条数。
  - 命令行：`python scripts/seed_sehuatang_posts.py --csv-dir <dir> --days 14`，只读 CSV，输出新增条数。部署后在容器里运行，CSV 目录需要临时挂载或复制进去，方法写进 Task 11 的运行手册。

- [ ] **Step 1: 写失败测试**

用虚构 CSV：3 个文件，其中 1 个超出 14 天；有 1 个 tid 重复，有 1 行链接无法解析。断言新增条数，以及超期文件没有被读取。

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh backend tests/script_jobs/test_seed_sehuatang_posts.py -q`

- [ ] **Step 3: 实现**（tid 的取法复用 `pages.py` 里的正则）

- [ ] **Step 4: 运行，确认通过**（同 Step 2 的命令）

- [ ] **Step 5: 提交**

```bash
git add scripts/seed_sehuatang_posts.py tests/script_jobs/test_seed_sehuatang_posts.py
git commit -m "feat: sehuatang 切换用的已提交帖子导入脚本"
```

---

### Task 10: 前端「脚本中心」

**Files:**
- Create: `frontend/src/api/scriptJobs.ts`、`frontend/src/pages/scriptCenter/JobCards.tsx`、`JobSettingsDrawer.tsx`、`RunLogPanel.tsx`
- Modify: `frontend/src/api/scriptRuns.ts`（类型改从 `schema.gen` 取）、`frontend/src/pages/ScriptRunsPage.tsx`、`frontend/src/layout/navigation.tsx`（`'脚本日报'` 改成 `'脚本中心'`）
- Test: `frontend/src/pages/ScriptRunsPage.test.tsx`（已有用例保持通过）、`frontend/src/pages/scriptCenter/*.test.tsx`

**Interfaces:**
- Consumes: Task 2、4、5、8 的接口。类型从 `components['schemas'][...]` 取，写法照 `frontend/src/api/dedupe.ts`。
- Produces（页面行为，测试用这些可见文字断言）：
  - **任务卡片**，每个任务一张，显示：
    - 名称（label）；
    - 状态标签：执行方为 unraid → “由 Unraid 运行”；18x 且停用 → “已停用”；18x 且启用 → “每天 HH:MM”；
    - 上次结果一句话；
    - 运行中或排队中时显示“运行中 N 分钟”或“排队中”。
  - **卡片按钮**：
    - 「立即运行」：只有执行方为 18x 时显示；
    - 「演练」：始终显示；
    - 「停止」：有 active_run 时显示，替代前两个按钮；
    - 「设置」；
    - 「看日志」：有 active_run 时显示。
  - **确认框**：立即运行、演练、停止都要再点一次确认。确认文案：
    - 立即运行：“立即真实运行「{label}」？”；
    - DEL 的立即运行另加一句“会真实删除文件”（本段 DEL 不可运行，但文案先放进去，测试覆盖）；
    - 演练：“演练运行「{label}」？不会提交或改动任何文件。”；
    - 停止：“停止这次运行？”
  - **红条**：sehuatang 的 `alert` 不为空时，在卡片区上方显示红色 Alert，内容是 alert 文本，外加“到设置里更换站点 cookie”。
  - **设置抽屉**：
    - 开关、运行时间（HH:MM 输入）、执行方切换（`runnable=False` 时禁用并提示“尚未支持在 18x 执行”）；
    - 参数表单：sehuatang 是页数、版块地址、qB 分类；MOVE、DEL 在本段只读展示参数，编辑留给第二、三段；
    - sehuatang 另有“站点 cookie”一节：显示“已设置，最后更新 …”或“未设置”，两个输入框（cookie、User-Agent），保存后清空，不回显旧值；
    - 保存失败时显示后端返回的中文 `detail`。
  - **运行记录**：在阶段 6 的列表基础上，每行加“演练”“手动”标签，状态标签覆盖七种状态，中文分别是：排队中、运行中、正常、有警告、失败、已停止、已中断。
  - **运行详情**：页签加「日志」，用 `RunLogPanel`：运行中每 2 秒按 offset 追加，`finished` 为 true 后停止轮询；第一次加载时从 0 开始。
  - **sehuatang 运行的一句话结果**：“提交 {submitted}，标题拦 {title_blocked}，种子拦 {torrent_blocked}，跳过 {skipped_seen}，失败 {submit_failed + parse_failed}”。
  - **名单页签**加：已提交、标题被拦、种子被拦、提交失败、解析失败。
  - **今日状态**加：disabled →“已停用”，not_tracked →“未接入日报”，queued、running、stopped、interrupted 用上面的中文。

- [ ] **Step 1: 写失败测试**

vitest 测试，接口用现有测试里的 mock 写法：

```tsx
it('由 Unraid 运行时只显示演练不显示立即运行', ...)
it('有运行中任务时显示停止和看日志', ...)
it('sehuatang alert 显示红条', ...)
it('DEL 立即运行确认框包含“会真实删除文件”', ...)
it('站点 cookie 保存后输入框清空且页面不出现旧 cookie', ...)
it('日志面板按 offset 追加，finished 后停止轮询', ...)  // fake timers
it('运行中的记录 finished_at 为空时不报错', ...)
```

- [ ] **Step 2: 运行，确认失败**

Run: `scripts/remote-test.sh frontend`
Expected: 新用例 FAIL。

- [ ] **Step 3: 实现**

延续现有 antd 和 `PageScaffold` / `SurfacePanel` 的风格，不加新依赖。

- [ ] **Step 4: 运行，确认通过**

Run: `scripts/remote-test.sh frontend`
Expected: 测试、构建、lint 全部通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src
git commit -m "feat: 脚本中心页面（运行、停止、设置、实时日志）"
```

---

### Task 11: 文档、运行手册和进度日志

**Files:**
- Create: `docs/script-jobs.md`、`progress/2026-11-25-script-jobs-p1.md`（日期以实际完成那天为准）
- Modify: `docs/unraid-script-reports.md`（开头加一段：sehuatang 已由 18x 执行；MOVE、DEL 切换前仍按本文档回报）

**Interfaces:** 无代码接口。

- [ ] **Step 1: 写 `docs/script-jobs.md`**

内容按以下小节：

1. 功能概述。
2. 新增环境变量：`QB_URL`、`QB_USERNAME`、`QB_PASSWORD`；可选 `SCRIPT_JOBS_DIR`、`SEHUATANG_SESSION_PATH`。只写变量名，不写值。
3. 页面操作。
4. 执行方切换步骤（设计第七节）。
5. 部署前检查：在页面上确认没有运行中的任务。
6. sehuatang 切换运行手册（见 Step 2）。
7. 回滚。

- [ ] **Step 2: 运行手册写明以下顺序**

每一步都标出“需用户批准”。

1. **8 个 AI 词只读预估**：在 DEL 的 3 个删除目录下，用 `find` 按名字含这 8 个词（区分大小写，和 DEL 一致）列出目录和文件，只统计、不删除，结果给用户看。
2. **加词**（需批准）：在 18x 关键词页或接口新增，`note` 写“来源：sehuatang 标题黑名单，2026-11 合并”。
3. **备份数据库并部署**（需批准）：迁移自动升到 `20261125_0018`。
4. **配置 qB 凭证**（需批准）：在生产 `.env` 写入 `QB_*`，由用户本人填，或经用户同意从 `gc.py` 复制；然后重启容器。
5. **设置站点 cookie**：用户在页面「设置」里粘贴 cookie 和浏览器 User-Agent。
6. **导入最近 14 天的帖子编号**：在容器里运行 `scripts/seed_sehuatang_posts.py`，只读 CSV。
7. **演练对比**：在 18x 里演练 sehuatang，和 Unraid 当天的日志对比；把被拦下的标题列表给用户检查。
8. **切换执行方**（需批准）：先在 Unraid 停用 `sehuatang` 定时，再在 18x 设置里把执行方改成 18x 并启用。
9. **次日核对**：01:28 之后核对运行记录和 qB 是否收到。

- [ ] **Step 3: 写进度日志**

包含 What was done、Testing（各任务的测试命令和结果）、Notes（Changed files / Rollback）。

- [ ] **Step 4: 提交**

```bash
git add docs/script-jobs.md docs/unraid-script-reports.md progress/2026-11-25-script-jobs-p1.md
git commit -m "docs: 脚本中心第一段说明与 sehuatang 切换手册"
```

---

## 完成后

- 用 superpowers:requesting-code-review 请一位全新的审阅人看整个分支。
- 生产切换（Task 11 运行手册）不在本计划的代码范围内，每一步执行前都要单独问用户。
- sehuatang 切换稳定后，再写第二段（MOVE）计划。
