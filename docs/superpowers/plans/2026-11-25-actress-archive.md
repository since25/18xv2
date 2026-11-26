# 女优档案 + 黑白名单 + 115 联动删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 18x 里新增独立的女优档案；拉黑后把应删的 115 番号片放进待删清单，网页确认后按「115 原文件 → porn_tv1 STRM → 302porn_tv1 番号目录」删除；白名单保护多人片并在 Jellyfin 建合集；给播放器提供按片查演员、直接改状态的接口。

**Architecture:** 新模块 `app/services/actresses/`，只读复用 Jellyfin 扫描结果（扫描时额外保存 NFO 演员名单），档案、规则、待删清单、删除批次各自一个文件。删除批次走现有后台任务机制（`app/services/job_runner.py`），每日链在扫描之后、合集同步之前加一步女优刷新。前端新增两个页面。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、pytest（Spark 上跑）、React + Ant Design + vitest。

**Spec:** `docs/superpowers/specs/2026-11-25-actress-archive-design.md`（必须先读）。

**执行位置：** 工作区 `.claude/worktrees/magical-morse-7b759f`，分支 `claude/magical-morse-7b759f`，已变基到最新 `main`（a0977f3b）之上，设计和计划两份文档是最前面的两个提交。

## Global Constraints

- 没经过网页确认就删除任何文件（包括每日任务发现的新片）——禁止。
- 删一部片的顺序固定：115 原文件 → `porn_tv1` 里对应的 STRM → `302porn_tv1` 的番号目录；**前一步失败就停在这部片**。
- 本地删除只允许落在 `porn_tv1` 和 `302porn_tv1` 两个可写根目录内；番号目录必须恰好是 `<302porn_tv1 根>/<演员>/<番号>`，演员目录只在变空时 `rmdir`。
- 不调用 Jellyfin 的「删除条目」接口删片；不做全量刷新（`FullRefresh` / `ReplaceAllMetadata` / `ReplaceAllImages`）。
- 女优名不写入 `keyword_entries` / `keyword_aliases`；关键词白名单只读。
- 演员只看 NFO 的 `<actor><name>`；NFO 缺失或解析失败的片子不进删除候选。
- 受保护 = 档案白名单，或演员名命中启用中的 `whitelist` / `emby_whitelist` 关键词（规范名或别名）。
- 女优功能总开关 `ACTRESS_ENABLED` 默认关闭；关闭时每日链不跑女优步骤、不建清单，删除接口返回 409。
- 代码注释、docstring、文档、提交说明用中文。
- 测试只在 Spark 上跑：`scripts/remote-test.sh backend <pytest 参数>`、`scripts/remote-test.sh frontend`。
- 提交时只 `git add` 本任务列出的文件，不用 `git add -A` / `git add .`。
- 测试夹具不得出现真实演员名、真实番号或真实路径以外的生产数据；用「甲」「乙」「ABC-001」这类占位。

## Review Focus

1. **演员名写法差异**：`三上 悠亜` 和 `三上悠亜`、全角和半角字母，用户会认为是同一个人 → Task 2 加 `test_normalize_actress_name_ignores_spaces_and_width`。
2. **路径换算配错或本地目录不在**：用户期望此时 115 一个文件都不删 → Task 6 加 `test_missing_local_dir_blocks_before_115`。
3. **分段片（CD1/CD2）只有一个带 NFO、或两个 NFO 演员不同**：用户期望按整部片看全部演员 → Task 3 加 `test_load_films_groups_parts_and_unions_actors`。
4. **Jellyfin 连不上**（取头像、删后扫库）：用户期望删除照样完成、头像显示占位 → Task 8 加 `test_delete_work_succeeds_when_jellyfin_refresh_fails`，Task 9 加 `test_image_returns_404_when_jellyfin_unavailable`。
5. **女优合集与关键词合集同名**：用户期望两边都不被改乱 → Task 7 加 `test_actress_collection_conflicts_with_keyword_collection_name`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `app/models/actresses.py` | 全部新表 |
| `alembic/versions/20261126_0019_actresses.py` | 迁移 |
| `app/services/actresses/names.py` | 演员名归一化、档案名字索引、受保护名字集合 |
| `app/services/actresses/films.py` | 把扫描条目按番号目录归成「片子」，读 NFO 标题 |
| `app/services/actresses/archive_service.py` | 建档、片数、改状态、别名、合并 |
| `app/services/actresses/rules.py` | 删片规则（规则 B） |
| `app/services/actresses/candidates_service.py` | 待删清单：重算、勾选、保留、检查 115 |
| `app/services/actresses/delete_guard.py` | 路径换算、本地删除守卫、STRM 地址索引 |
| `app/services/actresses/remote_115.py` | STRM 地址 → 115 文件解析 |
| `app/services/actresses/delete_batch_service.py` | 删除批次：建批次、逐部片执行、续跑 |
| `app/services/actresses/collection_sync.py` | 白名单女优的 Jellyfin 合集 |
| `app/services/actresses/job_runner.py` | 任务类型、开关判断、刷新 / 删除的干活函数 |
| `app/services/actresses/emby_import.py` | 旧 Emby 黑白名单一次性导入 |
| `app/schemas/actresses.py`、`app/api/routes/actresses.py` | 接口 |
| `scripts/actress_import_emby_lists.py` | 导入命令行 |
| `frontend/src/api/actresses.ts`、`frontend/src/pages/ActressesPage.tsx`、`frontend/src/pages/ActressDeletePage.tsx` | 前端 |
| `tests/actresses/` | 新测试目录 |

修改：`app/services/jellyfin/scan_service.py`、`app/services/jellyfin/client.py`、`app/services/jellyfin/job_runner.py`、`app/core/config.py`、`app/main.py`、`alembic/env.py`、`tests/conftest.py`、`.env.example`、`frontend/src/App.tsx`、`frontend/src/layout/navigation.tsx`、`frontend/openapi.json`、`frontend/src/api/schema.gen.ts`。

---

### Task 1: 数据表与迁移

**Files:**
- Create: `app/models/actresses.py`
- Create: `alembic/versions/20261126_0019_actresses.py`
- Modify: `alembic/env.py`（导入 `app.models.actresses`）
- Modify: `tests/conftest.py`（导入 `app.models.jellyfin` 和 `app.models.actresses`，让 `create_all` 建出新表）
- Test: `tests/actresses/__init__.py`、`tests/actresses/test_models.py`、`tests/test_migrations.py`

