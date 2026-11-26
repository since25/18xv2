# 女优头像（Gfriends → Jellyfin 人物主图）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 18x 按女优档案名到 Gfriends 头像库找图，下载后上传为 Jellyfin 人物主图；每日分批补齐，也支持手动指定几个人跑。

**Architecture:**
- 新模块 `gfriends.py` 负责：Gfriends 索引的缓存与名字查找、MDC 对照表、图片下载。
- 新模块 `avatar_service.py` 负责：挑人、找图、贴图、记状态。
- `JellyfinClient` 新增两个方法：查人物、上传人物主图。
- 新增任务 `actress:avatars`，接在每日链「女优刷新」之后。
- 头像接口改为取不到规范名的图时再试别名。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、httpx、pytest（全部在 Spark 上用 `scripts/remote-test.sh` 跑）、React + antd + vitest。

**Spec:** `docs/superpowers/specs/2026-11-26-actress-avatars-design.md`

## Global Constraints

- 测试不在本机跑：后端用 `scripts/remote-test.sh backend [路径]`，前端用 `scripts/remote-test.sh frontend`；改了接口或模型后运行 `scripts/gen-api-types.sh`。
- 代码注释、文档、提交说明用中文；测试夹具里的名字只用「甲」「乙」这类占位，不用真实演员名。
- Gfriends 索引地址：`https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json`；图片地址：`https://raw.githubusercontent.com/gfriends/gfriends/master/Content/<来源目录>/<实际文件名>`（去掉 `?t=...` 后缀）。
- 索引缓存超过 7 天才重新下载；下载失败沿用旧缓存，没有缓存时任务失败。
- `not_found`、`no_person` 两种状态满 7 天后重查；`uploaded`、`present` 永不回查。
- 单张图下载超时 30 秒，大小上限 5MB，只接受 `image/*`；每张图之间至少间隔 0.5 秒。
- 新配置：`ACTRESS_AVATARS_ENABLED`（默认 false）、`ACTRESS_AVATARS_PER_RUN`（默认 300）、`ACTRESS_AVATAR_NAME_MAP`（默认空）。
- 已有主图的 Jellyfin 人物一律不动；只按完整名字精确匹配，不做模糊匹配。
- 手动接口只要求 `ACTRESS_ENABLED` 打开、Jellyfin 已配置，不受 `ACTRESS_AVATARS_ENABLED` 限制。
- 提交：按用户约定，各任务不单独提交，记下提交说明，全部做完后问用户一次，再只添加本功能的文件。

## Review Focus

1. **对照表文件不存在或不是合法 XML**：不报错，退回只做直接匹配，任务摘要写明「未用对照表」。测试在 Task 2。
2. **同一女优多个名字对应多个 Jellyfin 人物，其中部分已有图**：只给没图的传，状态记 `uploaded`。测试在 Task 4。
3. **Gfriends 返回非图片（比如 HTML 错误页）或超过 5MB**：这人记 `error`，不上传，继续处理下一个人。测试在 Task 4。
4. **合并、加别名、删别名之后**：她的 `avatar_state` 重置为 `pending`，下次重新找。测试在 Task 4。
5. **头像接口规范名取不到、别名能取到**：返回别名人物的图。测试在 Task 5。

---

### Task 1: 数据列、迁移与配置

**Files:**
- Modify: `app/models/actresses.py`（`Actress` 加四列）
- Create: `alembic/versions/20261126_0020_actress_avatars.py`（down_revision 为 `20261126_0019`）
- Modify: `app/core/config.py`、`.env.example`
- Test: `tests/test_migrations.py`、`tests/actresses/test_models.py`

