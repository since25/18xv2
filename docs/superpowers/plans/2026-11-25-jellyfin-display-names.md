# Jellyfin 本地视频显示名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 18x 把本地已整理库里每个视频在 Jellyfin 的显示名改成 `关键词/资源包 · 序号` 并锁定，18x 合集按名字排序，每天自动维护。

**Architecture:** 纯函数 `compute_display_names` 按路径算出应有名字；`DisplayNameSyncService` 分页读取 Jellyfin 条目的名字和锁定字段，只对不一致的条目写回；作为新后台任务 `jellyfin:names` 接在每日合集同步之后，另有命令行脚本做只预览和单关键词试跑。

**Tech Stack:** Python 3 / FastAPI 项目内服务层、SQLAlchemy、httpx（`httpx.MockTransport` 测试）、pytest。

**Spec:** `docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`

## Global Constraints

- 显示名格式：`<分组名> · <序号>`，分隔符是「空格 + 中点 `·` + 空格」；序号位数 = `max(2, len(str(分组视频数)))`，左侧补零，从 1 开始。
- 分组：相对路径 ≥3 段取前两段 `关键词/资源包`；2 段取 `关键词`；1 段或不在任何本地根目录下的不处理。
- 只处理 `JellyfinMediaItem.source == "local"` 且 `active` 的条目；115（`strm_115`）一律不动。
- 只给有效映射（`JellyfinKeywordCollection.status == "active"`）的合集设置排序，不碰其他合集。
- 不写媒体目录；不调用任何刷新接口，尤其禁止 `MetadataRefreshMode=FullRefresh`。
- 新开关 `JELLYFIN_DISPLAY_NAMES_ENABLED`，默认 `false`；只控制每日自动执行，命令行手动执行不受它限制（但仍需 Jellyfin 地址和 API Key）。
- 不新增数据库表和字段，不加 Alembic 迁移。
- 代码注释、docstring、文档用中文。
- 测试只在 Spark 上跑：`scripts/remote-test.sh backend [pytest 参数]`，本机不跑 pytest。
- 按用户全局约定：不自动建 worktree、不在每个任务后提交；全部完成并写好进度日志后，问用户一次是否提交。

## Review Focus

- 文件名自然排序：`x (2).mp4` 必须排在 `x (10).mp4` 前，大小写不同的同名文件顺序稳定 → Task 1 `test_natural_sort_parenthesized_numbers`。
- 根目录前缀撞车：根目录 `/r/已整理` 不能把 `/r/已整理2/甲/包/a.mp4` 当成自己的文件；根目录带不带结尾 `/` 结果一样 → Task 1 `test_root_prefix_requires_path_boundary`。
- 用户按目录名（可能是别名）试跑：`--keyword` 传别名也要找到对应关键词 → Task 3 `test_keyword_filter_accepts_alias`。
- 资源包里有视频还没被 Jellyfin 扫到：它不占序号，其余视频编号连续 → Task 3 `test_items_missing_in_jellyfin_do_not_take_numbers`。
- 名字对但锁被手工去掉：要重新上锁，否则下次重扫会被改回文件名 → Task 3 `test_relocks_when_name_correct_but_unlocked`。

---

### Task 1: 命名规则（纯函数）

**Files:**
- Create: `app/services/jellyfin/display_names.py`
- Test: `tests/jellyfin/test_display_names.py`

**Interfaces:**
- Produces: `compute_display_names(paths: Iterable[str], local_roots: Sequence[str]) -> dict[str, str]`（键是原路径，值是显示名；不处理的路径不出现在结果里）；`natural_key(text: str) -> tuple`

- [ ] **Step 1: 写失败的测试**

