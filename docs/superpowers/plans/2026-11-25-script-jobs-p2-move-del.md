# 脚本中心第二、三段（MOVE + DEL 搬进 18x）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `MOVE_SSD_CACHE_TO_DISK2` 和 `DEL_SOMETHING` 能在 18x 容器里执行、演练、停止，并在页面上调参数。判定规则和 Unraid 版完全一致。

**Architecture:** 沿用第一段的执行框架，包括 `ScriptJobRunner`、调度、互斥组 `media`、日志目录和 `prepare/finalize/salvage` 三个钩子。

- **MOVE**：bash 脚本原样进仓库，由 18x 以子进程运行。
- **DEL**：一个 Python 编排入口按原 bash 外壳的顺序调用原 `delete_files.py` 和整理脚本。关键词由 18x 从库里导出成文件，格式与 `/api/keywords` 返回的完全相同，所以原脚本的取词和匹配代码不用改。
- **结果解析**：两个脚本跑完都用阶段 6 的解析器解析日志。

**Tech Stack:** FastAPI、SQLAlchemy、bash、React + antd v6、pytest/vitest（在 Spark 上跑）。

**Spec:** `docs/superpowers/specs/2026-11-25-scripts-into-18x-design.md`（第六节第 1–3、6–8 小节，第七节 MOVE / DEL 部分）

## Global Constraints

- 判定规则原样写死，不放页面，包括模糊匹配、最短词长 2、多命中跳过、组合上限 3、MOVE 的合并 / 去重 / “_新版本”规则。
- 权限必须写成数字 `99:100`，仓库里不能再出现 `chown` 配 `nobody:users` 的写法。
- 目录参数只能在 `/mnt/cache/docker1/SSD_cache` 或 `/mnt/disk2/qbbtdn` 之下。这条校验已有：`validate_media_dir`。
- 演练不删除、不移动、不改权限。
- 日志、名单、接口返回里不能有密码。DEL 原来靠 `KEYWORDS_API_USERNAME/PASSWORD` 登录取词，搬进来后不再需要这两项。
- 测试夹具只用虚构路径和虚构词，不放真实目录名或关键词。
- 测试只在 Spark 上跑：`scripts/remote-test.sh backend|frontend|all`。
- 代码注释、文档用中文；不 `git add -A`。

## Review Focus

1. **名字含空格、引号、中文或 `$` 的目录和文件**：MOVE 和 DEL 照常处理。路径只经环境变量和参数列表传递，不拼进 shell 字符串。→ Task 2、Task 4 的夹具里放 `带 空格'和$符号` 这种名字。
2. **运行中被停止**：子进程（`delete_files.py`、整理脚本、`mv`）随进程组一起结束，已经做完的删除和移动要能从日志里找回，进名单。→ Task 2、Task 4 测 salvage。
3. **黑名单为空，或关键词文件读不到**：`delete_files.py` 以退出码 1 结束，整理不再执行，本次记为失败。不能出现“没有词就什么都不删却报成功”或继续整理的情况。→ Task 4。
4. **删除目录清单里有不存在的目录**：照原逻辑跳过这一项，其余目录照常处理。→ Task 4。
5. **演练**：目录树前后完全一致，不调用 `chown`，名单里列出“将删除 / 将移动”。→ Task 2、Task 4。

---

## 文件结构

| 文件 | 作用 |
|---|---|
| `app/services/script_jobs/media_output.py`（新） | 从 `scripts/unraid/report_script_run.py` 搬来的 DEL / MOVE 解析器（只用标准库），另加演练名单解析 |
| `scripts/unraid/report_script_run.py`（改） | 只保留回报命令行，解析改为从上面的模块导入 |
| `scripts/jobs/move_ssd_cache_to_disk2.sh`（新） | MOVE 原脚本：目录改由环境变量传入、去掉回报片段、权限改为 99:100 |
| `scripts/jobs/del_something/delete_files.py`（新） | DEL 删除脚本：加 `KEYWORDS_FILE`、`DELETE_LOG_FILE` 两个环境变量 |
| `scripts/jobs/del_something/local_organize_from_whitelist.py`（新） | 两个整理脚本合并成一份：加 `KEYWORDS_FILE`、`ORGANIZE_LOG_FILE` |
| `app/services/script_jobs/media_task.py`（新） | MOVE / DEL 的 prepare、finalize、salvage；关键词导出 |
| `app/services/script_jobs/del_main.py`（新） | DEL 子进程入口：按原 bash 外壳顺序编排，最后修正权限 |
| `app/services/script_jobs/definitions.py`（改） | MOVE、DEL 设为 `runnable=True`，接上钩子 |
| `docker/docker-compose.yml`（改） | 挂载两个媒体根目录 |
| `frontend/src/pages/scriptCenter/JobSettingsDrawer.tsx`（改） | MOVE、DEL 参数可以编辑 |
| `docs/script-jobs.md`、`docs/unraid-script-reports.md`（改） | 说明、切换手册、回滚 |