**Interfaces:**
- Produces：
  - `Actress` 新增四列：
    - `avatar_state: str`，`String(16)`，默认 `"pending"`，带 server_default，建索引；
    - `avatar_source: str | None`，`Text`；
    - `avatar_note: str | None`，`Text`；
    - `avatar_checked_at: datetime | None`，`DateTime(timezone=True)`。
  - `Settings` 新增三项：
    - `actress_avatars_enabled: bool = False`（alias `ACTRESS_AVATARS_ENABLED`）；
    - `actress_avatars_per_run: int = 300`（alias `ACTRESS_AVATARS_PER_RUN`）；
    - `actress_avatar_name_map: str | None = None`（alias `ACTRESS_AVATAR_NAME_MAP`）。

- [ ] **Step 1: 写失败测试**
  - `test_models.py::test_actress_avatar_defaults`：新建 `Actress` 并 commit 后，`avatar_state == "pending"`，另外三列都为 None。
  - `test_migrations.py`：在现有的升降级测试里加断言。升到 head 后 `actresses` 表有这四列；降到 `20261126_0019` 后这四列都没了。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh backend tests/test_migrations.py tests/actresses/test_models.py -q`，预期失败。
- [ ] **Step 3: 实现模型列、迁移（`add_column` / `drop_column`）和配置三项**；`.env.example` 加这三项，每项上面一行中文说明。
- [ ] **Step 4: 跑测试确认通过**：同上命令，预期全部通过。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: 女优头像状态列与配置`

---

### Task 2: Gfriends 索引、名字查找与图片下载

**Files:**
- Create: `app/services/actresses/gfriends.py`
- Test: `tests/actresses/test_gfriends.py`

**Interfaces:**
- Produces：
  - `normalize_gfriends_name(name: str) -> str`：去掉空白和 `・･·（）()[]【】`，再转小写。
  - `class GfriendsIndex`：
    - `from_filetree(filetree: dict, name_map: dict[str, str] | None = None) -> GfriendsIndex`：`filetree` 是 `Filetree.json` 解析后的 dict；
    - `find(names: list[str]) -> str | None`：返回相对路径 `"<来源目录>/<实际文件名>"`，实际文件名不带 `?t=`；
    - `used_name_map: bool`：是否用上了对照表。
  - `load_name_map(path: str | None) -> dict[str, str] | None`：读 MDC 的 `mapping_actor.xml`，把 `keyword`（逗号分隔）、`zh_cn`、`zh_tw` 里每个名字归一化后映射到 `jp` 原文。路径为空、文件读不了或 XML 解析失败时返回 None，不抛错。
  - `load_filetree(cache_path: Path, *, fetch: Callable[[], bytes], now: datetime, max_age_days: int = 7) -> dict`：缓存文件的修改时间在 7 天内就直接读缓存；否则调用 `fetch` 并写回缓存；`fetch` 抛错时有缓存就读缓存，没有缓存就抛 `GfriendsError`。
  - `gfriends_image_url(rel_path: str) -> str`。
  - `download_image(url: str, *, timeout: float = 30, max_bytes: int = 5 * 1024 * 1024, transport: httpx.BaseTransport | None = None) -> tuple[bytes, str]`：返回（内容, Content-Type）。非 200、不是 `image/*`、超过上限时抛 `GfriendsError`。
  - `class GfriendsError(RuntimeError)`。

**查找表规则：**
- 每个文件按以下写法各登记一次：显示名（键去掉 `.jpg`）、去掉末尾 `-数字` 后的显示名、`A（B）` 形式里的 A 和 B。
- 同一个归一化名在多个来源目录里出现时，取来源目录名排序最小的那个（`sorted(Content)` 的顺序）。
- `find` 按 `names` 的顺序逐个名字查，每个名字先直接查，再经对照表换成 `jp` 查，第一个命中就返回。