```python
from app.services.jellyfin.display_names import compute_display_names

ROOT = "/r/已整理"

def test_three_level_paths_numbered_within_pack():
    names = compute_display_names([f"{ROOT}/甲/包/b.mp4", f"{ROOT}/甲/包/a.mp4"], [ROOT])
    assert names == {f"{ROOT}/甲/包/a.mp4": "甲/包 · 01", f"{ROOT}/甲/包/b.mp4": "甲/包 · 02"}

def test_natural_sort_parenthesized_numbers():
    paths = [f"{ROOT}/甲/包/x (10).mp4", f"{ROOT}/甲/包/x (2).mp4", f"{ROOT}/甲/包/10.mp4", f"{ROOT}/甲/包/2.mp4"]
    names = compute_display_names(paths, [ROOT])
    assert names[f"{ROOT}/甲/包/2.mp4"] == "甲/包 · 01"
    assert names[f"{ROOT}/甲/包/10.mp4"] == "甲/包 · 02"
    assert names[f"{ROOT}/甲/包/x (2).mp4"] == "甲/包 · 03"
    assert names[f"{ROOT}/甲/包/x (10).mp4"] == "甲/包 · 04"

def test_deeper_subfolders_join_pack_group():
    paths = [f"{ROOT}/甲/包/视图/y.mp4", f"{ROOT}/甲/包/z.mp4", f"{ROOT}/甲/包/V/x.mp4"]
    names = compute_display_names(paths, [ROOT])
    assert names[f"{ROOT}/甲/包/V/x.mp4"] == "甲/包 · 01"
    assert names[f"{ROOT}/甲/包/z.mp4"] == "甲/包 · 02"
    assert names[f"{ROOT}/甲/包/视图/y.mp4"] == "甲/包 · 03"

def test_file_directly_under_keyword_uses_keyword_only():
    assert compute_display_names([f"{ROOT}/甲__乙/a.mp4"], [ROOT]) == {f"{ROOT}/甲__乙/a.mp4": "甲__乙 · 01"}

def test_file_directly_under_root_or_outside_roots_skipped():
    assert compute_display_names([f"{ROOT}/a.mp4", "/别处/甲/包/a.mp4"], [ROOT]) == {}

def test_root_prefix_requires_path_boundary():
    assert compute_display_names([f"{ROOT}2/甲/包/a.mp4"], [ROOT]) == {}
    assert compute_display_names([f"{ROOT}/甲/包/a.mp4"], [ROOT + "/"]) == {f"{ROOT}/甲/包/a.mp4": "甲/包 · 01"}

def test_padding_grows_with_group_size():
    paths = [f"{ROOT}/甲/包/{i}.mp4" for i in range(1, 101)]
    names = compute_display_names(paths, [ROOT])
    assert names[f"{ROOT}/甲/包/1.mp4"] == "甲/包 · 001"
    assert names[f"{ROOT}/甲/包/100.mp4"] == "甲/包 · 100"
```

- [ ] **Step 2: 在 Spark 上确认失败**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_display_names.py`
Expected: FAIL，`ModuleNotFoundError: app.services.jellyfin.display_names`

- [ ] **Step 3: 实现 `display_names.py`**

`natural_key`：用 `re.split(r"(\d+)", text)` 切块，数字块转 `int`，文本块用 `casefold()`，最后附上原字符串保证大小写不同时顺序稳定。`compute_display_names`：根目录先 `rstrip("/")`，路径必须以 `root + "/"` 开头才算属于它（多个根目录取第一个匹配的）；分组键是分组名字符串（多根目录同名分组合并编号）；每组按相对路径的 `natural_key` 排序后编号。

- [ ] **Step 4: 在 Spark 上确认通过**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_display_names.py`
Expected: 7 passed

---

### Task 2: Jellyfin 客户端：读名字与锁、改名上锁、合集排序

**Files:**
- Modify: `app/services/jellyfin/client.py`（`iter_media_paths` 附近新增方法；分页逻辑抽成私有 `_iter_item_pages(params)` 供两者共用，`iter_media_paths` 行为不变）
- Test: `tests/jellyfin/test_client.py`

**Interfaces:**
- Produces:
  - `JellyfinClient.iter_media_items() -> Iterator[dict]`，每项 `{"id": str, "path": str, "name": str, "locked_fields": list[str] | None}`；返回里没有 `LockedFields` 键时为 `None`。请求参数 `Recursive=true`、`IsFolder=false`、`Fields=Path,Settings`。
  - `JellyfinClient.set_item_name(item_id: str, name: str, *, lock: bool = True) -> None`：带管理员 `userId` 读完整条目，设 `Name`；`lock=True` 时 `LockedFields` 在原有基础上追加 `"Name"`（已有则不重复），`lock=False` 时从中去掉 `"Name"`（回滚用）；再 `POST /Items/{id}`。
  - `JellyfinClient.ensure_sort_name_order(collection_id: str) -> bool`：读完整条目，`DisplayOrder` 已是 `"SortName"` 返回 `False` 且不写；否则设为 `"SortName"` 后 `POST`，返回 `True`。

