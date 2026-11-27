# 女优删片清理残留配套文件 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal：** 删片批次删完视频后，自动清理同一部片在 115 目录和 `porn_tv1` 源目录留下的 nfo、图片、字幕；已完成的批次可用脚本补跑。

**Architecture：** 新模块 `leftovers.py` 只做「判断该删什么」（纯函数，不碰 IO）；`FilmDeleteGuard` 加两个本地删除方法；`OpenListClient` 加只读列目录；`DeleteBatchService` 在 `_delete_film_dir` 之后调用新的清理步骤，结果记成新分组的文件行，失败不影响片子状态。补跑脚本复用同一个清理方法。

**Tech Stack：** Python 3.12、SQLAlchemy、httpx、pytest；前端 React + TypeScript（只改文案和标签）。

**Spec：** `docs/superpowers/specs/2026-11-27-actress-delete-leftover-cleanup-design.md`

## Global Constraints

- 配套扩展名（小写比较）：图片 `.jpg .jpeg .png .webp`；字幕 `.srt .ass .ssa .vtt`；另有 `.nfo`。写成常量，不放配置。
- 同名配套文件只认：`<名字>.nfo`、`<名字>-poster<图片扩展名>`、`<名字>-fanart<图片扩展名>`、`<名字>-thumb<图片扩展名>`、`<名字><字幕扩展名>`（`<名字>` = 视频文件名去掉扩展名，大小写敏感）。
- 整目录删除条件：没有子文件夹，且每个文件都是配套扩展名（空目录也算）。115 端目录路径不能是 `/`；本地目录必须在 `source_root` 之下至少一层、路径不经过链接。
- 新文件行分组：`remote_leftover`、`source_leftover`；文件行状态新增 `skipped`。清理失败只记在行上，片子仍是 `deleted`。
- 代码注释、docstring、提示文字用中文。
- 不改数据库结构（`group` 是 `String(16)`，新分组名 15 个字符，够用；`status` 是字符串）。

## Review Focus

1. 115 目录里还有别的片子的视频（集合目录，如测试夹具里的 `/AV`）→ 只能删同名配套文件，绝不能删目录。→ Task 3 `test_remote_leftover_shared_dir_deletes_only_same_name_sidecars`
2. OpenList 刷新那一行失败了（列表可能是旧的）→ 不清理 115，记 `skipped`。→ Task 3 `test_remote_leftover_skipped_when_refresh_failed`
3. 按路径查 115 得到的类型不对（期望文件夹却是文件，或反过来）→ 不删，记 `failed`。→ Task 3 `test_remote_leftover_rejects_wrong_category`
4. 本地源目录里有子文件夹或不认识的文件（如 `.txt`、别的 `.strm`）→ 不删目录，只删同名配套。→ Task 2 `test_plan_dir_with_subdir_or_unknown_file_falls_back`
5. 续跑或补跑第二次 → 已删的行不重做，不报错。→ Task 4 `test_clean_leftovers_twice_is_noop`

---

### Task 1：守卫和 OpenList 的新能力

**Files:**
- Modify: `app/services/actresses/delete_guard.py`（`FilmDeleteGuard` 加方法）
- Modify: `app/services/actresses/openlist.py`（`OpenListClient` 加方法）
- Test: `tests/actresses/test_delete_guard.py`、`tests/actresses/test_openlist.py`（已有文件，追加用例）

**Interfaces:**
- Produces:
  - `FilmDeleteGuard.delete_source_dir(path: str) -> str`：`path` 必须是 `source_root` 下至少一层的目录（用 `_locate(..., depth=None)`），不存在返回 `"missing"`，是目录则 `shutil.rmtree` 并返回 `"deleted"`，不是目录抛 `GuardError`。
  - `FilmDeleteGuard.delete_source_sidecar(path: str) -> str`：`path` 在 `source_root` 下、扩展名属于配套扩展名（从 Task 2 的 `SIDECAR_EXTS` 导入），不存在返回 `"missing"`，普通文件 `os.remove` 返回 `"deleted"`，否则抛 `GuardError`。
  - `OpenListClient.list_dir(path: str) -> list[tuple[str, bool]]`：POST `/api/fs/list`，请求体 `{"path": path, "refresh": False, "password": "", "page": 1, "per_page": 0}`，返回 `[(name, is_dir), ...]`（来自 `data.content[*].name` / `is_dir`，`content` 为 null 时返回 `[]`）；失败抛 `OpenListError`，判定方式与 `refresh_dir` 相同。