- [ ] **Step 1: 写失败测试**，`filetree` 用内存 dict 构造，名字用占位：
  - `test_find_direct_and_variants`：
    - `{"Content": {"a-源": {"甲.jpg": "AI-Fix-甲.jpg?t=1", "乙-834.jpg": "乙-834.jpg?t=2", "丙（丁）.jpg": "丙（丁）.jpg?t=3"}}}`；
    - `find(["甲"]) == "a-源/AI-Fix-甲.jpg"`；
    - `find(["乙"])` 命中 `乙-834.jpg`；
    - `find(["丁"])` 命中 `丙（丁）.jpg`；
    - `find(["甲 "])` 也命中（空格被归一化掉）。
  - `test_find_prefers_first_folder_sorted`：同名文件同时在 `b-源` 和 `a-源` 里，返回 `a-源/...`。
  - `test_find_via_name_map`：`name_map={"中甲": "日甲"}`，Gfriends 里只有 `日甲.jpg`，`find(["中甲"])` 命中，并且 `used_name_map is True`。
  - `test_find_tries_names_in_order_and_returns_none`：所有名字都查不到时返回 None。
  - `test_load_name_map_parses_keyword_and_zh`：临时 XML 里写 `<a zh_cn="中甲" zh_tw="中甲台" jp="日甲" keyword=",中甲,别甲,"/>`，读出来三个归一化名都映射到 `"日甲"`。
  - `test_load_name_map_missing_or_bad_returns_none`：路径为 None、文件不存在、内容不是 XML，三种情况都返回 None。
  - `test_load_filetree_uses_fresh_cache` / `test_load_filetree_refetches_stale_cache` / `test_load_filetree_falls_back_to_stale_on_fetch_error` / `test_load_filetree_raises_without_cache`：用 `os.utime` 设置缓存文件的修改时间，`fetch` 用计数桩。
  - `test_download_image_rejects_non_image_and_oversize`：用 MockTransport，`text/html` 抛 `GfriendsError`；6MB 的 `image/jpeg` 抛 `GfriendsError`；正常的 jpeg 返回（内容, `"image/jpeg"`）。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh backend tests/actresses/test_gfriends.py -q`。
- [ ] **Step 3: 实现 `gfriends.py`**：XML 用 `xml.etree.ElementTree` 解析；下载用 `httpx.Client(timeout=..., transport=...)`，按响应头 `Content-Length` 和实际读到的字节数两道把关。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: Gfriends 头像索引、名字对照与图片下载`

---

### Task 3: Jellyfin 查人物与上传人物主图

**Files:**
- Modify: `app/services/jellyfin/client.py`
- Test: `tests/jellyfin/test_client.py`

**Interfaces:**
- Produces：
  - `JellyfinClient.get_person(name: str) -> dict | None`：`GET /Persons/{quote(name, safe='')}`，返回 `{"id": str, "has_primary": bool}`。HTTP 404 或返回里没有 Id 时返回 None；其他错误照常抛 `JellyfinError`。
  - `JellyfinClient.upload_person_image(person_id: str, content: bytes, content_type: str) -> None`：`POST /Items/{person_id}/Images/Primary`，请求体是 `base64.b64encode(content)`，请求头 `Content-Type: content_type`。
  - `_request` 新增两个可选参数 `content: bytes | None`、`headers: dict | None`，透传给 `session.request`，原有调用不受影响。

- [ ] **Step 1: 写失败测试**（MockTransport）：
  - `test_get_person_returns_id_and_primary_flag`：返回 `{"Id": "p1", "ImageTags": {"Primary": "t"}}` 时得到 `{"id": "p1", "has_primary": True}`；`ImageTags` 为空时 `has_primary` 为 False；请求路径里的名字已编码，含 `/` 和空格的名字不会把路径拆开。
  - `test_get_person_404_returns_none`。
  - `test_upload_person_image_posts_base64`：断言 method 是 POST、路径是 `/Items/p1/Images/Primary`、`Content-Type: image/jpeg`、请求体等于 `base64.b64encode(b"\xff\xd8abc")`。
  - `test_upload_person_image_raises_on_error`：返回 400 时抛 `JellyfinError`。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh backend tests/jellyfin/test_client.py -q`。
- [ ] **Step 3: 实现**：`get_person` 的 404 判断要在 `_request` 抛错之前做，可以先单独发一次请求，或给 `_request` 加 `allow_404` 参数，由实现者选。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: Jellyfin 客户端查人物与上传人物主图`

