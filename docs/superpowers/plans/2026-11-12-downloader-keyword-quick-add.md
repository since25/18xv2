# 下载器搜索词一键加黑/白名单 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收件箱搜索框旁一键把搜索词加入白/黑名单，先预览影响，确认后立即重算候选。

**Architecture:** 新增后端服务函数：写入关键词后只重算「归一化标题包含该词」的资源包（复用 `_load_terms` / `_match_package`）；预览走同一流程后 `db.rollback()`。前端在 `CandidatesInbox` 工具栏加两个按钮和一个确认弹窗。

**Tech Stack:** FastAPI + SQLAlchemy；React + Ant Design + vitest。

**Spec:** `docs/superpowers/specs/2026-11-12-downloader-keyword-quick-add-design.md`

## Global Constraints

- 匹配规则不变：`normalize_keyword_text(x).casefold()` 子串包含。
- 新建关键词 `merge_policy="normal"`，`status="active"`，经 `KeywordRegistryService.create_entry_no_commit`（带操作日志）。
- 归一化后少于 2 个字符拒绝；已存在且类型不同拒绝（HTTP 409），提示去关键词页修改。
- 示例标题最多 5 个。
- 测试只在 Spark 上跑：`scripts/remote-test.sh backend|frontend`。
- 注释、提示文案中文。

## Review Focus

- 预览不能落库：dry_run 后关键词表、候选状态与调用前完全一致。
- 搜索词带空格 / 全角 / 大小写差异时，与同步时的匹配结果一致（走同一归一化）。
- 已忽略、已下载完成的资源包加白名单时不应生成候选（`_match_package` 已处理，测试钉住）。
- 加白名单时标题同时含已有黑名单词的包不生成候选。
- 词已作为别名存在（同类型）时不重复建词，仍正常重算。

---

### Task 1: 后端服务 + 接口

**Files:**
- Create: `app/services/downloader/keyword_quick_add.py`
- Modify: `app/schemas/downloader.py`（新增请求体）、`app/api/routes/downloader.py`（新增路由）
- Test: `tests/downloader/test_keyword_quick_add.py`、`tests/api/test_downloader_routes.py`

**Interfaces:**
- Produces:
  - `class KeywordQuickAddError(ValueError)`，属性 `status_code: int`（400 或 409）。
  - `quick_add_keyword(db: Session, *, keyword: str, list_type: Literal["whitelist", "blacklist"], dry_run: bool) -> dict`
    返回 `{"keyword": str, "list_type": str, "entry_status": "created" | "existing", "keyword_entry_id": int | None, "packages_affected": int, "candidates_created": int, "candidates_dismissed": int, "sample_titles": list[str]}`；dry_run 时 `keyword_entry_id` 为 None。
    约定：调用方会话不能有未提交改动（dry_run 会 `db.rollback()`）。
  - `DownloaderKeywordQuickAddRequest(keyword: str (min_length=1), list_type: Literal["whitelist","blacklist"], dry_run: bool = True)`
  - `POST /downloader/keyword-quick-add` → 上述 dict；`KeywordQuickAddError` 映射为对应状态码 + `detail` 文案。

- [ ] **Step 1: 写失败测试**（`tests/downloader/test_keyword_quick_add.py`，种子数据用 `DownloaderSyncService.sync_packages` + 假远端，种子后 `db_session.commit()`）
  - `test_blacklist_dry_run_reports_but_writes_nothing`：白名单 Foo，包「Foo Bar pack」「Foo Baz pack」；dry_run 加黑 `bar` → `candidates_dismissed == 1`、`packages_affected == 1`、`sample_titles == ["Foo Bar pack"]`；之后 `KeywordEntry` 中无 bar，待确认仍 2 条。
  - `test_blacklist_commit_dismisses_matching_candidates`：同上 dry_run=False → 待确认剩 1 条，bar 为 blacklist、active。
  - `test_whitelist_commit_creates_candidates_from_unmatched`：无关键词，包「Qux pack」；加白 `QUX` → `candidates_created == 1`，`list_inbox(view="candidates")` 有 1 条。
  - `test_whitelist_skips_ignored_and_blacklisted_packages`：包「Qux one」已忽略，包「Qux bad」含已有黑名单 bad → `candidates_created == 0`。
  - `test_rejects_short_keyword`：`" a "` → `KeywordQuickAddError`，status 400。
  - `test_rejects_existing_keyword_of_other_type`：Foo 已是白名单，加黑 `foo` → status 409。
  - `test_existing_alias_same_type_reuses_entry`：Foo 有别名 Fu，加白 `fu` → `entry_status == "existing"`，关键词数不变。