**Interfaces:**
- Produces（字段名、取值后续任务直接用；`created_at` 等时间列用 `DateTime(timezone=True), server_default=func.now()`）：
  - `Actress`（`actresses`）：`id`、`canonical_name String(255)`、`canonical_name_normalized String(255) unique index`、`status String(16)` 取值 `none|blacklist|whitelist` 默认 `none` 有索引、`film_count Integer` 默认 0、`created_at`、`updated_at`；`aliases` 关系 `cascade="all, delete-orphan"`。
  - `ActressAlias`（`actress_aliases`）：`id`、`actress_id FK actresses.id ON DELETE CASCADE`、`alias String(255)`、`alias_normalized String(255) unique`、`created_at`。
  - `ActressMark`（`actress_marks`）：`id`、`actress_id FK CASCADE`、`from_status`、`to_status`（String(16)）、`source String(16)` 取值 `web|player|import|merge`、`media_item_id FK jellyfin_media_items.id ON DELETE SET NULL nullable`、`note Text nullable`、`created_at`。
  - `JellyfinMediaActor`（`jellyfin_media_actors`）：主键 `(media_item_id FK jellyfin_media_items.id CASCADE, position Integer)`、`raw_name String(255)`、`name_normalized String(255) index`。
  - `ActressDeleteCandidate`（`actress_delete_candidates`）：`id`、`film_dir Text unique`、`selected Boolean` 默认 True、`added_by String(16)` 取值 `mark|daily`、`added_at`、`remote_state String(16)` 取值 `unchecked|found|missing|error` 默认 `unchecked`、`remote_note Text nullable`、`remote_checked_at nullable`。
  - `ActressKeptFilm`（`actress_kept_films`）：`id`、`film_dir Text unique`、`created_at`。
  - `ActressDeleteBatch`（`actress_delete_batches`）：`id`、`job_id String(128) nullable index`、`status String(16)` 取值 `pending|running|completed|failed|interrupted`、`created_at`、`started_at`、`finished_at`、`deleted_films`、`failed_films`、`skipped_films`（Integer 默认 0）、`jellyfin_refresh String(16) nullable` 取值 `done|skipped|error`、`note Text nullable`；`films` 关系按 id 排序、级联删除。
  - `ActressDeleteBatchFilm`（`actress_delete_batch_films`）：`id`、`batch_id FK CASCADE index`、`film_dir Text`、`number String(255)`、`status String(16)` 取值 `pending|deleted|skipped|failed`、`reason Text nullable`、`error Text nullable`、`finished_at nullable`；`files` 关系按 id 排序、级联删除。
  - `ActressDeleteBatchFile`（`actress_delete_batch_files`）：`id`、`batch_film_id FK CASCADE index`、`group String(16)` 取值 `remote_115|source_strm|organized_dir`、`target Text`、`remote_file_id String(64) nullable`、`status String(16)` 取值 `pending|deleted|missing|failed`、`error Text nullable`、`executed_at nullable`。
  - `JellyfinActressCollection`（`jellyfin_actress_collections`）：与 `JellyfinKeywordCollection` 同构，只是 `keyword_entry_id` 换成 `actress_id FK actresses.id ON DELETE SET NULL nullable index`；`status` 取值 `active|untagged|conflict|retired`。

- [ ] **Step 1: 写模型测试** `tests/actresses/test_models.py`

```python
def test_actress_alias_normalized_is_unique(db_session): ...  # 两个别名同一 alias_normalized → IntegrityError
def test_deleting_media_item_cascades_actor_rows(db_session): ...  # 删 JellyfinMediaItem 后 jellyfin_media_actors 为空
def test_candidate_film_dir_is_unique(db_session): ...
def test_batch_films_and_files_cascade(db_session): ...  # 删批次后三层都清空
```

并在 `tests/test_migrations.py` 仿照 `test_script_jobs_migration_upgrades_and_downgrades` 加 `test_actresses_migration_upgrades_and_downgrades`：升级后 10 张新表都在，降级后都没了。

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_models.py tests/test_migrations.py -q`
Expected: FAIL（`app.models.actresses` 不存在）

- [ ] **Step 3: 写模型和迁移**

迁移 `revision = "20261126_0019"`，`down_revision` 取执行时 `main` 上的最新 head（写计划时是 `"20261125_0018"`；如果已有更新的迁移，就接在它后面并相应改文件名序号）。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2 命令，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/models/actresses.py alembic/versions/20261126_0019_actresses.py alembic/env.py tests/conftest.py tests/actresses/__init__.py tests/actresses/test_models.py tests/test_migrations.py
git commit -m "feat: 女优档案相关数据表与迁移"
```

---

### Task 2: 演员名归一化，扫描时保存 NFO 演员

**Files:**
- Create: `app/services/actresses/__init__.py`、`app/services/actresses/names.py`
- Modify: `app/services/jellyfin/scan_service.py`（`_match_strm_file`、`_save_item`）
- Test: `tests/actresses/test_names.py`、`tests/jellyfin/test_scan_service.py`

**Interfaces:**
- Consumes: Task 1 的 `JellyfinMediaActor`。
- Produces: `normalize_actress_name(raw: str) -> str` = `normalize_keyword_text(raw)` 再去掉全部空格。扫描后每个 `strm_115` 条目在 `jellyfin_media_actors` 里有按 NFO 顺序的演员行（`position` 从 0 开始）；NFO 缺失或解析失败时没有行；本地条目永远没有行。

- [ ] **Step 1: 写失败测试**

```python
# tests/actresses/test_names.py
def test_normalize_actress_name_ignores_spaces_and_width():
    assert normalize_actress_name("三上 悠亜") == normalize_actress_name("三上悠亜")
    assert normalize_actress_name("ＡＢＣ　甲") == "ABC甲"
    assert normalize_actress_name("  ") == ""

# tests/jellyfin/test_scan_service.py（沿用文件里已有的夹具写法）
def test_scan_saves_nfo_actors_in_order(...): ...      # NFO 里 甲、乙 → 两行 position 0/1，raw_name 原样
def test_scan_replaces_actor_rows_on_rescan(...): ...  # 改 NFO 只剩 乙 后重扫 → 只剩一行 乙
def test_scan_no_actor_rows_when_nfo_missing_or_broken(...): ...  # 缺 NFO、坏 XML 都是 0 行；match_state 行为不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_names.py tests/jellyfin/test_scan_service.py -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`_match_strm_file` 改为同时返回 `actor_names: list[str] | None`；`_save_item` 增加关键字参数 `actors: list[str] | None = None`，每次先删该条目的演员行，`source == "strm_115"` 且 `actors` 非空时按顺序写入（同一条目内归一化后重复的名字只保留第一次出现）。关键词匹配逻辑不变。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS，且 `tests/jellyfin` 其余用例不回归）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/__init__.py app/services/actresses/names.py app/services/jellyfin/scan_service.py tests/actresses/test_names.py tests/jellyfin/test_scan_service.py
git commit -m "feat: 扫描时保存 115 番号片的 NFO 演员名单"
```