---

### Task 4: 头像服务（挑人、找图、贴图、记状态）及名字变化时重置

**Files:**
- Create: `app/services/actresses/avatar_service.py`
- Modify: `app/services/actresses/archive_service.py`（`add_alias`、`remove_alias`、`merge` 里把对应女优的 `avatar_state` 置为 `pending`）
- Test: `tests/actresses/test_avatar_service.py`、`tests/actresses/test_archive_service.py`

**Interfaces:**
- Consumes：
  - Task 1 的四列；
  - Task 2 的 `GfriendsIndex.find`、`gfriends_image_url`、`GfriendsError`；
  - Task 3 的 `get_person`、`upload_person_image`。
- Produces：
  - `AvatarService.run(db, *, index: GfriendsIndex, client: JellyfinClient, fetch_image: Callable[[str], tuple[bytes, str]], now: datetime, limit: int, actress_ids: list[int] | None = None, sleep: Callable[[float], None] = time.sleep, interval: float = 0.5) -> dict[str, int]`。
  - 返回的键：`processed`、`uploaded`、`present`、`not_found`、`no_person`、`error`，再加 `used_name_map`（0 或 1）。

**挑人规则：**
- 给了 `actress_ids` 时：只处理这几个人，不看当前状态，也不受 `limit` 以外的限制。
- 没给时，按以下条件挑人：
  - `avatar_state` 是 `pending` 或 `error`；
  - 或者 `avatar_state` 是 `not_found` / `no_person`，且 `avatar_checked_at` 早于 `now - 7 天`。
- 排序：`film_count` 从多到少，再按 `id` 从小到大。最多取 `limit` 人。

**对一个人的处理：**
1. 名字列表为 `[canonical_name, *按 id 排序的别名]`。
2. `index.find(names)` 返回 None → 记 `not_found`。
3. 对每个名字调 `get_person`，得到存在的人物；一个都不存在 → 记 `no_person`，`avatar_source` 记命中的路径。
4. 所有人物都已有主图 → 记 `present`。
5. 否则下载一次图片，上传给每个还没主图的人物 → 记 `uploaded`。
6. 下载或上传抛 `GfriendsError` / `JellyfinError` → 记 `error`，`avatar_note` 写原因，继续处理下一个人。
7. 每个人处理完都更新 `avatar_checked_at = now` 并 commit。
8. 每下载过一张图，就在处理下一个人之前调用一次 `sleep(interval)`。

- [ ] **Step 1: 写失败测试**：用假 index（字典桩）、假 client（记录调用）、假 `fetch_image`、`sleep` 记录桩：
  - `test_uploads_to_persons_without_primary`：甲有别名乙；`get_person("甲")` 有主图，`get_person("乙")` 没主图；结果只给乙上传，状态 `uploaded`，`avatar_source` 是命中的路径。
  - `test_present_when_all_persons_have_primary`：不下载、不上传，状态 `present`。
  - `test_not_found_and_no_person`：两种状态都正确写入，`avatar_checked_at == now`。
  - `test_bad_image_marks_error_and_continues`：第一个人的 `fetch_image` 抛 `GfriendsError("不是图片")`，第二个人照常 `uploaded`，第一个人 `avatar_note` 里含「不是图片」。
  - `test_selection_rules_and_order`：`uploaded` / `present` 的人不选；6 天前的 `not_found` 不选；8 天前的选；`limit=2` 时按片数取前两人。
  - `test_actress_ids_forces_rerun`：`uploaded` 的人带 `actress_ids` 时照样处理。
  - `test_sleeps_between_downloads`：处理 2 个需要下载的人时，`sleep` 被调用 1 次，参数是 `0.5`。
  - `test_archive_service.py` 里新增 `test_name_changes_reset_avatar_state`：`add_alias`、`remove_alias`、`merge`（看目标女优）之后，`avatar_state == "pending"`。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh backend tests/actresses/test_avatar_service.py tests/actresses/test_archive_service.py -q`。
- [ ] **Step 3: 实现 `avatar_service.py` 并改 `archive_service.py` 三处**。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: 女优头像服务，名字变化时重置头像状态`