- [ ] **Step 1：写失败测试**
  - `test_delete_source_dir_removes_dir_under_root`：`source/AV/x/` 里放 `a.nfo` → 返回 `"deleted"`，目录不在。
  - `test_delete_source_dir_rejects_root_and_outside`：传 `source_root` 本身、`tmp/other` → 抛 `GuardError`，目录仍在。
  - `test_delete_source_dir_missing`：不存在的子目录 → `"missing"`。
  - `test_delete_source_sidecar_only_sidecar_exts`：`a.nfo` → `"deleted"`；`a.strm`、`a.mp4` → 抛 `GuardError` 且文件仍在。
  - `test_list_dir_returns_names_and_dirs`：用 `httpx.MockTransport` 返回 `{"code":200,"data":{"content":[{"name":"a.nfo","is_dir":false},{"name":"sub","is_dir":true}]}}` → `[("a.nfo", False), ("sub", True)]`，并断言请求体 `refresh` 为 `False`。
  - `test_list_dir_null_content` → `[]`；`test_list_dir_error_raises`（`code` 500）→ 抛 `OpenListError`。
- [ ] **Step 2：运行确认失败** —— `/Users/wangyichuan/Developer/wangcodemac/18x_v2/.venv/bin/python -m pytest tests/actresses/test_delete_guard.py tests/actresses/test_openlist.py -n 0 -q`，预期新用例 FAIL。
- [ ] **Step 3：实现上面三个方法。**（Task 1 与 Task 2 一起做：守卫要导入 `SIDECAR_EXTS`。）
- [ ] **Step 4：同一命令全部 PASS。**

### Task 2：判断该删什么（纯函数）

**Files:**
- Create: `app/services/actresses/leftovers.py`
- Test: `tests/actresses/test_leftovers.py`

**Interfaces:**
- Produces:
  - 常量 `IMAGE_EXTS`、`SUBTITLE_EXTS`、`SIDECAR_EXTS`（= 图片 ∪ 字幕 ∪ {`.nfo`}），都是 `frozenset[str]`。
  - `is_sidecar(name: str) -> bool`：扩展名（小写）在 `SIDECAR_EXTS` 里。
  - `sidecar_names(video_names: Iterable[str], entries: Iterable[tuple[str, bool]]) -> list[str]`：`entries` 里不是目录、且是某个视频的同名配套文件的名字，排序去重。
  - `@dataclass(frozen=True) class LeftoverPlan: whole_dir: bool; names: list[str]`
  - `plan_dir(video_names: Iterable[str], entries: Iterable[tuple[str, bool]]) -> LeftoverPlan`：满足整目录条件时 `whole_dir=True, names=[]`；否则 `whole_dir=False, names=sidecar_names(...)`。

- [ ] **Step 1：写失败测试**
  - `test_plan_whole_dir_when_only_sidecars`：视频 `XYZ-001 x.avi`，entries 为 nfo + 3 张同名 jpg → `LeftoverPlan(True, [])`。
  - `test_plan_whole_dir_when_empty` → `whole_dir=True`。
  - `test_plan_dir_with_other_video_deletes_same_name_only`：entries 含 `ABC-001.nfo`、`ABC-001-poster.jpg`、`ABC-002.mp4`、`ABC-002.nfo`，视频 `ABC-001.mp4` → `LeftoverPlan(False, ["ABC-001-poster.jpg", "ABC-001.nfo"])`。
  - `test_plan_dir_with_subdir_or_unknown_file_falls_back`：分别加 `("sub", True)`、`("readme.txt", False)`、`("ABC-002.strm", False)` → `whole_dir=False`，只返回同名配套。
  - `test_sidecar_names_exact_suffixes`：`ABC-001-poster.png`、`ABC-001.zh.srt`（不认）、`ABC-0011.nfo`（不认）、`abc-001.nfo`（大小写不同，不认）、`ABC-001.srt`（认）。
- [ ] **Step 2：运行确认失败** —— `.../.venv/bin/python -m pytest tests/actresses/test_leftovers.py -n 0 -q`。
- [ ] **Step 3：实现 `leftovers.py`。**
- [ ] **Step 4：PASS。**

### Task 3：删除批次里的清理步骤

**Files:**
- Modify: `app/services/actresses/delete_batch_service.py`
- Modify: `app/models/actresses.py`（只改 `ActressDeleteBatchFile.group` / `status` 的注释，写上新分组和 `skipped`）
- Modify: `app/schemas/actresses.py:189-192`（`group` Literal 加 `"remote_leftover"`、`"source_leftover"`；`status` Literal 加 `"skipped"`）
- Test: `tests/actresses/test_delete_batch_service.py`（追加；`_FakeOpenList` 加 `list_dir`，内容由测试设定）

**Interfaces:**
- Consumes: Task 1 的 `delete_source_dir` / `delete_source_sidecar` / `list_dir`；Task 2 的 `plan_dir`。
- Produces: `DeleteBatchService._clean_leftovers(batch_film, *, client_115, guard, openlist, urls: list[str], source_paths: list[str]) -> None`，不抛异常、不 commit。