- [ ] **Step 0: 只读实测生产 Jellyfin（不写任何东西）**

在生产 18x 容器里用现有 `.env` 的地址和 Key，各发一次只读请求并记录结论到进度日志：
1. `GET /Items?Recursive=true&IsFolder=false&Fields=Path,Settings&Limit=3`，看条目里是否有 `LockedFields`；
2. 对任一 18x 合集 `GET /Items/{id}?userId=<管理员>`，看是否有 `DisplayOrder` 键及当前值。
命令里不得打印 API Key。若第 1 项没有 `LockedFields`，实现不变（`locked_fields` 为 `None`，见 Task 3 的判断规则）；若第 2 项没有 `DisplayOrder`，`ensure_sort_name_order` 仍按接口写，但在进度日志记下"排序待试跑确认"。

- [ ] **Step 1: 写失败的测试**

```python
def test_iter_media_items_reads_name_and_locks():
    seen: list[dict] = []
    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"Items": [
            {"Id": "i1", "Path": "/r/甲/包/a.mp4", "Name": "a", "LockedFields": ["Name"]},
            {"Id": "i2", "Path": "/r/甲/包/b.mp4", "Name": "b"},
        ], "TotalRecordCount": 2})
    client = JellyfinClient("http://jf.test", "k", 3, 50, httpx.MockTransport(handler), sleep_fn=lambda _: None)
    assert list(client.iter_media_items()) == [
        {"id": "i1", "path": "/r/甲/包/a.mp4", "name": "a", "locked_fields": ["Name"]},
        {"id": "i2", "path": "/r/甲/包/b.mp4", "name": "b", "locked_fields": None},
    ]
    assert seen[0]["Fields"] == "Path,Settings"

def test_set_item_name_appends_name_lock():
    # /Users 返回一个管理员；GET /Items/i1 返回 {"Id":"i1","Name":"old","LockedFields":["Overview"]}
    # 断言 GET /Items/i1 带 userId；POST /Items/i1 的 json 中
    # Name == "甲/包 · 01" 且 LockedFields == ["Overview", "Name"]

def test_set_item_name_does_not_duplicate_lock():
    # GET 返回 LockedFields == ["Name"]，POST 后仍是 ["Name"]

def test_set_item_name_unlock_removes_name_lock():
    # GET 返回 LockedFields == ["Overview", "Name"]；set_item_name("i1", "a", lock=False)
    # POST json Name == "a" 且 LockedFields == ["Overview"]

def test_ensure_sort_name_order_writes_only_when_needed():
    # DisplayOrder == "PremiereDate" → 返回 True，POST json["DisplayOrder"] == "SortName"
    # DisplayOrder == "SortName" → 返回 False，没有 POST 请求
```

（后三个测试照现有 `test_client.py` 里 `MockTransport` 按 `request.method` 和 `request.url.path` 分支返回的写法补全，断言即注释所列。）

- [ ] **Step 2: 在 Spark 上确认失败**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_client.py`
Expected: 新增 5 个 FAIL（`AttributeError` 或参数错误），原有测试仍 PASS

- [ ] **Step 3: 实现上述三个方法和 `_iter_item_pages`**

- [ ] **Step 4: 在 Spark 上确认通过**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_client.py`
Expected: 全部 PASS

---

### Task 3: 显示名同步服务

**Files:**
- Create: `app/services/jellyfin/display_name_sync_service.py`
- Test: `tests/jellyfin/test_display_name_sync.py`