---

### Task 3: 片子归组与女优档案服务

**Files:**
- Create: `app/services/actresses/films.py`、`app/services/actresses/archive_service.py`
- Modify: `app/services/actresses/names.py`（加索引函数）
- Test: `tests/actresses/test_films.py`、`tests/actresses/test_archive_service.py`

**Interfaces:**
- Consumes: Task 2 的演员行和 `normalize_actress_name`。
- Produces:
  - `names.build_name_index(db) -> dict[str, int]`：全部女优规范名和别名的归一化 → `actress_id`。
  - `films.Film`（frozen dataclass）：`film_dir: str`、`number: str`（番号目录名）、`actor_dir: str`、`strm_paths: tuple[str, ...]`、`media_item_ids: tuple[int, ...]`、`jellyfin_item_ids: tuple[str, ...]`（只含已解析的）、`actor_names: tuple[str, ...]`（原样名字，按归一化去重，保持首次出现顺序）。
  - `films.load_films(db, *, strm_roots: list[str], film_dirs: set[str] | None = None) -> list[Film]`：只取 `source == "strm_115"`、`active`、路径恰好是 `<某个 strm_root>/<演员>/<番号>/<文件>.strm` 的条目，按父目录归组；`film_dirs` 给定时只返回这些。
  - `films.read_nfo_title(film: Film) -> str | None`：读番号目录里第一个 `.nfo` 的 `<title>`，任何错误返回 None。
  - `archive_service.ActressError(ValueError)`：给接口返回 400 的业务错误。
  - `ArchiveService`（实例方法，均以 `db` 为第一个参数，方法内 commit）：
    - `refresh(db, *, strm_roots) -> dict[str, int]`：给有效片子里归一化后在索引中找不到的演员名建档（规范名取首次出现的原样写法，状态 `none`），并重算所有女优的 `film_count`（出现在多少个有效片子里）；返回 `{"created": n, "actresses": 总数}`。
    - `ensure_actresses(db, raw_names: list[str]) -> list[Actress]`：按顺序返回对应女优，缺的当场建档。
    - `set_status(db, actress_ids: list[int], status: str, *, source: str, media_item_id: int | None = None) -> int`：状态真有变化的才写 `ActressMark` 并计数，返回变化人数；`status` 不在三种取值内抛 `ActressError`。**不在这里重算清单**（调用方接着调 Task 4 的 `reconcile`）。
    - `add_alias(db, actress_id: int, alias: str) -> ActressAlias`：归一化后为空、与任何女优的规范名或别名冲突时抛 `ActressError("…已属于 <名字>，请用合并")`。
    - `remove_alias(db, actress_id: int, alias_id: int) -> None`。
    - `merge(db, source_id: int, target_id: int) -> Actress`：一黑一白抛 `ActressError`；否则 source 的规范名和别名都变成 target 的别名，标记记录转给 target，target 状态取两者中非 `none` 的那个，写一条 `source="merge"` 的标记，删除 source，重算 target 的 `film_count`。

- [ ] **Step 1: 写失败测试**

```python
# tests/actresses/test_films.py（用 tmp_path 建 <root>/<演员>/<番号>/ 目录并插入 JellyfinMediaItem + 演员行）
def test_load_films_groups_parts_and_unions_actors(...):
    # ABC-001 下 cd1.strm（NFO 甲、乙）、cd2.strm（NFO 乙、丙）
    # → 一部片，actor_names == ("甲", "乙", "丙")，strm_paths 两个
def test_load_films_skips_inactive_local_and_wrong_depth(...): ...
def test_read_nfo_title_returns_none_on_broken_xml(...): ...

# tests/actresses/test_archive_service.py
def test_refresh_creates_unknown_actors_and_counts_films(...)   # 甲出现在 2 部片 → film_count == 2
def test_refresh_matches_alias_instead_of_creating(...)        # 档案「甲」有别名「甲甲」，NFO 写「甲 甲」→ 不新建
def test_set_status_records_mark_only_on_change(...)           # 连续两次拉黑 → 只有 1 条 ActressMark，第二次返回 0
def test_add_alias_rejects_name_owned_by_other_actress(...)
def test_merge_moves_names_and_marks(...)
def test_merge_rejects_black_and_white(...)
def test_actress_operations_do_not_touch_keyword_entries(...)  # 全流程后 keyword_entries / keyword_aliases 行数不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_films.py tests/actresses/test_archive_service.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 上面 Interfaces 里的函数。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/films.py app/services/actresses/archive_service.py app/services/actresses/names.py tests/actresses/test_films.py tests/actresses/test_archive_service.py
git commit -m "feat: 女优档案建档、改状态、别名与合并"
```

---

### Task 4: 删片规则与待删清单

**Files:**
- Create: `app/services/actresses/rules.py`、`app/services/actresses/candidates_service.py`
- Modify: `app/services/actresses/names.py`（加受保护名字集合）
- Test: `tests/actresses/test_rules.py`、`tests/actresses/test_candidates_service.py`

**Interfaces:**
- Consumes: Task 3 的 `Film`、`load_films`、`build_name_index`、`read_nfo_title`。
- Produces:
  - `names.build_protected_terms(db) -> set[str]`：启用中的 `whitelist` 和 `emby_whitelist` 关键词的规范名、别名，经 `normalize_actress_name` 后的集合。
  - `rules.Verdict`（frozen dataclass）：`deletable: bool`、`black_names: tuple[str, ...]`、`protected_by: tuple[str, ...]`、`kept: bool`。
  - `rules.RuleContext`（dataclass）：字段 `name_index`、`status_by_id: dict[int, str]`、`protected_terms: set[str]`、`kept_dirs: set[str]`；`RuleContext.load(db) -> RuleContext`；`verdict(film: Film) -> Verdict`。规则：`deletable = 有黑名单演员 and 没有受保护演员 and 不在保留名单 and 有演员`（Film 只来自有效条目，所以「仍有效」由 `load_films` 保证）。受保护 = 演员映射到白名单女优，或归一化名字在 `protected_terms` 里。
  - `rules.skip_reason(verdict: Verdict) -> str`：给执行时跳过用的中文原因，如 `已受白名单保护：乙`、`已标为保留`、`没有黑名单演员`。
  - `candidates_service.CandidateView`（dataclass）：`film_dir`、`number`、`title: str | None`、`selected`、`added_by`、`added_at`、`black_names: list[str]`、`other_actors: list[tuple[str, str]]`（名字, 状态）、`remote_state`、`remote_note`。
  - `CandidateService`：
    - `reconcile(db, *, strm_roots, added_by: str) -> tuple[int, int]`：算出全部 `deletable` 的片子；新的插入（`selected=True`），已在清单里的保持原勾选状态，不再满足的删除；返回 `(added, removed)`，commit。
    - `list(db, *, strm_roots) -> list[CandidateView]`：按 `added_at` 倒序，再按番号。
    - `set_selected(db, film_dirs: list[str], selected: bool) -> int`
    - `keep(db, film_dirs: list[str]) -> int`：写保留名单并从清单删除。
    - `unkeep(db, film_dirs: list[str], *, strm_roots) -> int`：删保留记录后 `reconcile(added_by="mark")`。