行为（按设计第「规则」「记录与失败」两节）：

- 调用点：`_process_film` 里 `_delete_film_dir` 之后、置 `deleted` 之前。`source_paths` = 这部片 `source_strm` 行里状态为 `deleted` 或 `missing`、且 `target` 是绝对路径的那些 `target`。
- **115 端**，按 `openlist_dir_for(url)` 去重分目录；每个目录的视频名 = 该目录下 `decode_115_open_path(url).remote_path` 的文件名；115 目录路径 = 去掉开头 `/115_OPEN` 后的部分（`decode_115_open_path(url).remote_path` 的 dirname）。
  - `openlist is None` → 记一行 `remote_leftover`，target=115 目录路径，`skipped`，error「没配置 OpenList，未清理 115 配套文件」。
  - 这个 OpenList 目录的 `openlist_dir` 行不是 `refreshed` → `skipped`，error「OpenList 没刷新成功，未清理 115 配套文件」。
  - `list_dir` 失败 → `failed`，error 写原因。
  - 整目录：115 目录路径为 `/` 时不删、记 `skipped`；否则 `client_115.get_file(path=目录)`，`file_category` 必须是 `"0"` 才 `delete_node(file_id, dry_run=False)`，成功记 `deleted`（target=目录，`remote_file_id`），类型不对记 `failed`「115 上这个路径不是文件夹」；随后 `openlist.refresh_dir(OpenList 上级目录)`，失败只把原因追加到该行 `error`，状态仍 `deleted`。
  - 只删同名：对每个名字 `get_file(path=目录/名字)`，`file_category` 必须是 `"1"` 才删，逐个记行（target=完整 115 路径）；查不到（`resolve` 同样的 `430004` / 空结果规则，可复用 `MISSING_ERROR_CODE`）记 `missing`。
- **本地端**，按 `os.path.dirname(source_path)` 去重分目录；视频名 = 该目录下被删 STRM 的文件名去掉 `.strm` 后，再拼任意扩展名——即 `plan_dir` 的 `video_names` 传 STRM 文件名本身即可（`sidecar_names` 按去扩展名后的名字比）。目录不存在 → 记 `missing`。
  - 整目录 → `guard.delete_source_dir(目录)`；同名 → 逐个 `guard.delete_source_sidecar(目录/名字)`。`GuardError`/`OSError` 记 `failed`。
- 已是 `deleted`/`missing` 的行续跑时跳过（用现有 `_file_row` 取行）。

- [ ] **Step 1：写失败测试**（夹具里 115 片子都在共享目录 `/AV`，正好覆盖「集合目录」）
  - `test_remote_leftover_shared_dir_deletes_only_same_name_sidecars`：`/AV` 里再放 `ABC-001.nfo`（115 节点）和别的片 `ABC-009.mp4`；`_FakeOpenList.list_dir` 返回这些名字 → 只删 `ABC-001.nfo`，`d1` 目录节点还在，`ABC-009.mp4` 还在；文件行 `("remote_leftover", "/AV/ABC-001.nfo", "deleted")`。
  - `test_remote_leftover_whole_dir`：片子放在 115 的 `/AV/ABC-001/` 子目录（节点 `d2`，文件夹）里，`list_dir` 只返回 `ABC-001.nfo`、`ABC-001-poster.jpg` → `d2` 被删，行 `("remote_leftover", "/AV/ABC-001", "deleted")`，并且 `refresh_dir("/115_OPEN/AV")` 在删除后又调了一次。
  - `test_remote_leftover_skipped_when_refresh_failed`：`refresh_dir` 抛错 → 行状态 `skipped`，`list_dir` 没被调用，片子仍 `deleted`。
  - `test_remote_leftover_skipped_without_openlist`：不传 openlist → 一行 `skipped`，片子 `deleted`。
  - `test_remote_leftover_rejects_wrong_category`：整目录情形下 `/AV/ABC-001` 在假 115 里是文件 → 行 `failed`，没删任何节点。
  - `test_source_leftover_whole_dir`：本地 `source/AV/ABC-001/` 里放 STRM + `ABC-001.nfo` + `ABC-001-fanart.jpg` → 删完目录不在，行 `("source_leftover", <目录>, "deleted")`。
  - `test_source_leftover_shared_dir`：沿用夹具 `source/AV/`，再放 `ABC-001.nfo`、`ABC-002.strm` → 只删 `ABC-001.nfo`，`ABC-002.strm` 还在。
  - `test_leftover_failure_keeps_film_deleted`：守卫 `delete_source_dir` 抛 `OSError` → 行 `failed`，片子 `deleted`，批次 `completed`。
  - 更新 `test_refreshes_openlist_dir_after_115_before_local`、`test_without_openlist_client_no_refresh_row` 等断言完整文件行列表的已有用例：末尾追加新分组的行（按实际行为写死）。