---

### Task 5: 任务、每日链、接口和头像接口改为试别名

**Files:**
- Modify: `app/services/actresses/job_runner.py`、`app/services/jellyfin/job_runner.py`（每日链）、`app/api/routes/actresses.py`、`app/schemas/actresses.py`
- Test: `tests/actresses/test_job_runner.py`、`tests/actresses/test_routes.py`、`tests/jellyfin/test_job_runner.py`

**Interfaces:**
- Consumes：Task 2 的 `load_filetree`、`load_name_map`、`GfriendsIndex.from_filetree`、`download_image`；Task 4 的 `AvatarService.run`。
- Produces：
  - `JOB_AVATARS = "actress:avatars"`；
  - `actress_avatars_enabled(settings) -> bool`：`actress_enabled(settings)` 为真、`jellyfin_sync_enabled(settings)` 为真、`actress_avatars_enabled` 为真，三者都满足才为真；
  - `avatars_work(*, actress_ids: list[int] | None = None, limit: int | None = None) -> JobWork`：
    - 索引缓存放 `data/actress-avatars/Filetree.json`；
    - `limit` 不传时用 `settings.actress_avatars_per_run`；
    - 返回 `AvatarService.run` 的摘要。
  - 每日链：在「女优刷新」之后、「合集同步」之前，`actress_avatars_enabled(settings)` 为真时建 `JOB_AVATARS` 任务并运行。失败只记在它自己的任务上，不挡后面的步骤。写法照抄同文件里女优刷新那一段。
  - 接口 `POST /api/actresses/avatars/refresh`：
    - 请求体 `ActressAvatarRefreshRequest {actress_ids: list[int] | None = None, limit: int | None = Field(None, ge=1, le=2000)}`；
    - 返回 `ActressJobResponse`，状态码 202；
    - 前置检查是 `_require_enabled` 加 Jellyfin 已配置，后者不满足时返回 409「Jellyfin 未配置」；
    - 同类任务在跑时返回 409「头像任务正在运行，请等它结束」；
    - **这个路由要注册在 `/{actress_id}` 系列路由之前**。
  - `ActressDetail` 新增：`avatar_state: Literal["pending", "uploaded", "present", "not_found", "no_person", "error"]`、`avatar_note: str | None`、`avatar_checked_at: datetime | None`。
  - `GET /api/actresses/{id}/image`：依次用规范名、按 id 排序的别名调 `get_person_image`，第一个取到的就返回；全部取不到时返回 404。

- [ ] **Step 1: 写失败测试**：
  - job_runner：
    - `test_actress_avatars_enabled_requires_all_three`；
    - `test_avatars_work_uses_per_run_limit_and_passes_ids`：替换 `AvatarService.run`，断言收到的 `limit` 和 `actress_ids`。
  - jellyfin 每日链：照现有女优刷新的链式测试，断言开关打开时 `actress:avatars` 排在 `actress:refresh` 之后、`jellyfin:sync` 之前；开关关闭时不跑。
  - routes：
    - `test_avatar_refresh_ignores_avatar_switch`：`ACTRESS_AVATARS_ENABLED` 关、`ACTRESS_ENABLED` 开时返回 202；
    - `test_avatar_refresh_requires_actress_enabled`：返回 409；
    - `test_avatar_refresh_busy_409`；
    - `test_detail_includes_avatar_fields`；
    - `test_image_falls_back_to_alias`：假 client 对规范名返回 None、对别名返回图片，接口返回 200，内容是那张图。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh backend tests/actresses tests/jellyfin/test_job_runner.py -q`。
- [ ] **Step 3: 实现**，再运行 `scripts/gen-api-types.sh` 重新生成前端类型。
- [ ] **Step 4: 跑测试确认通过**：同上命令，加上 `tests/api/test_openapi_snapshot.py`。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: 女优头像任务、手动接口与每日链；头像接口按别名回退`