---

### Task 1: 解析器搬进 app，加演练名单

**Files:**
- Create: `app/services/script_jobs/media_output.py`
- Modify: `scripts/unraid/report_script_run.py`（删掉解析函数和常量，改为 `from app.services.script_jobs.media_output import ...`。文件头部先把仓库根目录插进 `sys.path`，保证单独运行时也能导入）
- Test: `tests/script_jobs/test_media_output.py`；`tests/script_runs/test_report_script.py` 不改，必须照常通过

**Interfaces:**
- Produces:
  - `ParseResult(counts: dict[str, int], items: list[dict], summary_found: bool)`
  - `parse_del_something_output(output: str) -> ParseResult`
  - `parse_move_ssd_cache_output(output: str) -> ParseResult`
  - `parse_output(script_name, output) -> ParseResult`
  - 新增 `parse_del_dry_run(output: str) -> ParseResult`

`parse_del_dry_run` 只认两类行：

- `[DRY-RUN] 将删除目录：<p>` / `[DRY-RUN] 将删除文件：<p>`：生成 `deleted_dir` / `deleted_file` 条目，计数 `deleted_dirs` / `deleted_files` 加 1，`message="演练"`。
- 整理脚本的 `[DRY-RUN] <src> -> <dst>`，下一行是 `命中标准词: <词>`：生成 `moved_new` 或 `moved_rescan`。归类规则和正式运行相同：源路径含 `已整理/抖音(风)` 的算 `moved_rescan`。`keyword=<词>`，`message="演练"`。

其余的行交给 `parse_del_something_output` 照常处理，比如 `[ERROR]`、`[WARN]`、`[AMBIGUOUS-LOW]`，计数合并进结果。

- [ ] **Step 1: 写失败测试** `test_dry_run_lists_would_delete_and_would_move`

  夹具包含：一行“将删除目录”、一行“将删除文件”、两组整理演练（一组源在 `/data/已整理/抖音/示例C`，一组源在 `/data/finish/示例B`），以及一行 `[WARN] 示例警告`。

  断言：
  - `counts["deleted_dirs"] == 1`、`counts["deleted_files"] == 1`、`counts["moved_new"] == 1`、`counts["moved_rescan"] == 1`、`counts["warnings"] == 1`。
  - 每个演练条目的 `message == "演练"`，moved 条目的 `keyword == "示例词"`。

  再写 `test_parsers_importable_from_app`：`from app.services.script_jobs.media_output import parse_output`，用 `tests/script_runs/test_report_script.py` 里同一段 DEL 夹具调用，结果和 `scripts.unraid.report_script_run.parse_del_something_output` 的结果相等。
- [ ] **Step 2: 运行，确认失败**：`scripts/remote-test.sh backend tests/script_jobs/test_media_output.py`，预期 `ModuleNotFoundError`。
- [ ] **Step 3: 实现**：把解析代码整段搬过去，内容不改。新增 `parse_del_dry_run`。改 `report_script_run.py` 的导入。
- [ ] **Step 4: 运行**：`scripts/remote-test.sh backend tests/script_jobs/test_media_output.py tests/script_runs/test_report_script.py`，预期全部 PASS。
- [ ] **Step 5: 提交** `refactor: DEL/MOVE 输出解析搬进 app，并解析演练名单`

---

### Task 2: MOVE 进仓库并能在 18x 执行