- [ ] **Step 1: 写失败测试**

```python
# tests/actresses/test_rules.py
def test_black_only_film_is_deletable(...)
def test_film_with_whitelisted_costar_is_protected(...)      # verdict.protected_by == ("乙",)
def test_keyword_whitelist_costar_protects(...)              # KeywordEntry(keyword_type="whitelist", canonical_name="乙")
def test_emby_whitelist_alias_protects(...)                  # emby_whitelist 关键词的别名命中
def test_unmarked_costar_does_not_protect(...)
def test_kept_film_is_not_deletable(...)
def test_film_without_actors_is_never_deletable(...)

# tests/actresses/test_candidates_service.py
def test_reconcile_adds_selected_and_reports_counts(...)     # 拉黑甲 → (2, 0)，两行 selected=True, added_by="mark"
def test_reconcile_keeps_unchecked_state(...)                # set_selected False 后再 reconcile → 仍为 False，不重复插入
def test_reconcile_removes_when_costar_whitelisted(...)      # 把乙加白 → removed == 1
def test_keep_removes_and_daily_does_not_readd(...)          # keep 后 reconcile(added_by="daily") → 不回来
def test_unkeep_puts_film_back(...)
def test_list_shows_reason_and_costars(...)                  # black_names == ["甲"], other_actors == [("乙", "none")]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_rules.py tests/actresses/test_candidates_service.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 上面 Interfaces 里的函数。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/rules.py app/services/actresses/candidates_service.py app/services/actresses/names.py tests/actresses/test_rules.py tests/actresses/test_candidates_service.py
git commit -m "feat: 删片规则与待删清单"
```

---

### Task 5: 删除守卫、STRM 地址索引、115 文件解析

**Files:**
- Create: `app/services/actresses/delete_guard.py`、`app/services/actresses/remote_115.py`
- Modify: `app/services/actresses/candidates_service.py`（加 `check_remote`）
- Test: `tests/actresses/test_delete_guard.py`、`tests/actresses/test_remote_115.py`

**Interfaces:**
- Consumes: `app.services.emby_media_actions.strm_mapping_service.normalize_stream_url`、`decode_115_open_path`；`Fake115Client` / `Real115Client` 的 `get_file(path=...)`。
- Produces:
  - `delete_guard.parse_path_map(value: str) -> list[tuple[str, str]]`：解析 `"a=>b,c=>d"`，空串返回 `[]`。
  - `delete_guard.PathMapper(mappings)`：`map(path: str) -> str` 按最长前缀替换（只在目录边界匹配），没有命中原样返回。
  - `delete_guard.GuardError(Exception)`。
  - `delete_guard.FilmDeleteGuard(source_root: str, organized_root: str)`（两个参数存为同名公开属性，Task 6 用 `guard.source_root` 建地址索引）：
    - `delete_source_strm(path: str) -> str`：必须是 `source_root` 下的 `.strm` 普通文件（不跟随链接），返回 `deleted`；不存在返回 `missing`；其他情况抛 `GuardError`。
    - `delete_film_dir(path: str) -> str`：`path` 必须恰好是 `organized_root/<演员>/<番号>`、是真实目录（不是链接），`shutil.rmtree` 后返回 `deleted`；不存在返回 `missing`；其他抛 `GuardError`。
    - `remove_actor_dir_if_empty(path: str) -> bool`：`path` 必须恰好是 `organized_root/<演员>`；空目录才 `os.rmdir` 并返回 True。
  - `delete_guard.read_strm_url(path: str) -> str | None`：第一行非空内容，读不到返回 None。
  - `delete_guard.build_url_index(root: str) -> dict[str, list[str]]`：`root` 下全部 `.strm` 的 `normalize_stream_url(地址)` → 路径列表（排序）。
  - `remote_115.Remote115`（dataclass）：`state`（`found|missing|error`）、`file_id: str | None`、`remote_path: str | None`、`note: str | None`。
  - `remote_115.resolve_115(client, url: str) -> Remote115`：地址不是 `/d/115_OPEN/...` → `error`（note「不是 115_OPEN 地址」）；`client.get_file(path=remote_path)` 成功且 `data.file_id` 非空 → `found`；抛出的 `Client115Error` 文本包含 `MISSING_MARKERS` 中任一项（不分大小写）→ `missing`；其余异常 → `error`。
  - `remote_115.MISSING_MARKERS = ("not found", "不存在")`：**上线第 1 步只读核实**真实 115 对不存在路径的报错文本，按实际补充；没核实前宁可判成 `error`（这部片整部失败、什么都不删）。
  - `CandidateService.check_remote(db, film_dirs: list[str], client_115, *, strm_roots, mapper: PathMapper) -> int`：逐部片读 STRM 地址并 `resolve_115`，全部 `found` → `found`，全部 `missing` → `missing`，否则 `error`（note 写第一个问题），记 `remote_checked_at`；返回处理部数。

- [ ] **Step 1: 写失败测试**

```python
# tests/actresses/test_delete_guard.py
def test_path_mapper_longest_prefix_on_dir_boundary():
    m = PathMapper(parse_path_map("/mnt/user/v=>/mnt/cache/v,/mnt/user/v/x=>/other"))
    assert m.map("/mnt/user/v/a/b.strm") == "/mnt/cache/v/a/b.strm"
    assert m.map("/mnt/user/v/x/c") == "/other/c"
    assert m.map("/mnt/user/vv/a") == "/mnt/user/vv/a"
def test_delete_film_dir_requires_exact_depth(...)          # 根下一层、三层都 GuardError
def test_delete_film_dir_rejects_symlink_and_outside_root(...)
def test_delete_film_dir_removes_whole_dir(...)
def test_remove_actor_dir_only_when_empty(...)
def test_delete_source_strm_rejects_non_strm(...)
def test_build_url_index_normalizes_scheme_and_host_case(...)

# tests/actresses/test_remote_115.py（fake_client.add_node 一个 path="/AV/ABC-001.mp4" 的节点）
def test_resolve_found(...)        # state == "found", file_id == 节点 id
def test_resolve_missing(...)      # Fake115Client 抛 "Node not found" → "missing"
def test_resolve_rejects_non_115_url(...)
def test_check_remote_marks_mixed_as_error(...)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_delete_guard.py tests/actresses/test_remote_115.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 上面 Interfaces 里的函数（不改 `emby_media_actions/path_guard.py`，Emby 模块保持原样）。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/delete_guard.py app/services/actresses/remote_115.py app/services/actresses/candidates_service.py tests/actresses/test_delete_guard.py tests/actresses/test_remote_115.py
git commit -m "feat: 女优删片的路径守卫与 115 文件解析"
```