---

### Task 6: 前端——补头像按钮与详情里的头像状态

**Files:**
- Modify: `frontend/src/api/actresses.ts`、`frontend/src/pages/ActressesPage.tsx`
- Test: `frontend/src/pages/ActressesPage.test.tsx`

**Interfaces:**
- Consumes：Task 5 的接口和重新生成的类型。
- Produces：
  - `refreshActressAvatars(body?: { actress_ids?: number[]; limit?: number }): Promise<ActressJobResponse>`。
  - 女优页工具栏加按钮「补头像」，点后调用不带参数的接口，提示「已开始补头像，稍后刷新查看」；409 时显示接口返回的 detail。
  - 详情抽屉显示「头像：<状态中文>」，有 `avatar_note` 时附在后面。状态中文：
    - `pending` 待处理、`uploaded` 已上传、`present` 本来就有；
    - `not_found` Gfriends 里找不到、`no_person` Jellyfin 里没有这个人物、`error` 失败。
  - 详情抽屉加按钮「重新找头像」，点后调用 `refreshActressAvatars({ actress_ids: [id] })`。

- [ ] **Step 1: 写失败测试**：
  - 点「补头像」后以空请求体调用接口，并出现成功提示；
  - 详情里显示「头像：Gfriends 里找不到」；
  - 点「重新找头像」后以 `{ actress_ids: [当前 id] }` 调用接口。
- [ ] **Step 2: 跑测试确认失败**：`scripts/remote-test.sh frontend`（看 test 部分）。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 跑测试确认通过**：test、build、lint 退出码都是 0。
- [ ] **Step 5: 记下提交说明（先不提交）**：`feat: 女优页补头像按钮与头像状态显示`

---

### Task 7: 挂载对照表、文档与全量测试

**Files:**
- Modify: `docker/docker-compose.yml`：`app.volumes` 加一行 `/mnt/user/docker1/mdc_ng/data/mapping_actor.xml:/app/mdc/mapping_actor.xml:ro`，上面配中文注释说明它是 MDC 的演员对照表、只读。
- Modify: `docs/actresses.md`：
  - 新增「头像」一节：来源、匹配规则、状态含义、开关和上限、手动接口、不回查、上线步骤；
  - 配置表加三项，生产示例 `ACTRESS_AVATAR_NAME_MAP=/app/mdc/mapping_actor.xml`。
- Modify: `docs/superpowers/specs/2026-11-26-actress-avatars-design.md`：把状态行改为「已实施（待上线）」。
- Create: `progress/2026-11-26-actress-avatars.md`。

- [ ] **Step 1: 改 compose 和文档。**
- [ ] **Step 2: 跑全量测试，依次各跑一次**：
  - `scripts/remote-test.sh backend` 预期退出码 0；
  - `scripts/remote-test.sh frontend` 预期 test、build、lint 退出码都是 0。
- [ ] **Step 3: 写 progress 日志**：What was done / Testing / Notes（含 Changed files 和 Rollback；Rollback 要写先把迁移降到 `20261126_0019`）。
- [ ] **Step 4: 问用户是否提交**：提交范围是本功能全部文件，说明汇总各任务记下的提交说明。

**上线（不在本计划内，每步由用户批准）**：先部署（带迁移，开关关），再用手动接口对 1 个人验证 Jellyfin 上传接口格式，然后试 3 个人，最后打开 `ACTRESS_AVATARS_ENABLED`。