**Files:**
- Create: `scripts/jobs/move_ssd_cache_to_disk2.sh`、`app/services/script_jobs/media_task.py`
- Modify: `app/services/script_jobs/definitions.py`（MOVE：`runnable=True`，接上 `prepare/finalize/salvage`）
- Test: `tests/script_jobs/test_move_job.py`、`tests/script_jobs/test_media_task.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_move_ssd_cache_output`；`run_store.status_for(exit_code, counts, kinds)`；`LOG_FILE_NAME`
- Produces（`media_task.py`）：
  - `MOVE_SCRIPT: Path`（仓库内脚本的绝对路径）
  - `move_prepare(db, ctx) -> PreparedCommand`：argv 是 `["bash", str(MOVE_SCRIPT)]`，演练时末尾加 `"--dry-run"`；env 在 `os.environ` 基础上加 `MOVE_SOURCE_DIR`、`MOVE_TARGET_DIR`，值来自 `ctx.params`
  - `media_finalize(db, ctx, exit_code) -> RunOutcome`，DEL 共用：
    - 读 `ctx.run_dir / LOG_FILE_NAME`。
    - 按 `ctx.job_name` 和 `ctx.dry_run` 选解析器：DEL 演练用 `parse_del_dry_run`，其余用 `parse_output`。
    - `status = status_for(exit_code, counts, kinds)`。
    - `exit_code != 0` 时 `error_reason = f"运行异常退出（退出码 {exit_code}）"`。
  - `media_salvage(db, ctx) -> RunOutcome`：同样解析日志，但 MOVE 不因缺少汇总行补 `failed`，`status` 留空

- [ ] **Step 1: 原样拷贝并提交**
  - 先确认仓库里没有 `scripts/jobs/`。
  - 用 `scp` 只读拷贝 `root@192.168.70.138:/boot/config/plugins/user.scripts/scripts/MOVE_SSD_CACHE_TO_DISK2/script`，存为 `scripts/jobs/move_ssd_cache_to_disk2.sh`。
  - 单独提交 `chore: MOVE 原脚本原样入库（来自 Unraid User Scripts）`，方便下一步对比改动。
- [ ] **Step 2: 写失败测试**（`test_move_job.py`）

  在 `tmp_path` 下建 `src/`、`dst/`，并在 `PATH` 前面放一个假 `chown`：它把参数追加写进 `chown_calls.txt`，然后退出码 0。夹具覆盖：
  - 新文件 `新片 带 空格'和$符号.mp4`：应直接移动。
  - 同名目录 `合并目录/`：两边各有不同的文件，应递归合并，源目录清空后删除。
  - 同名同大小文件：应删除源文件。
  - 同名不同大小的 `a.mp4`：应在目标另存为 `a_新版本.mp4`。
  - 目录和文件同名冲突：应跳过。

  测试：
  - `test_move_real_run_matches_original_rules`：`subprocess.run(["bash", MOVE_SCRIPT], env=…)`。断言目标树内容；`parse_move_ssd_cache_output(stdout).counts` 中 `moved == 3`（新文件、合并目录里的新文件、`_新版本`）、`duplicates_removed == 1`、`skipped == 1`、`failed == 0`；`chown_calls.txt` 的内容是 `-R 99:100 <dst>`。
  - `test_move_dry_run_changes_nothing`：在 `--dry-run` 前后分别拍下两棵目录树（路径 + 大小），应完全相同；`chown_calls.txt` 不存在。
  - `test_move_script_has_no_named_owner`：脚本文本里不出现 `nobody:users`，也不出现 `report_script_run`。

  再写 `test_media_task.py`：
  - `move_prepare` 的 argv 和 env：演练时有 `--dry-run`；env 里的两个目录等于参数。
  - `media_finalize`：分别给有汇总行的成功日志、`失败 1 个` 的日志、没有汇总行的日志，状态依次为 `success`、`failed`、`failed`。
  - `media_salvage`：日志只有前几行“移动:”、没有汇总行时，`counts` 里不含补上的 `failed`。
- [ ] **Step 3: 运行，确认失败**：`scripts/remote-test.sh backend tests/script_jobs/test_move_job.py tests/script_jobs/test_media_task.py`
- [ ] **Step 4: 改脚本（只改三处）**
  1. `SRC="${MOVE_SOURCE_DIR:?未设置源目录}"`、`DST="${MOVE_TARGET_DIR:?未设置目标目录}"`。
  2. 删掉“脚本日报”整段，从 `REPORT_SCRIPT_NAME` 到 `trap report_on_exit EXIT`。
  3. `chown -R 99:100 "$DST"`，提示文字改成“设置权限 99:100（Unraid nobody:users）...”；文件头注释同步更新。