- [ ] **Step 2: 跑测试确认失败** — `scripts/remote-test.sh backend tests/downloader/test_keyword_quick_add.py` → ImportError。
- [ ] **Step 3: 实现 `quick_add_keyword`**：校验 → `find_entry_by_keyword` 判断已存在/冲突 → `create_entry_no_commit` → `db.flush()` → `_load_terms(db)` → 取全部 `DownloaderPackage`，按归一化标题包含该词过滤 → 逐个 `_match_package` 累加计数 → dry_run 则 `db.rollback()`，否则 `db.commit()`。
- [ ] **Step 4: 加路由与请求体**，路由测试 `test_keyword_quick_add_route_preview_and_conflict`：预览 200 且不落库；冲突返回 409 且 `detail` 含「关键词页」。
- [ ] **Step 5: 跑 `scripts/remote-test.sh backend` 全量** → 全部通过。
- [ ] **Step 6: 提交** `git add` 上述文件；`feat: 下载器搜索词一键加入白名单/黑名单（后端）`。

### Task 2: 前端按钮与确认弹窗

**Files:**
- Modify: `frontend/src/api/downloader.ts`、`frontend/src/pages/downloader/CandidatesInbox.tsx`
- Test: `frontend/src/pages/downloader/CandidatesInbox.test.tsx`

**Interfaces:**
- Consumes: Task 1 的接口。
- Produces: `quickAddKeyword(keyword: string, listType: 'whitelist' | 'blacklist', dryRun: boolean): Promise<KeywordQuickAddResult>`，类型字段与后端返回一致。

- [ ] **Step 1: 写失败测试**
  - `adds the search text to the blacklist after previewing the impact`：输入「bar」→ 出现「加入黑名单」按钮 → 点击后以 `dryRun=true` 调用，弹窗显示「将移走 1 条待确认候选」和示例标题 → 点「确认加入黑名单」以 `dryRun=false` 调用，并重新加载列表。
  - `hides the quick add buttons when search is empty`。
  - `shows the conflict message from the server`：预览抛出「已在白名单，请到关键词页修改」→ `message.error` 显示该文案，不弹确认框。
- [ ] **Step 2: 跑测试确认失败** — `scripts/remote-test.sh frontend`。
- [ ] **Step 3: 实现**：搜索框后、`search.trim()` 非空时显示两个按钮；预览结果放在 antd `Modal`，文案：「涉及 N 个资源包，将新增 X 条 / 移走 Y 条待确认候选」+ 示例标题列表；黑名单确认按钮 `danger`；成功后 `message.success` 并 `load(1)`。
- [ ] **Step 4: 跑 `scripts/remote-test.sh frontend`**（含 build）→ 通过；lint 只允许原有 2 个错误。
- [ ] **Step 5: 提交** `feat: 下载器收件箱搜索词一键加黑/白名单（前端）`。

### Task 3: 文档与进度日志

- [ ] 在 `docs/` 中下载器说明处补一段新入口说明（找现有下载器文档位置）。
- [ ] 写 `progress/2026-11-12-downloader-keyword-quick-add.md`（What was done / Testing / Notes）。
- [ ] 部署前向用户确认。