---

### Task 6: 删除批次执行

**Files:**
- Create: `app/services/actresses/delete_batch_service.py`
- Test: `tests/actresses/test_delete_batch_service.py`

**Interfaces:**
- Consumes: Task 3 `load_films`；Task 4 `RuleContext`、`skip_reason`；Task 5 全部。
- Produces:
  - `BatchSummary`（dataclass）：`batch_id: int`、`deleted: int`、`failed: int`、`skipped: int`。
  - `DeleteBatchService`：
    - `create_batch(db, *, strm_roots) -> ActressDeleteBatch`：把清单里 `selected=True` 的片子快照成批次片子（`status="pending"`，`number` 取番号目录名），批次 `status="pending"`；一部都没勾时抛 `ActressError("没有勾选的片子")`。
    - `run(db, batch_id: int, *, client_115, guard: FilmDeleteGuard, mapper: PathMapper, strm_roots, progress: Callable[[str, int, int], None]) -> BatchSummary`：处理 `status in ("pending", "failed")` 的片子，批次开始置 `running`，全部处理完：有失败 → `failed`，否则 `completed`，写三个计数和 `finished_at`。每部片处理完 commit 一次。

每部片的处理顺序（任何一步失败：片子置 `failed`、写 `error`、进入下一部，**不执行后面的步骤**）：

1. `load_films(db, strm_roots=..., film_dirs={film_dir})` 为空 → `skipped`，原因「片子已不在扫描结果中」。
2. `RuleContext.load(db).verdict(film)` 不可删 → `skipped`，原因 `skip_reason(verdict)`。
3. `local_dir = mapper.map(film.film_dir)` 不是目录 → `failed`「本地番号目录不存在：<local_dir>（检查路径换算）」。**此时不调用任何 115 接口。**
4. 逐个 STRM 用 `read_strm_url(mapper.map(p))` 取地址，任一为空 → `failed`。
5. 逐个地址 `resolve_115`：`error` → `failed`；`missing` → 写一条 `remote_115` 文件行 `missing`；`found` → `client_115.delete_node(file_id, dry_run=False)`，成功写 `deleted`，异常写 `failed` 并让整部片 `failed`。已是 `deleted`/`missing` 的文件行（续跑时）跳过。
6. 地址索引（本次 `run` 里对 `guard.source_root` 只建一次）里查到的每个路径 → `guard.delete_source_strm`，各写一条 `source_strm` 行。
7. `guard.delete_film_dir(local_dir)` 写 `organized_dir` 行；再 `guard.remove_actor_dir_if_empty(父目录)`。
8. 把 `film.media_item_ids` 对应的 `JellyfinMediaItem.active` 置 False，删除这部片的清单行，片子置 `deleted`。

`progress(f"删除中 {number}", 已处理数, 总数)`。

- [ ] **Step 1: 写失败测试**（`tmp_path` 下建 `source/` 与 `organized/甲/ABC-001/`；STRM 内容是 `http://openlist.test/d/115_OPEN/AV/ABC-001.mp4`；`fake_client` 里放对应节点；`mapper` 把扫描路径前缀换到 `tmp_path`）

```python
def test_create_batch_snapshots_only_selected(...)
def test_create_batch_rejects_empty_selection(...)
def test_run_deletes_115_then_local(...):
    # fake 节点没了、source STRM 没了、ABC-001 目录没了、空的「甲」目录没了、
    # 条目 active False、清单行没了、批次 completed、deleted == 1
def test_115_failure_keeps_local_files(...)          # delete_node 抛异常 → 片子 failed，source STRM 和番号目录都还在
def test_missing_local_dir_blocks_before_115(...)    # mapper 换到不存在的目录 → 片子 failed，fake_client 节点仍在
def test_115_already_missing_still_deletes_local(...)
def test_skips_film_protected_after_batch_created(...)  # 建批次后把乙加白 → skipped，原因含「乙」
def test_resume_retries_failed_without_redoing_done_files(...)  # 第一次本地删除抛错、第二次 run 成功；delete_node 只被调用一次
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_delete_batch_service.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** `DeleteBatchService`。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/delete_batch_service.py tests/actresses/test_delete_batch_service.py
git commit -m "feat: 女优删片批次按 115→STRM→番号目录顺序执行"
```

---

### Task 7: Jellyfin 客户端补充与白名单女优合集

**Files:**
- Modify: `app/services/jellyfin/client.py`
- Create: `app/services/actresses/collection_sync.py`
- Test: `tests/jellyfin/test_client.py`、`tests/actresses/test_collection_sync.py`

**Interfaces:**
- Consumes: Task 3 `load_films`、`build_name_index`；`CollectionSyncService` 的静态方法 `_is_managed`、`_find_unmanaged_same_name`、`_sync_existing_collection` 和常量 `MANAGED_TAG`。
- Produces:
  - `JellyfinClient.refresh_library(library_id: str) -> None`：`POST /Items/{library_id}/Refresh`，参数固定 `Recursive=true`、`MetadataRefreshMode=Default`、`ImageRefreshMode=Default`、`ReplaceAllMetadata=false`、`ReplaceAllImages=false`（即 Jellyfin 界面里的「扫描新增和更新的文件」，不是全量刷新）。
  - `JellyfinClient.get_person_image(name: str) -> tuple[bytes, str] | None`：`GET /Persons/{URL 编码后的名字}` 取 `Id`，再 `GET /Items/{Id}/Images/Primary`；任一步 `JellyfinError` 或没有 Id 时返回 None；返回 `(内容, Content-Type)`。
  - `ActressCollectionSyncService.sync(db, client, *, strm_roots) -> dict[str, int]`：键与 `CollectionSyncService.sync` 相同（`collections_created`、`collections_renamed`、`collections_deleted`、`items_added`、`items_removed`、`conflicts`、`errors`）。依赖关键词合集同步刚写好的 `JellyfinMediaItem.jellyfin_item_id`，因此必须在它之后调用。每个白名单女优一个合集，名字 = 规范名，标签 `MANAGED_TAG`，成员 = 她出演的片子的 `jellyfin_item_ids`；成员为空不建；女优不再是白名单（或已被合并删除）→ 清空并删除 18x 建的合集、映射置 `retired`；与未打标签的同名合集、或与 `jellyfin_keyword_collections` 中 `status="active"` 的 `canonical_name_snapshot` 同名 → 置 `conflict` 只计数不改动。