- [ ] **Step 5: 实现 `media_task.py` 中 MOVE 的部分**，在 definitions 里接上 MOVE 的钩子。
- [ ] **Step 6: 运行，确认通过**；再跑 `tests/script_jobs` 全目录，确认第一段的测试没有被破坏。
- [ ] **Step 7: 提交** `feat: MOVE 可在 18x 执行（目录由参数传入，权限改为 99:100）`

---

### Task 3: DEL 的两个 Python 脚本进仓库，关键词改由 18x 导出

**Files:**
- Create: `scripts/jobs/del_something/delete_files.py`、`scripts/jobs/del_something/local_organize_from_whitelist.py`
- Modify: `app/services/script_jobs/media_task.py`（加入关键词导出）
- Test: `tests/script_jobs/test_keywords_export.py`、`tests/script_jobs/test_del_scripts.py`

**Interfaces:**
- Produces：
  - `export_keywords(db, keyword_type: str, path: Path) -> int`：写入 `{"total": n, "entries": [...]}`。`entries` 取 `KeywordRegistryService(db).list_entries(keyword_type=…, status="active", skip=0, limit=1_000_000)`，每条用 `KeywordEntryResponse.model_validate(e).model_dump(mode="json")` 序列化。返回条数。
  - 两个脚本新增环境变量：
    - `KEYWORDS_FILE`：设置了就从这个文件读一页数据，不登录、不发请求；没设置就保持原来的 HTTP 方式。
    - `DELETE_LOG_FILE` / `ORGANIZE_LOG_FILE`：没设置时用原来写死的路径。

**Ruling（我的决定）：** 设计稿允许“读本机接口或直接读库”。这里选择由 18x 从库里导出与接口返回完全相同的 JSON，脚本只把“取一页数据”的来源换掉，后面的过滤（`strip`、最短 2 字、别名、`merge_policy`）和匹配代码一行不动。

原因：
- 不用在 18x 的 `.env` 里放一份自己登录自己的账号密码；
- 取词结果和接口完全一致，由下面的对比测试证明。

如果判断错了，代价是取到的词和 Unraid 版不一致，所以 Task 3 的对比测试和切换前的生产演练对比是两道关。

- [ ] **Step 1: 原样拷贝并提交**
  - 只读拷贝 `/mnt/cache/docker1/python/scripts/delsomethin/` 下的 `delete_files.py`、`local_organize_from_whitelist.py`。
  - 再对 `local_organize_from_whitelist_telegram.py` 做一次 `diff`，确认它和前者只差默认扫描目录和两行注释。
  - 单独提交 `chore: DEL 原 Python 脚本原样入库（来自 Unraid delsomethin）`，提交说明里记下 diff 的结论。
- [ ] **Step 2: 写失败测试**
  - `test_export_matches_keywords_api`：库里建 3 条黑名单（其中 1 条带别名、1 条停用）和 2 条白名单（其中 1 条 `merge_policy="fallback_only"`）。直接调用路由函数 `app.api.routes.keywords.list_keywords(keyword_type="blacklist", status="active", skip=s, limit=1, db=db_session)` 逐页取，`model_dump(mode="json")` 后把各页的 `entries` 拼起来，应该等于 `export_keywords` 写出的 `entries`。白名单同样比一遍。
  - `test_delete_files_reads_keywords_file`：把 `delete_files.py` 当模块导入（`importlib`，设好 `KEYWORDS_FILE` 环境变量），`load_keywords_from_api()` 的结果等于 `{规范名, 别名}` 中不少于 2 字的那些词；`requests.Session` 被替换成调用就报错的假对象，证明没有发网络请求。
  - `test_organizer_reads_keywords_file`：`load_whitelist_rules_from_api()` 返回的规则里，`is_fallback` 和 `all_terms` 的排序与原逻辑一致：长词在前；`fallback_only` 为真。