**Interfaces:**
- Consumes: Task 1 `compute_display_names`；Task 2 `iter_media_items`、`set_item_name`、`ensure_sort_name_order`
- Produces:
  - `class UnknownKeyword(ValueError)`
  - `DisplayNameSyncService().sync(db: Session, client, *, local_roots: Sequence[str], dry_run: bool = False, keyword: str | None = None, restore: bool = False, sample_size: int = 20, progress: Callable[[str, int, int], None] | None = None) -> dict`
  - 返回字典固定键：`dry_run`(bool)、`restore`(bool)、`to_update`、`updated`、`unchanged`、`failed`、`not_in_jellyfin`、`skipped`（不在根目录下或只有 1 层）、`collections_ordered`、`errors`、`samples`（`[{"path", "old", "new"}]`，最多 `sample_size` 条）

**行为（实现者照此写，测试即下方清单）：**
1. 读取 `source == "local"` 且 `active` 的 `JellyfinMediaItem`（预加载 `keyword_links`）。
2. `client.iter_media_items()` 全部读完建 `path → 条目` 索引；抛 `JellyfinError` 时 `errors = 1` 直接返回，不写任何东西。
3. 只有在 Jellyfin 索引里找到的本地视频参与编号（用 Jellyfin 返回的 id）；找不到的计入 `not_in_jellyfin`。
4. 在全部参与编号的视频上调用 `compute_display_names`，没有名字的计入 `skipped`。
5. `keyword` 不为空时，先按 `normalize_keyword_text` 在白名单关键词的规范名和别名（`KeywordAlias.alias_normalized`）里找，找不到抛 `UnknownKeyword`；只处理关联到该关键词的视频，但编号仍按第 4 步的全量结果。
6. 需要写回 = `名字 != 应有名字` 或 `locked_fields is not None 且 "Name" 不在其中`。不需要的计入 `unchanged`；需要的计入 `to_update` 并采样；非只预览时调用 `set_item_name`，成功计 `updated`，任何异常计 `failed` 后继续。
7. 非只预览时，对 `status == "active"` 且有合集 ID 的映射调用 `ensure_sort_name_order`（指定了 `keyword` 时只处理该关键词的映射），返回 `True` 计入 `collections_ordered`，异常计 `failed`。
8. 每处理 500 条调用一次 `progress("改名中", 已处理, 总数)`。
9. `restore=True`（回滚）：应有名字改为文件名去掉扩展名（`PurePosixPath(path).stem`），需要写回 = `名字 != stem` 或 `locked_fields is not None 且 "Name" 在其中`，写回调用 `set_item_name(id, stem, lock=False)`；不处理合集排序；`keyword`、`dry_run` 照常生效。

- [ ] **Step 1: 写失败的测试**

测试里的 `FakeDisplayClient` 在内存里保存 `{path: {"id", "name", "locked_fields"}}`，`set_item_name` 会更新名字并把 `"Name"` 加进锁、记录调用，可配置某个 id 抛 `JellyfinError`；`ensure_sort_name_order` 记录调用并返回 `True`。用 `test_collection_sync.py` 的 `_entry`、`_media_link`、`_mapped_collection` 写法造数据，根目录用 `/r/已整理`。

```python
def test_dry_run_reports_without_writing(db_session):
    # 甲/包/a.mp4、甲/包/b.mp4 在 Jellyfin 名为 "a"、"b"
    # result["to_update"] == 2, result["updated"] == 0, client.set_calls == []
    # result["samples"][0] == {"path": ".../甲/包/a.mp4", "old": "a", "new": "甲/包 · 01"}
    # client.order_calls == []

def test_apply_renames_and_second_run_is_idempotent(db_session):
    # 第一次：updated == 2；第二次：to_update == 0, unchanged == 2, 第二次没有新的 set 调用

def test_relocks_when_name_correct_but_unlocked(db_session):
    # Jellyfin 名字已是 "甲/包 · 01" 但 locked_fields == [] → set_item_name 被调用一次
    # locked_fields 为 None 且名字正确 → 不调用

def test_items_missing_in_jellyfin_do_not_take_numbers(db_session):
    # 甲/包/a、b、c，b 不在 Jellyfin → a 改成 "甲/包 · 01"，c 改成 "甲/包 · 02"，not_in_jellyfin == 1

def test_keyword_filter_only_touches_that_keyword(db_session):
    # 甲/包/a.mp4 关联关键词「甲」，乙/包/a.mp4 关联「乙」；keyword="甲" → 只改甲的

def test_keyword_filter_accepts_alias(db_session):
    # 关键词「甲」有别名「甲酱」；keyword="甲酱" 等同 keyword="甲"

def test_unknown_keyword_raises(db_session):
    # keyword="不存在" → pytest.raises(UnknownKeyword)

def test_single_failure_does_not_stop_others(db_session):
    # a 的 id 配置为抛错 → failed == 1, updated == 1

def test_listing_failure_returns_error_without_writes(db_session):
    # iter_media_items 抛 JellyfinError → errors == 1，没有任何 set / order 调用

def test_inactive_and_115_items_untouched(db_session):
    # active=False 的本地条目、source="strm_115" 的条目即使在 Jellyfin 里也不改名

def test_orders_only_active_mapped_collections(db_session):
    # 一个 active 映射、一个 retired 映射 → order_calls 只含 active 的合集 ID，collections_ordered == 1

def test_restore_sets_stem_and_unlocks(db_session):
    # Jellyfin 名为 "甲/包 · 01"、locked_fields == ["Name"] 的 .../甲/包/a.mp4
    # restore=True → set_item_name 收到 ("a", lock=False)，updated == 1，order_calls == []
```