- [ ] **Step 1: 写失败测试**

```python
# tests/jellyfin/test_client.py（沿用文件里已有的 mock 写法）
def test_refresh_library_uses_default_modes(...)   # 断言方法、路径和 5 个参数值；不出现 FullRefresh
def test_get_person_image_returns_none_when_missing(...)

# tests/actresses/test_collection_sync.py（假 Jellyfin 客户端，仿 tests/jellyfin/test_collection_sync.py）
def test_creates_collection_for_whitelisted_actress(...)
def test_ignores_blacklisted_and_unmarked(...)
def test_retires_collection_after_unwhitelist(...)
def test_actress_collection_conflicts_with_keyword_collection_name(...)
def test_leaves_unmanaged_collections_untouched(...)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_client.py tests/actresses/test_collection_sync.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 两个客户端方法和 `ActressCollectionSyncService`。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/jellyfin/client.py app/services/actresses/collection_sync.py tests/jellyfin/test_client.py tests/actresses/test_collection_sync.py
git commit -m "feat: 白名单女优 Jellyfin 合集与库扫描、人物图片接口"
```

---

### Task 8: 配置开关、任务类型与每日任务链

**Files:**
- Modify: `app/core/config.py`、`.env.example`
- Create: `app/services/actresses/job_runner.py`
- Modify: `app/services/jellyfin/job_runner.py`（每日循环与 `sync_work`）
- Test: `tests/actresses/test_job_runner.py`、`tests/jellyfin/test_job_runner.py`

**Interfaces:**
- Consumes: Task 3/4/5/6/7。
- Produces:
  - `Settings` 新字段：`actress_enabled: bool = Field(default=False, alias="ACTRESS_ENABLED")`、`actress_source_root: str | None = Field(default=None, alias="ACTRESS_SOURCE_ROOT")`（可写的 `porn_tv1`）、`actress_organized_root: str | None = Field(default=None, alias="ACTRESS_ORGANIZED_ROOT")`（可写的 `302porn_tv1`）、`actress_path_map: str = Field(default="", alias="ACTRESS_PATH_MAP")`。`.env.example` 加这四项，注释写生产取值示例 `/mnt/cache/docker1/alist-strm/video/porn_tv1`、`/mnt/cache/docker1/alist-strm/video/302porn_tv1`、`/mnt/user/docker1/alist-strm/video=>/mnt/cache/docker1/alist-strm/video`。
  - `app/services/actresses/job_runner.py`：
    - `JOB_REFRESH = "actress:refresh"`、`JOB_DELETE = "actress:delete"`
    - `actress_enabled(settings) -> bool` = `settings.actress_enabled and jellyfin_scan_enabled(settings)`
    - `actress_delete_ready(settings) -> bool` = `actress_enabled(settings)` 且两个可写根目录都已配置
    - `refresh_work(db, progress) -> dict`：`ArchiveService().refresh` 后 `CandidateService().reconcile(added_by="daily")`，返回 `{"created", "actresses", "candidates_added", "candidates_removed"}`
    - `delete_work(batch_id: int, client_115) -> JobWork`：按配置构造 `FilmDeleteGuard`、`PathMapper`，调 `DeleteBatchService().run`；`deleted > 0` 且 `jellyfin_sync_enabled(settings)` 时用 `find_library_id(settings.media_library_strm_roots)` 找库并 `refresh_library`，批次 `jellyfin_refresh` 记 `done` / `error`（异常不影响批次结果），否则记 `skipped`；返回 `BatchSummary` 的字典形式。
  - `jellyfin_daily_loop`：扫描之后、合集同步之前，`actress_enabled(settings)` 为真时建 `JOB_REFRESH` 任务并运行（`JobAlreadyRunning` 时记日志跳过）。
  - `sync_work`：关键词合集同步之后，`actress_enabled(settings)` 为真时再跑 `ActressCollectionSyncService().sync`，结果并入摘要，键加前缀 `actress_`。
  - 避免循环导入：`app/services/actresses/job_runner.py` 可以从 `app.services.jellyfin.job_runner` 导入开关函数；反过来 `app/services/jellyfin/job_runner.py` 对 `app.services.actresses.*` 一律在函数内部导入。

- [ ] **Step 1: 写失败测试**

```python
# tests/actresses/test_job_runner.py
def test_refresh_work_builds_archive_and_candidates(...)
def test_delete_ready_requires_both_roots(...)
def test_delete_work_refreshes_jellyfin_only_when_something_deleted(...)
def test_delete_work_succeeds_when_jellyfin_refresh_fails(...)   # refresh_library 抛 JellyfinError → 批次 completed，jellyfin_refresh == "error"

# tests/jellyfin/test_job_runner.py
def test_daily_loop_runs_actress_refresh_between_scan_and_sync(...)  # 记录调用顺序 == ["scan", "actress", "sync", ...]
def test_daily_loop_skips_actress_when_disabled(...)
def test_sync_work_includes_actress_collections_when_enabled(...)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_job_runner.py tests/jellyfin/test_job_runner.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 配置、`app/services/actresses/job_runner.py`、每日循环和 `sync_work` 的改动。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/core/config.py .env.example app/services/actresses/job_runner.py app/services/jellyfin/job_runner.py tests/actresses/test_job_runner.py tests/jellyfin/test_job_runner.py
git commit -m "feat: 女优功能开关、刷新与删除任务、接入每日任务链"
```

---

### Task 9: 接口

**Files:**
- Create: `app/schemas/actresses.py`、`app/api/routes/actresses.py`
- Modify: `app/main.py`（`app.include_router(actresses.router)`）
- Modify（生成）：`frontend/openapi.json`、`frontend/src/api/schema.gen.ts`
- Test: `tests/actresses/test_routes.py`

**Interfaces:**
- Consumes: Task 3～8 的服务；`get_db`；`request.app.state.client_115`。
- Produces（`router = APIRouter(prefix="/actresses", tags=["actresses"])`；**固定路径必须声明在 `/{actress_id}` 之前**；业务错误 `ActressError` → 400；功能关闭或删除未就绪 → 409；`JobAlreadyRunning` → 409）：