- [ ] **Step 2：运行确认失败** —— `.../.venv/bin/python -m pytest tests/actresses/test_delete_batch_service.py -n 0 -q`。
- [ ] **Step 3：实现 `_clean_leftovers` 并接到 `_process_film`；改 schema 和模型注释。**
- [ ] **Step 4：`tests/actresses` 全部 PASS** —— `.../.venv/bin/python -m pytest tests/actresses -n 0 -q`。

### Task 4：补跑脚本

**Files:**
- Modify: `app/services/actresses/delete_batch_service.py`（加公开方法）
- Create: `scripts/actress_clean_leftovers.py`（照 `scripts/actress_import_emby_lists.py` 的写法）
- Test: `tests/actresses/test_delete_batch_service.py`（追加）

**Interfaces:**
- Produces:
  - `@dataclass class LeftoverAction: group: str; target: str; whole_dir: bool`
  - `DeleteBatchService.clean_leftovers(db, batch_id: int, *, client_115, guard, openlist, apply: bool) -> list[LeftoverAction]`：只处理批次里 `status == "deleted"` 的片子；`urls` 取这部片 `remote_115` 行的 `target`，`source_paths` 取 `source_strm` 行（规则同 Task 3）。`apply=False` 时只返回会删什么、不调用任何删除或刷新、不写文件行；`apply=True` 时调用 `_clean_leftovers` 并 commit，返回实际执行过的动作。批次不存在抛 `ActressError`。
  - 预览需要的 `openlist_dir` 行条件：补跑时不要求已有 `refreshed` 行——先对每个目录调一次 `openlist.refresh_dir`（`apply=False` 时也调用，它只刷新缓存、不删东西），成功后再列目录。为此 `_clean_leftovers` 加参数 `require_refreshed: bool = True`，补跑传 `False` 并自己先刷新。
- 脚本：`python scripts/actress_clean_leftovers.py --batch <编号> [--apply]`；功能未开启（`actress_enabled`）或没配齐 OpenList 时打印原因返回 1；用 `Real115Client(settings)`、`FilmDeleteGuard(settings.actress_source_root, settings.actress_organized_root)`、`job_runner._openlist_client(settings)`；逐行打印「将删除 / 已删除  115|本地  目录|文件  路径」，最后一行汇总；预览时提示「只预览，未删除；确认无误后加 --apply」。

- [ ] **Step 1：写失败测试**
  - `test_clean_leftovers_preview_does_not_delete`：先跑一个批次（不传 openlist，所以 115 端当时 `skipped`），再 `clean_leftovers(apply=False)` → 返回包含 115 和本地的动作，文件都还在，文件行数没变。
  - `test_clean_leftovers_apply_deletes`：同上 `apply=True` → 文件被删，新增行状态 `deleted`。
  - `test_clean_leftovers_twice_is_noop`：再跑一次 `apply=True` → 不报错，不再删除，返回空列表。
  - `test_clean_leftovers_unknown_batch` → 抛 `ActressError`。
- [ ] **Step 2：确认失败 → Step 3：实现 → Step 4：`tests/actresses` 全部 PASS。**

### Task 5：前端文案和标签

**Files:**
- Modify: `frontend/src/pages/ActressDeletePage.tsx:72-84, 204, 674`
- Modify: `frontend/src/pages/ActressDeletePage.test.tsx:45`
- Regenerate: `frontend/openapi.json`、`frontend/src/api/schema.gen.ts`（`scripts/gen-api-types.sh`，看脚本用法；生成不了就手改这两处 Literal 对应的类型并在交回时说明）

- [ ] `FILE_STATUS` 加 `skipped: ['未清理', 'warning']`；`FILE_GROUP_LABELS` 加 `remote_leftover: '115 配套文件'`、`source_leftover: 'porn_tv1 配套文件'`。
- [ ] 确认框文案改为：`` `将删除 ${dirs.length} 部片子的 115 原文件和本地 STRM，115 文件进回收站；同名的 nfo、图片、字幕一起清掉。确定？` ``（测试第 45 行同步）。
- [ ] 页面说明末尾追加：「视频删除后，同名的 nfo、图片、字幕一起清掉；目录里只剩这些时整个目录删掉（115 进回收站）。」
- [ ] 前端测试在 Spark 上由主管跑，工人不跑。

### Task 6：文档

- [ ] `docs/actresses.md`：删除步骤说明里加清理一步和补跑脚本用法；上线检查清单加一条「部署后用补跑脚本预览首删的那个批次，批准后 `--apply`」。