- [ ] **Step 3: 运行，确认失败。**
- [ ] **Step 4: 改脚本**
  - 两个文件里各加一个生成器 `_iter_keyword_pages()`：如果设置了 `KEYWORDS_FILE`，就读文件、只给出这一页数据；否则照原来的方式登录，再分页请求，每页给出一次 `data`。`load_*_from_api` 的循环改成遍历它，过滤和组装代码不动。
  - 日志路径改成从环境变量读。
  - 整理脚本删掉 `#scan_root`、`#target_root` 两行注释掉的旧配置，其余不动。
- [ ] **Step 5: 实现 `export_keywords`，运行测试，确认通过。**
- [ ] **Step 6: 提交** `feat: DEL 脚本入库，关键词改由 18x 导出文件提供`

---

### Task 4: DEL 编排，并能在 18x 执行

**Files:**
- Create: `app/services/script_jobs/del_main.py`
- Modify: `app/services/script_jobs/media_task.py`（`del_prepare`）、`definitions.py`（DEL：`runnable=True`，接上 `prepare` 和共用的 `media_finalize/media_salvage`）
- Test: `tests/script_jobs/test_del_job.py`

**Interfaces:**
- Consumes：Task 3 的 `export_keywords` 和两个脚本；Task 2 的 `media_finalize/media_salvage`
- Produces：
  - `del_prepare(db, ctx) -> PreparedCommand`。在 `ctx.run_dir` 下写四个文件：
    - `target_dirs.csv`：每行一个 `delete_dirs`；
    - `keywords_blacklist.json`、`keywords_whitelist.json`；
    - `input.json`：`{"dry_run", "organize_jobs", "merge_on_conflict", "fix_permissions", "scripts_dir", "run_dir"}`。

    argv 是 `[sys.executable, "-m", "app.services.script_jobs.del_main", "--input", <input.json>]`；env 和 sehuatang 一样设置 `PYTHONPATH`、`PYTHONUNBUFFERED`。
  - `del_main.main(argv) -> int`，照原 bash 外壳的顺序执行：
    1. `os.umask(0o077)`，与原脚本一致。
    2. 子进程运行 `python -u delete_files.py`。env 加 `DRY_RUN`、`TARGET_DIRS_CSV`、`KEYWORDS_FILE`（黑名单）、`DELETE_LOG_FILE=<run_dir>/delete_log.txt`。退出码非 0 时，立即以同一退出码结束（原脚本 `set -e`）。
    3. 逐条处理 `organize_jobs`：
       - 扫描目录不存在时打印 `[SKIP] 扫描根不存在, 跳过: <scan_root>`，继续下一条；
       - 否则打印 `[INFO] Organizing: <scan_root> -> <target_root>`，运行整理脚本。env 加 `ORGANIZE_SCAN_ROOT`、`ORGANIZE_TARGET_ROOT`、`MERGE_ON_CONFLICT`、`DRY_RUN`、`KEYWORDS_FILE`（白名单）、`ORGANIZE_LOG_FILE`；
       - 退出码非 0 时立即结束；
       - 记下处理过的目标根，保持顺序并去重。
    4. 只有 `fix_permissions` 为真且不是演练时，才逐个修正目标根的权限：
       - 目录存在：先打印 `[INFO] Fixing permissions for: <root>`，再依次运行 `["chown", "-R", "99:100", root]`、`["find", root, "-type", "d", "-exec", "chmod", "775", "{}", "+"]`、`["find", root, "-type", "f", "-exec", "chmod", "664", "{}", "+"]`；
       - 目录不存在：打印 `[WARN] Organized root does not exist, skip permission fix: <root>`；
       - 命令失败：打印 `[ERROR] 修正权限失败: <root>`，继续处理其他目标根，最后返回 1。
    5. 演练且 `fix_permissions` 为真时，打印 `[INFO] 演练模式，跳过修正权限`。

**Ruling（我的决定）：**
- **演练不改权限**：原 bash 外壳设了 `DRY_RUN` 也会照样 `chown`。设计稿要求演练不改动任何东西，所以 18x 的演练跳过修正权限。代价：演练日志比 Unraid 版少几行 `[INFO] Fixing permissions`，对比时忽略这几行。
- **保留 `umask 077`**：与原脚本保持一致，新建目录的权限由最后一步修正。