- [ ] **Step 2: 在 Spark 上确认失败**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_display_name_sync.py`
Expected: FAIL，模块不存在

- [ ] **Step 3: 按上面的行为实现服务**

- [ ] **Step 4: 在 Spark 上确认通过**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_display_name_sync.py`
Expected: 12 passed

---

### Task 4: 后台任务、每日接入、开关、命令行和文档

**Files:**
- Modify: `app/core/config.py`（Jellyfin 配置段，约第 81–89 行后）
- Modify: `app/services/jellyfin/job_runner.py`
- Create: `scripts/jellyfin_display_names.py`
- Modify: `.env.example`（Jellyfin 段）、`docker/jellyfin/README.md`（新增「本地视频显示名」一节）、`scripts/README.md`（脚本列表）
- Test: `tests/jellyfin/test_job_runner.py`

**Interfaces:**
- Consumes: Task 3 `DisplayNameSyncService`、`UnknownKeyword`
- Produces:
  - 配置 `jellyfin_display_names_enabled: bool = Field(default=False, alias="JELLYFIN_DISPLAY_NAMES_ENABLED")`
  - `JOB_NAMES = "jellyfin:names"`
  - `jellyfin_display_names_enabled(settings) -> bool`：`jellyfin_sync_enabled(settings)` 且开关为真
  - `names_work(*, dry_run: bool = False, keyword: str | None = None, restore: bool = False) -> JobWork`：未配置地址或 Key 时抛 `RuntimeError("Jellyfin 同步未启用或缺少地址/API Key")`；否则用与 `sync_work` 相同方式建客户端，调用 `DisplayNameSyncService().sync(..., local_roots=settings.media_library_local_roots, dry_run=..., keyword=..., restore=..., progress=progress)`
  - `run_names_job(job_id: str, *, dry_run: bool = False, keyword: str | None = None, restore: bool = False) -> None`
  - `jellyfin_daily_loop`：合集同步之后，若 `jellyfin_display_names_enabled(settings)`，同样以 `start_job` + `asyncio.to_thread(run_names_job, job_id)` 执行，`JobAlreadyRunning` 记日志跳过
  - 脚本 `python scripts/jellyfin_display_names.py [--dry-run] [--keyword 名字] [--restore]`（`--restore` 为回滚：名字改回文件名并解锁）：`start_job(db, JOB_NAMES)`（已有同类任务时打印提示、退出码 1）→ `run_names_job` → 用 `BackgroundJobService.get` 读回任务，把摘要按 JSON（`ensure_ascii=False`, `indent=2`）打印；任务状态不是成功时打印错误并退出码 1。脚本不看 `JELLYFIN_DISPLAY_NAMES_ENABLED`。

- [ ] **Step 1: 写失败的测试**