| 方法 路径 | 请求 | 返回 |
|---|---|---|
| `GET /actresses` | `status`（三选一，可空）、`q`、`sort`（`film_count`\|`name`，默认 `film_count`）、`page`（默认 1）、`page_size`（默认 50，最大 200） | `ActressListResponse{items: list[ActressSummary], total, counts{none, blacklist, whitelist}}`；`ActressSummary{id, canonical_name, aliases: list[str], status, film_count, candidate_count}` |
| `GET /actresses/by-media` | `jellyfin_item_id` 或 `path`（二选一） | `MediaActorsResponse{film_dir, number, in_candidates, actors: list{actress_id, name, status}}`；按 NFO 顺序，缺档的当场 `ensure_actresses`；找不到片子 404 |
| `POST /actresses/status` | `ActressStatusRequest{actress_ids: list[int], status, source: "web"\|"player", media_item_id: int \| None}` | `ActressStatusResponse{changed, candidates_added, candidates_removed}`（先 `set_status` 再 `reconcile(added_by="mark")`） |
| `POST /actresses/refresh` | — | `{job_id}`（手动触发 `JOB_REFRESH`） |
| `GET /actresses/candidates` | — | `CandidateListResponse{items: list[CandidateItem], total, selected}` |
| `POST /actresses/candidates/select` | `{film_dirs, selected: bool}` | `{count}` |
| `POST /actresses/candidates/keep` | `{film_dirs}` | `{count}` |
| `POST /actresses/candidates/check-remote` | `{film_dirs}`（最多 50） | `{count}` |
| `GET /actresses/kept` | — | `{items: list{film_dir, number, created_at}}` |
| `POST /actresses/kept/remove` | `{film_dirs}` | `{count}` |
| `GET /actresses/delete-batches` | — | 批次列表（id、状态、三个计数、时间） |
| `POST /actresses/delete-batches` | — | `{batch_id, job_id}`：`create_batch` 后用 `create_job(db, JOB_DELETE)` + `submit_job(job_id, delete_work(batch_id, client_115))`，并把 `job_id` 写回批次 |
| `GET /actresses/delete-batches/{batch_id}` | — | 批次详情：片子列表（番号、状态、原因、错误）及每部片的文件行 |
| `POST /actresses/delete-batches/{batch_id}/resume` | — | `{batch_id, job_id}`；只允许 `failed`、`interrupted`、`running`（且没有运行中的 `JOB_DELETE`） |
| `GET /actresses/{actress_id}` | — | `ActressDetail{...ActressSummary, marks: list{from_status, to_status, source, media_item_id, created_at}, films: list{film_dir, number, title, actors: list{name, status}, protected: bool, in_candidates: bool}}` |
| `GET /actresses/{actress_id}/image` | — | 图片字节（`Response`，带 Content-Type）；Jellyfin 未配置或取不到 → 404 |
| `POST /actresses/{actress_id}/aliases` | `{alias}` | `ActressDetail`；随后 `reconcile(added_by="mark")`（别名会改变演员归属） |
| `DELETE /actresses/{actress_id}/aliases/{alias_id}` | — | `ActressDetail`；随后 `reconcile(added_by="mark")` |
| `POST /actresses/{actress_id}/merge` | `{into_id}` | 合并后的 `ActressDetail`；随后 `reconcile(added_by="mark")` |

- [ ] **Step 1: 写失败测试** `tests/actresses/test_routes.py`（照 `tests/jellyfin/test_routes.py` 的 `client` 夹具，额外设 `ACTRESS_ENABLED`）

```python
def test_list_filters_and_counts(...)
def test_status_change_returns_candidate_counts(...)       # 拉黑甲 → {"changed": 1, "candidates_added": 2, "candidates_removed": 0}
def test_player_mark_records_source_and_media(...)         # source="player" → ActressMark.source/media_item_id
def test_by_media_lookup_creates_missing_archive_entries(...)
def test_static_paths_not_shadowed_by_actress_id(...)      # GET /actresses/candidates 返回 200 而不是 422
def test_create_batch_returns_409_when_disabled(...)
def test_create_batch_returns_400_when_nothing_selected(...)
def test_image_returns_404_when_jellyfin_unavailable(...)
def test_merge_conflict_returns_400(...)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_routes.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** schemas 和路由，注册到 `app/main.py`。

- [ ] **Step 4: 重新生成前端类型**

Run: `scripts/gen-api-types.sh`
Expected: 取回更新后的 `frontend/openapi.json` 和 `frontend/src/api/schema.gen.ts`

- [ ] **Step 5: 跑测试确认通过**

Run: `scripts/remote-test.sh backend tests/actresses tests/api/test_openapi_snapshot.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/schemas/actresses.py app/api/routes/actresses.py app/main.py frontend/openapi.json frontend/src/api/schema.gen.ts tests/actresses/test_routes.py
git commit -m "feat: 女优档案、待删清单与删除批次接口"
```

---

### Task 10: 旧 Emby 黑白名单导入

**Files:**
- Create: `app/services/actresses/emby_import.py`、`scripts/actress_import_emby_lists.py`
- Test: `tests/actresses/test_emby_import.py`

**Interfaces:**
- Consumes: Task 3 `ArchiveService.ensure_actresses`、`set_status`；Task 4 `reconcile`。
- Produces:
  - `ImportRow`（dataclass）：`name`、`target_status`（`blacklist|whitelist`）、`result`（`will_set|set|unchanged|conflict`）、`note`。
  - `import_emby_lists(db, *, apply: bool, strm_roots) -> list[ImportRow]`：读启用中的 `emby_blacklist` / `emby_whitelist` 关键词（规范名为人名）；同一人同时在两边 → `conflict` 不导入；已是目标状态 → `unchanged`；`apply=False` 只返回 `will_set`；`apply=True` 用 `set_status(source="import")` 写入，然后 `reconcile(added_by="mark")`。关键词表只读。
  - `scripts/actress_import_emby_lists.py`：默认只列出（打印每行 `结果 名字 → 状态`，最后打印汇总），加 `--apply` 才写入。写法仿 `scripts/jellyfin_display_names.py`。

- [ ] **Step 1: 写失败测试**

```python
def test_dry_run_lists_without_writing(...)
def test_apply_sets_status_with_import_source(...)
def test_conflicting_names_are_skipped(...)
def test_keyword_entries_untouched(...)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh backend tests/actresses/test_emby_import.py -q`
Expected: FAIL

- [ ] **Step 3: 实现** 服务函数和命令行脚本。

- [ ] **Step 4: 跑测试确认通过**（同 Step 2，Expected: PASS）

- [ ] **Step 5: 提交**

```bash
git add app/services/actresses/emby_import.py scripts/actress_import_emby_lists.py tests/actresses/test_emby_import.py
git commit -m "feat: 旧 Emby 黑白名单一次性导入女优档案"
```

---

### Task 11: 前端「女优」页

**Files:**
- Create: `frontend/src/api/actresses.ts`、`frontend/src/pages/ActressesPage.tsx`、`frontend/src/pages/ActressesPage.test.tsx`
- Modify: `frontend/src/App.tsx`（`<Route path="/actresses" …>`）、`frontend/src/layout/navigation.tsx`（「流程」组 Jellyfin 之后加 `{ key: '/actresses', label: '女优' }` 和 `{ key: '/actress-deletes', label: '女优删除' }`，图标沿用已引入的）
- Modify（如冒烟测试按导航逐页渲染）：`frontend/src/pages/workflowGroup.smoke.test.tsx`

**Interfaces:**
- Consumes: Task 9 的接口；类型从 `schema.gen.ts` 取。
- Produces: `frontend/src/api/actresses.ts` 导出 `listActresses`、`getActress`、`setActressStatus`、`addActressAlias`、`removeActressAlias`、`mergeActress`、`actressImageUrl(id)`，以及 Task 12 用的 `listCandidates`、`selectCandidates`、`keepCandidates`、`checkCandidatesRemote`、`listKept`、`removeKept`、`createDeleteBatch`、`listDeleteBatches`、`getDeleteBatch`、`resumeDeleteBatch`。

页面按设计文档 5.9 的草图：顶部三个状态计数；搜索、状态筛选、排序；表格列为头像（`actressImageUrl`，加载失败显示占位）、名字（含别名）、状态、片数、待删数、操作（拉黑 / 加白 / 设为未标）；可多选批量改状态；点一行打开详情抽屉（别名增删、合并到另一位、标记记录、她的片子，每部片显示同片演员状态和是否受保护）。改状态成功后用 `message` 提示「已放进删除草稿 N 部 / 草稿移出 N 部」。

- [ ] **Step 1: 写失败测试** `ActressesPage.test.tsx`（照 `JellyfinPage.test.tsx` 用 `vi.mock('@/api/actresses')`）

```tsx
it('按状态显示计数并列出女优')
it('点拉黑后调用 setActressStatus 并提示放进草稿的部数')   // 断言参数 {actress_ids:[1], status:'blacklist', source:'web'}
it('头像加载失败时显示占位')
it('详情抽屉里添加别名')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh frontend`
Expected: FAIL（`ActressesPage` 不存在）

- [ ] **Step 3: 实现** API 模块、页面、路由和导航。

- [ ] **Step 4: 跑测试确认通过**

Run: `scripts/remote-test.sh frontend`
Expected: PASS（含 build 和 lint）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/actresses.ts frontend/src/pages/ActressesPage.tsx frontend/src/pages/ActressesPage.test.tsx frontend/src/App.tsx frontend/src/layout/navigation.tsx frontend/src/pages/workflowGroup.smoke.test.tsx
git commit -m "feat: 前端女优页"
```