- [ ] **Step 1: 写失败测试**（`test_del_job.py`，全部用真实子进程、`tmp_path` 目录树、`PATH` 前置的假 `chown` 和关键词文件）
  - `test_del_real_run_deletes_then_organizes_then_fixes_permissions`：
    - 夹具：两个删除目录（其中一个不存在）、黑名单词 `示例坏词`、白名单词 `示例好词`；扫描目录里有 `示例坏词 合集/`、`示例好词 带 空格'和$/`、`无关目录/`。
    - 断言：坏词目录被删；好词目录移到 `<target>/示例好词/`；无关目录不动；`chown_calls.txt` 里每个目标根恰好出现一次 `-R 99:100 <root>`。
    - 用 Task 1 的解析器解析输出：`deleted_dirs == 1`、`moved_new == 1`、`errors == 0`。
  - `test_del_dry_run_changes_nothing_and_lists_plan`：前后两棵目录树完全一致；没有 `chown` 调用；用 `parse_del_dry_run` 解析日志得到 1 条 `deleted_dir` 和 1 条 `moved_new`，`message` 都是 `"演练"`。
  - `test_del_missing_scan_root_is_skipped`：输出含 `[SKIP] 扫描根不存在`，退出码 0。
  - `test_del_empty_blacklist_fails_before_organize`：黑名单文件为空，退出码 1；输出里没有 `[INFO] Organizing`；好词目录还在原位。
  - `test_del_prepare_writes_inputs`：检查 csv 的每一行、两个关键词文件的条数和 `input.json` 的字段；env 里没有 `KEYWORDS_API_PASSWORD`。
  - `test_del_stop_salvages_partial_deletions`：给 `media_salvage` 一段只有一行“已删除目录”和一行“已删除文件”、没有汇总的 DEL 日志，断言 `deleted_dirs == 1`、`deleted_files == 1`。进程组一起被停止这一点，第一段的 runner 测试已经覆盖。
- [ ] **Step 2: 运行，确认失败**：`scripts/remote-test.sh backend tests/script_jobs/test_del_job.py`
- [ ] **Step 3: 实现** `del_main.py`、`del_prepare`，在 definitions 里接上 DEL 的钩子。
- [ ] **Step 4: 运行**：先跑 `tests/script_jobs/test_del_job.py`，再跑整个 `tests/script_jobs`，预期全部 PASS。
- [ ] **Step 5: 提交** `feat: DEL 可在 18x 执行（Python 编排，演练不改权限）`

---

### Task 5: 容器挂载两个媒体根目录

**Files:**
- Modify: `docker/docker-compose.yml`
- Test: `tests/script_jobs/test_compose_mounts.py`

- [ ] **Step 1: 写失败测试** `test_allowed_roots_are_mounted_at_same_path`：用 `yaml.safe_load` 读 compose 文件。断言 `definitions.ALLOWED_ROOTS` 里的每个根，都以 `<root>:<root>` 形式出现在 `services.app.volumes` 里，并且不带 `:ro`。
- [ ] **Step 2: 运行，确认失败。**
- [ ] **Step 3: 修改 compose**
  - 加 `/mnt/cache/docker1/SSD_cache:/mnt/cache/docker1/SSD_cache` 和 `/mnt/disk2/qbbtdn:/mnt/disk2/qbbtdn`，注释写明用途（DEL 删除和整理、MOVE 源和目标）。
  - 删掉被新挂载覆盖的 `/mnt/disk2/qbbtdn/已整理` 一行，注释说明 Jellyfin 用的路径不变。
- [ ] **Step 4: 运行，确认通过；提交** `feat: 18x 容器挂载 SSD_cache 和 disk2/qbbtdn，供 MOVE/DEL 使用`

---

### Task 6: 设置页可编辑 MOVE、DEL 参数

**Files:**
- Modify: `frontend/src/pages/scriptCenter/JobSettingsDrawer.tsx`
- Test: `frontend/src/pages/scriptCenter/JobSettingsDrawer.test.tsx`

**Interfaces:**
- Consumes：`updateScriptJob(name, {enabled, run_time, executor, params})`（已有）。参数结构见 `MoveParams` / `DelParams`。

页面字段：