```python
def test_display_names_enabled_requires_flag_and_sync_config():
    base = dict(jellyfin_enabled=True, jellyfin_base_url="http://jf", jellyfin_api_key="k")
    assert job_runner.jellyfin_display_names_enabled(SimpleNamespace(**base, jellyfin_display_names_enabled=True)) is True
    assert job_runner.jellyfin_display_names_enabled(SimpleNamespace(**base, jellyfin_display_names_enabled=False)) is False
    assert job_runner.jellyfin_display_names_enabled(
        SimpleNamespace(jellyfin_enabled=True, jellyfin_base_url=None, jellyfin_api_key="k", jellyfin_display_names_enabled=True)
    ) is False

def test_run_names_job_records_summary_and_passes_options(db_session, monkeypatch):
    # 仿照 test_run_cover_job_records_summary：替换 SessionLocal、get_settings、DisplayNameSyncService.sync
    # sync 记录收到的 dry_run=True、keyword="甲"、local_roots，返回 {"to_update": 1, ...}
    # run_names_job(job_id, dry_run=True, keyword="甲") 后任务状态为成功，summary["to_update"] == 1

def test_run_names_job_records_failure_without_config(db_session, monkeypatch):
    # settings 缺 API Key → 任务状态为失败，错误信息含 "缺少地址/API Key"
```

- [ ] **Step 2: 在 Spark 上确认失败**

Run: `scripts/remote-test.sh backend tests/jellyfin/test_job_runner.py`
Expected: 新增 3 个 FAIL

- [ ] **Step 3: 实现配置、任务函数、每日接入和脚本；补 `.env.example`（`JELLYFIN_DISPLAY_NAMES_ENABLED=false` 加一行中文注释）与两份 README**

`docker/jellyfin/README.md` 新增一节写明：规则（引用设计文档）、开关、四条命令（只预览、单关键词试跑、全量、`--restore` 回滚），以及「先关开关再回滚」「禁止 FullRefresh」。命令示例统一为在生产容器内执行：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --dry-run`。

- [ ] **Step 4: 在 Spark 上跑后端全量**

Run: `scripts/remote-test.sh backend`
Expected: 全部通过；如有与本次无关的既有失败，逐条记录到进度日志，不能写"全部通过"。

- [ ] **Step 5: 写进度日志并询问是否提交**

写 `progress/2026-11-25-jellyfin-display-names.md`（What was done / Testing / Notes：Changed files、Rollback，含 Task 2 Step 0 的实测结论）。按用户约定问一次是否提交，提交范围只含本计划涉及的文件、设计文档和这份日志；工作区里其他会话留下的未跟踪 `progress/*.md` 和 `visuals/` 不带上。

---

### Task 5: 部署与试跑（每一步先经用户批准）

不写代码，按顺序执行，每一步都先向用户说明影响再执行：

- [ ] **Step 1: 部署**：按生产手册合并、推送、重建 `docker-app-1`。部署前检查主工作区有没有其他会话的未提交文件并列给用户。`JELLYFIN_DISPLAY_NAMES_ENABLED` 保持关闭。
- [ ] **Step 2: 只预览**：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --dry-run`，把待改数、未入库数、示例名字给用户看。
- [ ] **Step 3: 单关键词试跑**：先只读确认「本地已整理」库 `MetadataSavers` 为空、`SaveLocalMetadata` 为 false（2026-11-25 已核对一次，试跑前再看一眼）。用户挑一个关键词，`--keyword <名字>` 执行；记录耗时，按单条耗时估算全量时间；试跑后确认该关键词目录里没有新增 `.nfo` 文件（设计第八节第 5 条）。
- [ ] **Step 4: 用户验收**：用户在 SenPlayer 和 Jellyfin 网页打开该合集，确认名字和顺序（设计第八节第 1、2 条）；再执行一次同一命令，确认 `to_update == 0`（第 3 条）。
- [ ] **Step 5: 重扫保持**：经用户同意后，在 Jellyfin 里对「本地已整理」做一次普通扫描（不是 FullRefresh），确认试跑合集的名字不变（第 4 条）。不保持就停下，回到设计。
- [ ] **Step 6: 全量与开启每日**：用户同意后在夜里执行全量；完成后把生产 `.env` 的 `JELLYFIN_DISPLAY_NAMES_ENABLED` 改为 `true` 并重建容器（生产配置变更，单独批准）。
- [ ] **Step 7: 收尾记录**：在部署日志里记录各步结果、耗时和回滚方式。