（冒烟测试没改就不要 add 它。）

---

### Task 12: 前端「女优删除」页

**Files:**
- Create: `frontend/src/pages/ActressDeletePage.tsx`、`frontend/src/pages/ActressDeletePage.test.tsx`
- Modify: `frontend/src/App.tsx`（`<Route path="/actress-deletes" …>`）

**Interfaces:**
- Consumes: Task 11 的 API 函数。

三个标签页：

- **待删清单**：顶部「待删 N 部，本次勾选 M 部」、全选 / 全不选、「检查 115」（对勾选的片子调 `checkCandidatesRemote`，每次最多 50 部，分批调）、「确认删除」。表格每行：勾选框、番号、标题、因为谁、同片演员及状态、115 状态（未检查 / 可解析 / 已不存在 / 有问题+原因）、「保留」按钮。「确认删除」先弹确认框：「将删除 M 部片子的 115 原文件和本地 STRM，115 文件进回收站。确定？」，确定后 `createDeleteBatch`，切到「历史批次」并打开该批次。
- **历史批次**：批次列表；打开一个批次时每 3 秒刷新一次 `getDeleteBatch` 直到状态不是 `running`，显示每部片的状态、原因、错误和文件行；`failed` / `interrupted` 的批次有「重试失败的」按钮（`resumeDeleteBatch`）。
- **保留名单**：列表 + 「撤销保留」。

- [ ] **Step 1: 写失败测试**

```tsx
it('只把勾选的片子算进本次删除，不勾选的留在清单')
it('确认删除前弹确认框，确定后调用 createDeleteBatch')
it('点保留后调用 keepCandidates 并从列表移除')
it('批次运行中轮询，完成后停止')
it('失败批次显示重试按钮')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `scripts/remote-test.sh frontend`
Expected: FAIL

- [ ] **Step 3: 实现** 页面和路由。

- [ ] **Step 4: 跑测试确认通过**

Run: `scripts/remote-test.sh frontend`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/ActressDeletePage.tsx frontend/src/pages/ActressDeletePage.test.tsx frontend/src/App.tsx
git commit -m "feat: 前端女优删除页（待删清单、历史批次、保留名单）"
```

---

### Task 13: 文档、进度日志与全量测试

**Files:**
- Create: `docs/actresses.md`（中文使用说明：功能是什么、四个配置项、每日链里的位置、删一部片的顺序和失败时会怎样、怎么续跑、导入脚本用法、上线检查清单）
- Create: `progress/<实施完成日期>-actress-archive.md`（`What was done`、`Testing`、`Notes`（Changed files / Rollback：关闭 `ACTRESS_ENABLED` 即停用；迁移可降级到上一个 revision））
- Modify: `docs/superpowers/specs/2026-11-25-actress-archive-design.md` 状态行改为「已实施（待上线）」

- [ ] **Step 1: 全量后端测试**

Run: `scripts/remote-test.sh backend`
Expected: 全部 PASS；如有与本功能无关的既有失败，记进进度日志，不能写成全套通过。

- [ ] **Step 2: 全量前端测试**

Run: `scripts/remote-test.sh frontend`
Expected: PASS（test + build + lint）

- [ ] **Step 3: 写文档和进度日志**

- [ ] **Step 4: 提交**

```bash
git add docs/actresses.md progress/<日期>-actress-archive.md docs/superpowers/specs/2026-11-25-actress-archive-design.md
git commit -m "docs: 女优档案使用说明与实施记录"
```

---

## 上线（不在本计划内，按设计文档第八节逐项找用户批准）

1. 只读统计生产数据（演员数、多人片比例、NFO 缺失比例、旧 Emby 名单条数），核实路径换算（同一文件在 `/mnt/user/...` 和 `/mnt/cache/...` 下 inode 一致），核实 115 对不存在路径的报错文本并补进 `MISSING_MARKERS`。
2. 备份数据库后部署（迁移自动执行），配置四个 `ACTRESS_*` 项，打开 `ACTRESS_ENABLED`。
3. 首次真实删除只删 1 部用户指定的片子，按设计文档验收第 5 条核对，观察一天。
4. 用户同意后跑 `scripts/actress_import_emby_lists.py`，先看列表再 `--apply`。