- **MOVE**：「源目录」「目标目录」两个输入框。
- **DEL**：
  - 「删除扫描目录」：多行文本，每行一个，保存时去掉空行；
  - 「整理任务」：`Form.List`，每条有「扫描目录」「整理到」两个输入框和删除按钮，底部有「添加一条」；
  - 「同名目录合并」「跑完修正权限」两个开关。
- 表单顶部提示：“判定规则不在这里改；关键词在「关键词」页管理”。
- 删掉“参数（本阶段只读）”。

- [ ] **Step 1: 写失败测试**
  - `MOVE 保存时提交源和目标目录`：改目标目录后点保存，断言 `updateScriptJob` 收到 `params.target_dir` 为新值。
  - `DEL 保存删除目录和整理任务`：删除目录多行文本里有一个空行；删掉一条整理任务；关掉“修正权限”。断言提交的 `delete_dirs` 不含空串，`organize_jobs` 少一条，`fix_permissions === false`。
  - `后端校验错误原样显示`：mock 返回 400，内容是“目录不在容器已挂载的目录下…”，页面上应出现这段文字。
- [ ] **Step 2: 运行，确认失败**：`scripts/remote-test.sh frontend`
- [ ] **Step 3: 实现。**
- [ ] **Step 4: 运行**：`scripts/remote-test.sh frontend`，vitest、build、lint 全部通过。
- [ ] **Step 5: 提交** `feat: 脚本中心可编辑 MOVE、DEL 参数`

---

### Task 7: 文档与全量验证

**Files:**
- Modify: `docs/script-jobs.md`、`docs/unraid-script-reports.md`

- [ ] **Step 1: 更新 `docs/script-jobs.md`**
  - 第一张表：MOVE、DEL 的“能否由 18x 执行”改成“能”。
  - 删掉“MOVE、DEL 的参数本阶段只能查看”。
  - 新增“MOVE / DEL 的处理流程”：顺序、演练不改权限、权限 99:100、关键词由 18x 导出。
  - 新增“MOVE / DEL 切换手册”，每步都要用户批准：
    1. 部署前确认页面上没有运行中的任务，并避开 01:01–03:00 和 12:09–15:00。
    2. 备份数据库，部署。这次会改容器挂载，需要重建容器。
    3. 只读核对容器里的两个目录：`docker exec docker-app-1 ls /mnt/cache/docker1/SSD_cache /mnt/disk2/qbbtdn`。
    4. MOVE 演练对比：在 18x 里演练；同一时刻在 Unraid 上运行 `bash /boot/config/plugins/user.scripts/scripts/MOVE_SSD_CACHE_TO_DISK2/script --dry-run`。比较两边“移动 / 删除重复 / 新版本 / 跳过”的名单。
    5. DEL 演练对比：在 18x 里演练；同一时刻在 Unraid 上直接运行两个 Python 脚本，并设置 `DRY_RUN=true`。不要运行 bash 外壳，因为它在演练时也会 `chown`。比较“将删除”和“将移动”的名单。
    6. 停掉 Unraid 定时：备份 `schedule.json` 和 `customSchedule.cron`，把 MOVE、DEL 设为 disabled，然后执行 `update_cron`。
    7. 18x 把这两个脚本的执行方改成 18x 并启用。
    8. 第二天核对 01:01 和 12:09 两次运行的记录和日志。
  - 回滚：执行方改回 Unraid，恢复 cron 备份；需要时把 compose 挂载恢复原样，再重建容器。
- [ ] **Step 2: 更新 `docs/unraid-script-reports.md`**：切换后 Unraid 上的回报片段和 `report_script_run.py` 随原脚本一起停用；仓库里的 `scripts/unraid/report_script_run.py` 只用于回退。
- [ ] **Step 3: 全量验证**：`scripts/remote-test.sh all`，预期后端、前端、build、lint 全部通过。如果接口有变化，再跑 `scripts/gen-api-types.sh`。
- [ ] **Step 4: 提交** `docs: 脚本中心 MOVE/DEL 说明与切换手册`

---

## 不在本计划内（部署与切换，按手册逐步请用户批准）

- 生产部署（含挂载变更）、两次演练对比、停 Unraid 定时、18x 启用。
- 这些步骤按 Task 7 写好的手册执行，每一步单独请用户批准。
