# 整站 UI 重设计与下载器双流重做 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 18x 前端换成中性冷灰 + 蓝色主色的统一设计系统，并把下载器页重做成「候选收件箱 + 任务看板」双流模型，后端补齐时间、容量、忽略和筛选能力。

**Architecture:** 先落地设计令牌、格式化工具和外壳（阶段 A）。再做下载器后端：迁移、同步、查询、路由（B1–B4）。然后把下载器前端拆到 `frontend/src/pages/downloader/` 目录，分成收件箱、任务看板、检查抽屉三块（B5–B9）。最后按导航分组迁移其余页面（C1–C3），并做整体验收（D1）。后端沿用 FastAPI + SQLAlchemy + Alembic 的现有写法，前端沿用 React 19 + antd 6。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2 / Alembic / pytest；React 19 / antd 6 / Vite / vitest + Testing Library。

**Spec:** `docs/superpowers/specs/2026-10-31-ui-redesign-downloader-design.md`（2026-11-01 修订版）

## Global Constraints

- 注释、文档、提交说明一律用中文。
- **不提交、不切分支、不推送、不部署**：用户没有要求做任何 Git 操作。每个任务结束时停在「检查点」：列出改动文件和测试结果，等用户授权后再提交。只能逐个添加本任务改动的文件，禁止 `git add -A` 或 `git add .`。
- **B1 数据库迁移开始前必须单独请用户确认**：说明新增哪些字段、只增不删、downgrade 可回滚、只在本地 SQLite 执行。
- 浅色令牌：`--app-bg #f8fafc`，`--app-surface #ffffff`，`--app-surface-elevated #ffffff`，`--app-bg-muted #f1f5f9`，`--app-border rgba(15, 23, 42, 0.08)`，`--app-border-strong rgba(15, 23, 42, 0.16)`，`--app-text #0f172a`，`--app-text-muted #64748b`，`--app-brand #0284c7`，`--app-brand-subtle #e0f2fe`，`--app-success #16a34a / #f0fdf4`，`--app-warning #d97706 / #fffbeb`，`--app-danger #dc2626 / #fef2f2`。
- 深色令牌：`--app-bg #0b0f17`，`--app-surface #111827`，`--app-surface-elevated #1f2937`，`--app-bg-muted #1e293b`，`--app-border rgba(255, 255, 255, 0.08)`，`--app-border-strong rgba(255, 255, 255, 0.16)`，`--app-text #f8fafc`，`--app-text-muted #94a3b8`，`--app-brand #38bdf8`，`--app-brand-subtle rgba(56, 189, 248, 0.12)`。深色语义色取 Tailwind 400 档：`#4ade80`、`#fbbf24`、`#f87171`，浅底为对应色 12% 透明度。
- 卡片投影：`0 1px 3px 0 rgba(0, 0, 0, 0.03), 0 0 0 1px var(--app-border)`。浮层投影：`0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.08)`。
- 圆角：按钮和输入框 6px，卡片和表格 8px，浮动条 12px，徽章 999px。状态徽章 `padding: 2px 8px`。
- 动效：150–200ms，缓动 `cubic-bezier(0.16, 1, 0.3, 1)`；`prefers-reduced-motion: reduce` 时关闭。
- 字体栈：`-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Noto Sans SC', 'Segoe UI', sans-serif`。数字、时间、容量列使用 `font-variant-numeric: tabular-nums`。
- 界面里不用 emoji 当图标，一律用 `@ant-design/icons`。
- 主题键名保持 `comfort` / `graphite`，存储键保持 `18x-theme-mode`；对外文案为「浅色 / 深色」。
- 时间一律按 Asia/Shanghai 显示；后端返回 ISO 字符串，RN 的 Unix 秒在后端转换。
- 不改 RN 下载器项目本身；不做自动下载；其余页面不改业务逻辑和接口契约。
- 命令：后端 `.venv/bin/python -m pytest tests/ -q`；前端在 `frontend/` 目录下运行 `npm run test`、`npm run build`、`npm run lint`。

## 与规范的偏差（需用户知悉）

1. **单文件重试做不了**：RN 的 `POST /api/tasks/{id}/retry` 只能按任务重试，且本来就只重试失败文件（`download_failed` 模式），没有单文件重试接口；规范又不允许改 RN。因此抽屉里的失败文件卡片不放「单项重试」按钮，只在卡片区顶部放一个「重试全部失败文件」。`only_failed` 参数照收，但对 RN 没有影响，在接口文档里说明。
2. **「有更新 +N」需要新字段**：18x 没有记录「上次完成时的媒体数」。B1 给 `downloader_packages` 增加 `completed_media_count`，B2 在同步到 `current_download_status == 'completed'` 时写入当时的 `media_count`。在这之前已完成的包算不出 N，只显示「有更新」。
3. **提交不再依赖「已选择」状态**：新页面的勾选只是前端状态，所以 `submit_selected` 要放宽，同时接受 `pending` 候选。`/select` 接口保留，以兼容旧调用。
4. **顺带修一个已有缺陷**：文件历史目前把 RN 的格式化字符串 `total_size`（如 `"12.3 MB"`）当整数解析，结果总是 0。B2 改为读取 `total_size_bytes` / `downloaded_size_bytes` / `download_speed_bytes`。

## Review Focus

1. **忽略后 5 秒内关闭或刷新页面**：用户预期忽略照样生效。B7 在组件卸载和 `pagehide` 时立即提交所有待提交的忽略。
2. **RN 旧任务缺少 `created_at` / 文件字节数**：列表照常显示（显示 `-`），时间筛选不报错；这类任务只在「全部时间」下出现。B4 有测试覆盖。
3. **同一资源包被多个白名单词命中，生成了多条候选**：收件箱只显示一行（按资源包合并，命中词显示为多个胶囊）；忽略和下载都按资源包生效。B3、B7 有测试覆盖。
4. **当前页全部被提交或忽略后列表变空**：自动回到上一页或第 1 页，不能停在一个空页上。B7 有测试覆盖。
5. **RN 不可达时点击「同步」或「确认下载」**：给出中文错误提示；勾选状态和列表都保留，不清空。B7 有测试覆盖。

## 文件结构

后端：
- Modify `app/models/downloader.py`：新增字段。
- Create `alembic/versions/20261101_0015_downloader_ui_fields.py`：迁移与回填。
- Modify `app/services/downloader/sync_service.py`：同步写字段、忽略跳过、提交放宽。
- Create `app/services/downloader/query_service.py`：所有读接口的查询，包括收件箱、任务筛选、详情、汇总，以及忽略/恢复。拆出来是为了不让 `sync_service.py` 继续膨胀。
- Modify `app/schemas/downloader.py`、`app/api/routes/downloader.py`。
- Tests：`tests/downloader/test_migration_ui_fields.py`、`tests/downloader/test_query_service.py`；修改 `tests/downloader/test_sync_service.py`、`tests/api/test_downloader_routes.py`。

前端：
- Modify `frontend/src/theme/{types,palettes,antdTheme}.ts`、`frontend/src/index.css`。
- Modify `frontend/src/utils/format.ts`；Create `frontend/src/utils/statusText.ts`。
- Create `frontend/src/components/{StatusTag,BytesText,TimeText,EmptyState}.tsx`。
- Modify `frontend/src/layout/{AppShell,navigation,PageScaffold,DataToolbar,MetricStrip}.tsx`。
- Modify `frontend/src/api/downloader.ts`。
- Replace `frontend/src/pages/DownloaderPage.tsx` with a thin entry; Create `frontend/src/pages/downloader/{DownloaderHeader,CandidatesInbox,FloatingActionBar,useUndoableIgnore,TasksBoard,TaskInspector}.tsx`。
- 其余 `frontend/src/pages/*.tsx` 只换皮。

---

### Task A1: 设计令牌与 antd 主题

**Files:**
- Modify: `frontend/src/theme/types.ts`、`frontend/src/theme/palettes.ts`、`frontend/src/theme/antdTheme.ts`、`frontend/src/index.css:1-45`（`:root` 和 `[data-theme='graphite']` 两块变量）
- Test: `frontend/src/theme/antdTheme.test.ts`

**Interfaces:**
- Produces: `ThemePalette`。去掉 `sidebarBg/sidebarText/sidebarMuted/headerBg`；新增 `surfaceElevated, borderStrong, brandSubtle, success, successBg, warning, warningBg, danger, dangerBg`。CSS 变量名以 Global Constraints 为准，另加 `--app-success-bg`、`--app-warning-bg`、`--app-danger-bg`、`--shadow-card`、`--shadow-float`、`--ease-out`。
- 移除 `BRAND_PURPLE`。

- [ ] **Step 1: 改写测试** `antdTheme.test.ts`：
  - `buildAntdTheme('comfort').token.colorPrimary === '#0284c7'`
  - `buildAntdTheme('graphite').token.colorPrimary === '#38bdf8'`
  - `token.borderRadius === 6`
  - `components.Card.borderRadiusLG === 8`
  - 对两个模式序列化后的主题对象执行 `JSON.stringify(...)`，结果不含 `8b5cf6` 和 `139, 92, 246`。
- [ ] **Step 2:** 运行 `npm run test -- antdTheme`。预期：FAIL（主色仍为紫色）。
- [ ] **Step 3:** 按令牌改写 `palettes.ts` 和 `antdTheme.ts`。
  - `Menu` 改用浅色主题令牌：`itemSelectedBg = brandSubtle`，`itemSelectedColor = brand`。
  - `Table.rowHoverBg` 用 `bgMuted`。
  - `boxShadow` 用卡片投影。
  - `index.css` 变量块同步改写，`body` 字体栈替换。
- [ ] **Step 4:** 运行 `npm run test -- theme`。预期：PASS（包括原有的 storage、Provider 测试）。
- [ ] **Step 5: 检查点**：列出改动文件和测试结果，不提交。

### Task A2: 格式化工具、状态映射与基础组件

**Files:**
- Modify: `frontend/src/utils/format.ts`
- Create: `frontend/src/utils/statusText.ts`、`frontend/src/components/StatusTag.tsx`、`BytesText.tsx`、`TimeText.tsx`、`EmptyState.tsx`
- Test: `frontend/src/utils/format.test.ts`、`frontend/src/utils/statusText.test.ts`、`frontend/src/components/StatusTag.test.tsx`

**Interfaces:**
- Produces:
  - `formatBytes(bytes: number | null | undefined): string`
  - `formatShortDateTime(value: string | number | null | undefined, now?: Date): string`：数字视为 Unix 秒。
  - `formatRelative(value: string | number | null | undefined, now?: Date): string`
  - `formatDuration(seconds: number | null | undefined): string`
  - `type StatusDomain = 'package' | 'task' | 'file'`
  - `type StatusTone = 'neutral' | 'info' | 'active' | 'success' | 'warning' | 'danger'`
  - `statusMeta(domain: StatusDomain, value: string | null | undefined): { label: string; tone: StatusTone }`
  - `<StatusTag domain value suffix? tooltip? />`：`suffix` 用于「有更新 (+3)」。
  - `<BytesText value />`、`<TimeText value relative? />`：悬停显示完整时间。
  - `<EmptyState title description? action? />`

- [ ] **Step 1: 写测试**（`now` 固定为 `2026-11-01T12:00:00+08:00`）：
  - `formatBytes(12948331) === '12.3 MB'`
  - `formatBytes(0) === '-'`
  - `formatBytes(1536) === '1.5 KB'`
  - `formatBytes(2.5 * 1024 ** 4) === '2.5 TB'`
  - `formatShortDateTime('2026-10-28T06:05:00Z', now) === '10-28 14:05'`
  - `formatShortDateTime('2025-10-28T06:05:00Z', now) === '2025-10-28'`
  - `formatShortDateTime(null) === '-'`
  - `formatRelative(<now 减 180 秒>, now) === '3 分钟前'`
  - `formatRelative(<now 减 2 天>, now) === '2 天前'`
  - `formatDuration(4320) === '1 小时 12 分'`
  - `formatDuration(45) === '45 秒'`
  - `formatDuration(754) === '12 分 34 秒'`
  - `formatDuration(null) === '-'`
  - `statusMeta`：断言规范中的每一个映射，例如 `('package','outdated') → { label: '有更新', tone: 'warning' }`、`('package','failed') → '下载异常'`、`('task','completed_with_errors') → { label: '部分完成', tone: 'warning' }`、`('task','paused') → '已暂停'`。未知值返回 `{ label: 原文, tone: 'neutral' }`；空值返回 `{ label: '-', tone: 'neutral' }`。
  - `file` 域：`completed/downloaded → 已完成`，`failed/download_failed → 失败`，`downloading → 下载中`，`pending → 等待中`，`upload_failed → 上传失败`。
  - `StatusTag` 渲染 `('package','outdated', suffix '+3')` 时，文本为「有更新 (+3)」，并带 `status-tag--warning` 类名。
- [ ] **Step 2:** 运行 `npm run test -- format statusText StatusTag`。预期：FAIL。
- [ ] **Step 3:** 实现。
  - `formatShortDateTime` 复用现有 `normalizeDateTimeInput` 和上海时区。
  - 「今年」以上海时区的年份判断。
  - `.status-tag` 及各 tone 的样式写进 `index.css`，按 Global Constraints 的徽章规则。
- [ ] **Step 4:** 重跑。预期：PASS。
- [ ] **Step 5: 检查点。**

### Task A3: 外壳与通用骨架

**Files:**
- Modify: `frontend/src/layout/AppShell.tsx`、`navigation.tsx`、`PageScaffold.tsx`、`DataToolbar.tsx`、`MetricStrip.tsx`、`frontend/src/index.css`（外壳相关样式）
- Test: `frontend/src/layout/AppShell.test.tsx`、`navigation.test.tsx`、`PageScaffold.test.tsx`

**Interfaces:**
- Produces:
  - `NAV_GROUPS[].label` 为 `数据 / 流程 / 系统`；`/downloader` 的 label 改为 `下载器`。
  - `getNavTrail(pathname: string): { group: string; page: string } | null`
  - `DataToolbar` 新签名 `{ left?: ReactNode; right?: ReactNode; children?: ReactNode }`；`children` 保留，兼容旧用法。
  - `MetricStrip` 改为紧凑行内文字样式，不再用 `Statistic` 大数字。
  - `PageScaffold` 签名不变。

- [ ] **Step 1: 改写测试。**
  - `AppShell`：
    - 有文字「18x 整理台」和「流程」
    - 没有「Admin workspace」
    - 面包屑在 `/dedupe` 路由下显示「流程 / 文件去重」
    - 用户菜单按钮可访问名称为「wang」，没有 `.app-user-chip`
    - 点击菜单后点击「深色」，`data-theme` 变为 `graphite`
    - 点击「退出登录」会调用 `onLogout`
  - `navigation`：`getNavTrail('/downloader')` 返回 `{ group: '流程', page: '下载器' }`。
- [ ] **Step 2:** 运行 `npm run test -- layout`。预期：FAIL。
- [ ] **Step 3:** 实现。
  - 侧栏用浅色 `Menu`（不再用 `theme="dark"`），选中项左侧 2px 高亮条。
  - 用户菜单用 antd `Dropdown`，菜单项为「外观：浅色 / 深色」和「退出登录」。
  - 删除 `.app-user-chip`、`.app-eyebrow`、`.app-brand-mark` 的样式和 JSX。
- [ ] **Step 4:** 依次运行 `npm run test`（全部前端测试）和 `npm run build`。预期：PASS。旧的 `DownloaderPage.test` 断言标题「下载器资源包」，这里会失败，属于预期，在 B6 修复，检查点里写明。
- [ ] **Step 5: 检查点。**

### Task B1: 数据库字段与迁移（开始前请用户确认）

**Files:**
- Modify: `app/models/downloader.py`
- Create: `alembic/versions/20261101_0015_downloader_ui_fields.py`（`revision = "20261101_0015"`，`down_revision = "20261031_0014"`）
- Test: `tests/downloader/test_migration_ui_fields.py`；`tests/test_migrations.py` 继续通过

**Interfaces:**
- Produces:
  - `DownloaderPackage` 新增：`ignored_at: datetime | None`、`ignored_reason: str | None`、`completed_media_count: int | None`。
  - `DownloaderTaskSnapshot` 新增：`remote_created_at`、`remote_updated_at`、`finished_at`（均为带时区的 `datetime | None`）、`total_bytes: int`（BigInteger，默认 0）、`downloaded_bytes: int`（同上）、`channel_title: str | None`。
  - 索引：`ix_downloader_tasks_node_created (node_key, remote_created_at)`、`ix_downloader_tasks_node_status (node_key, status)`。
  - 纯函数 `backfill_task_fields(raw_payload_json: str) -> dict`，放在迁移文件里，测试直接导入。从 `created_at` / `updated_at`（Unix 秒）、`files[].total_size_bytes` / `downloaded_size_bytes` 中提取；`status` 为终态时，`finished_at = updated_at`。

- [ ] **Step 0: 请用户确认迁移**（按 Global Constraints 的说明内容）。
- [ ] **Step 1: 写测试。**
  - `backfill_task_fields` 对正常载荷，返回正确的上海时间对应 UTC 和字节求和。
  - 对 `"{}"`、`"not json"`、`files` 不是列表、字节为字符串 `"12.3 MB"` 的情况，返回空值或 0，不抛异常。
  - 升级到 head 后再降级到 `20261031_0014` 可执行，`downloader_task_snapshots` 不再有 `total_bytes` 列。
- [ ] **Step 2:** 运行 `.venv/bin/python -m pytest tests/downloader/test_migration_ui_fields.py tests/test_migrations.py -q`。预期：FAIL。
- [ ] **Step 3:** 实现模型和迁移。
  - 新增列用 `op.add_column`；SQLite 下用 `batch_alter_table`，沿用 0014 的写法。
  - upgrade 末尾逐行读取快照的 `raw_payload_json`，调用 `backfill_task_fields` 后更新。
- [ ] **Step 4:** 重跑。预期：PASS。
- [ ] **Step 5: 检查点**，注明回滚命令为 `alembic downgrade 20261031_0014`。

### Task B2: 同步写入新字段与忽略跳过

**Files:**
- Modify: `app/services/downloader/sync_service.py`
- Test: `tests/downloader/test_sync_service.py`

**Interfaces:**
- Consumes: B1 的字段，以及迁移文件里的 `backfill_task_fields`。把它挪到 `sync_service.py` 作为 `_task_structured_fields(payload: dict) -> dict`，迁移文件里保留一份独立副本，因为迁移不应导入应用代码。
- Produces: 同步行为如下。
  - `sync_tasks` 写入 6 个新字段。`finished_at` 只在首次进入终态（`completed`、`completed_with_errors`、`failed`、`cancelled`）时写入，之后不覆盖；离开终态（例如被重试）时清空。
  - `channel_title` 的取值顺序：提交记录关联资源包的 `channel_title` → 载荷里的 `chat_title` → `None`。
  - `sync_packages` 遇到 `ignored_at` 不为空的包：不生成新候选；该包已有的 `pending` / `selected` 候选改为 `dismissed`，`dismissed_reason='ignored'`。
  - `current_download_status == 'completed'` 时，`completed_media_count = media_count`。
  - `_record_task_history` 的文件字节改读 `*_bytes` 字段。
  - `submit_selected` 同时接受 `pending`、`selected` 状态的候选。

- [ ] **Step 1: 写测试**（`test_sync_service.py` 新增）：
  - `test_sync_tasks_records_times_bytes_and_finished_once`：载荷 `created_at=1761890000.0, updated_at=1761890600.0, status='completed', files=[{total_size_bytes:100, downloaded_size_bytes:100}, {total_size_bytes:50, downloaded_size_bytes:20}]`。断言 `total_bytes==150`、`downloaded_bytes==120`、`finished_at` 等于 `updated_at` 对应的时间；第二次同步时把 `updated_at` 改成更晚，`finished_at` 不变。
  - `test_sync_tasks_clears_finished_when_task_restarts`
  - `test_ignored_package_creates_no_candidate_and_dismisses_pending`
  - `test_completed_package_records_completed_media_count`
  - `test_file_history_reads_byte_fields`：`total_size_bytes: 12948331` 落库为 12948331。
  - `test_submit_accepts_pending_candidate`
- [ ] **Step 2:** 运行 `.venv/bin/python -m pytest tests/downloader/test_sync_service.py -q`。预期：新测试 FAIL。
- [ ] **Step 3:** 实现。
- [ ] **Step 4:** 运行 `.venv/bin/python -m pytest tests/downloader -q`。预期：PASS。
- [ ] **Step 5: 检查点。**

### Task B3: 收件箱查询与忽略/恢复服务

**Files:**
- Create: `app/services/downloader/query_service.py`
- Test: `tests/downloader/test_query_service.py`

**Interfaces:**
- Produces（`class DownloaderQueryService`，全部为 `@staticmethod`）：
  - `list_inbox(db, *, view: Literal['candidates','ignored'], download_status: str | None, keyword_entry_id: int | None, search: str | None, sort: Literal['published_at','size','media_count'] = 'published_at', page: int = 1, page_size: int = 50) -> tuple[list[dict], int, dict[str, int]]`
    - **按资源包聚合**：每个包一行。`candidates` 视图的条件是「包未忽略，且至少有一条当前版本的 `pending` / `selected` 候选」；`ignored` 视图的条件是 `ignored_at` 不为空。
    - `download_status` 的取值：`never`、`outdated`、`failed`（`failed` 同时匹配 `cancelled`）。
    - 排序一律倒序。
    - 每行字段：`package_id, remote_package_id, title, channel_title, published_at, media_count, known_total_size, current_download_status, index_revision, completed_revision, new_media_count, candidate_ids: list[int], keywords: list[{keyword_entry_id, keyword, matched_term}], ignored_at, ignored_reason`。
    - `new_media_count = media_count - completed_media_count`；只在状态为 `outdated` 且两者都有值、差值 > 0 时给出，否则为 `None`。
    - 第三个返回值是 `{'candidates': n, 'ignored': m}`，用于分段控制器上的数字。
  - `ignore_packages(db, *, candidate_ids: list[int] | None = None, package_ids: list[int] | None = None, reason: str | None = None) -> int`：返回实际新忽略的包数。重复调用幂等。
  - `unignore_packages(db, package_ids: list[int]) -> int`：清除忽略后，对每个包重新匹配一次白名单。

- [ ] **Step 1: 写测试。**
  - 同一包命中两个白名单词时，`list_inbox` 只返回 1 行，`keywords` 长度为 2、`candidate_ids` 长度为 2。
  - `ignore_packages(candidate_ids=[其中一个])` 后，该包从 `candidates` 视图消失、出现在 `ignored` 视图，计数变为 `{'candidates':0,'ignored':1}`；重复调用返回 0。
  - `unignore_packages` 后包重新出现在 `candidates` 视图（候选恢复为 `pending`）。
  - `outdated` 包在 `media_count=20, completed_media_count=18` 时 `new_media_count==2`；`completed_media_count=None` 时为 `None`。
  - `search` 匹配标题；`download_status='failed'` 同时匹配 `cancelled`；`sort='size'` 按大小倒序。
- [ ] **Step 2:** 运行 `.venv/bin/python -m pytest tests/downloader/test_query_service.py -q`。预期：FAIL。
- [ ] **Step 3:** 实现。
  - 「重新匹配」要从 `sync_packages` 的循环体里抽出 `_match_package(db, package, whitelist_terms, blacklist_terms) -> tuple[int, int]`（返回新建数、作废数），供同步和恢复共用，避免复制逻辑。
  - 白名单和黑名单的加载也抽成 `_load_terms(db)`。
- [ ] **Step 4:** 运行 `.venv/bin/python -m pytest tests/downloader -q`。预期：PASS。
- [ ] **Step 5: 检查点。**

### Task B4: 任务筛选、详情、汇总与路由

**Files:**
- Modify: `app/services/downloader/query_service.py`、`app/schemas/downloader.py`、`app/api/routes/downloader.py`
- Test: `tests/downloader/test_query_service.py`、`tests/api/test_downloader_routes.py`

**Interfaces:**
- Produces（服务层）：
  - `list_tasks(db, *, node_key, status: list[str] | None, since: datetime | None, until: datetime | None, channel: str | None, keyword_entry_id: int | None, search: str | None, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]`
    - 状态分组展开：`active` 展开为 `pending, queued, running, downloading, paused`。
    - 时间按 `remote_created_at` 过滤；该字段为空的任务只在 `since` 和 `until` 都为空时出现。
    - 排序：`remote_created_at` 倒序，空值排最后，再按 `id` 倒序。
    - `keyword_entry_id` 的关联路径：提交记录 → 候选。
    - 每行字段：旧字段 + `remote_created_at, finished_at, total_bytes, downloaded_bytes, channel_title, duration_seconds, download_speed_bytes, package_id, package_title`。
    - `duration_seconds`：有 `finished_at` 时用 `finished_at − remote_created_at`；进行中的任务用当前时间减开始时间。
    - `download_speed_bytes` 取当前文件的 `download_speed_bytes`。
  - `task_detail(db, task_id, *, node_key) -> dict | None`：返回 `{ task: <同上行>, failed_files: [...], files: [...], history: [...] }`。
    - 文件来自最新一条历史快照，字段为 `message_id, filename, status, total_size, downloaded_size, error`。
    - `failed_files` 是 `status` 属于 `failed / download_failed / upload_failed` 的子集。
    - `history` 复用现有的 `list_task_history`，最多 50 条。
  - `summary(db, *, node_key, now: datetime) -> dict`：键为 `today_count, today_bytes, week_count, week_bytes, active_count, week_failed_files`。「今天」按上海时区零点计算；字节按 `downloaded_bytes` 求和；只统计 `finished_at` 落在区间内、状态为 `completed` 或 `completed_with_errors` 的任务。
- Produces（路由，旧参数保持兼容）：
  - `GET /downloader/packages`：新增 `view`。传了 `view` 时走 `list_inbox`，响应 `{items,total,page,page_size,counts}`；不传时走旧的 `list_candidates`。
  - `POST /downloader/packages/ignore`：请求体 `{candidate_ids?: int[], package_ids?: int[], reason?: str}`，两者至少给一个，否则返回 422。响应 `{ignored: n}`。
  - `POST /downloader/packages/unignore`：请求体 `{package_ids: int[]}`，响应 `{restored: n}`。
  - `GET /downloader/tasks`：新增 `status`（逗号分隔）、`since`、`until`（ISO 字符串）、`channel`、`keyword_entry_id`、`search`、`page`、`page_size`。保留 `limit`：只给了 `limit` 时按旧行为返回前 `limit` 条。
  - `GET /downloader/tasks/{task_id}/detail`：找不到返回 404。
  - `POST /downloader/tasks/{task_id}/retry`：可选请求体 `{only_failed?: bool}`，忽略后照常调用 RN。
  - `GET /downloader/summary`。
  - `GET /downloader/channels`：返回已知频道名（快照和资源包的 `channel_title` 去重排序），供频道下拉使用。

- [ ] **Step 1: 写测试。**
  - 服务层：
    - `status=['active']` 只返回进行中的任务。
    - `since`、`until` 生效。
    - 没有 `remote_created_at` 的任务：给定 `since` 时不出现，不给时出现在最后。
    - `keyword_entry_id` 能通过提交记录过滤。
    - `task_detail.failed_files` 只含失败文件。
    - `summary` 对构造的数据给出精确数字，例如今天 2 个任务共 300 字节。
  - 路由：
    - `GET /downloader/packages?view=candidates` 返回含 `counts` 的响应。
    - `ignore` 请求体为空时返回 422。
    - `GET /downloader/tasks?limit=5` 保持旧行为。
    - `GET /downloader/tasks/missing/detail` 返回 404。
    - `GET /downloader/summary` 返回上述 6 个键。
- [ ] **Step 2:** 运行 `.venv/bin/python -m pytest tests/downloader/test_query_service.py tests/api/test_downloader_routes.py -q`。预期：FAIL。
- [ ] **Step 3:** 实现。schema 新增 `DownloaderIgnoreRequest`、`DownloaderUnignoreRequest`、`DownloaderRetryRequest`、`DownloaderInboxResponse`。
- [ ] **Step 4:** 运行 `.venv/bin/python -m pytest tests/ -q`（后端全量）。预期：PASS。与本计划无关的既有失败要逐条记录。
- [ ] **Step 5: 检查点。**

### Task B5: 前端下载器 API 层

**Files:**
- Modify: `frontend/src/api/downloader.ts`
- Test: `frontend/src/api/downloader.test.ts`

**Interfaces:**
- Produces:
  - 类型：`InboxItem`、`InboxResponse`（含 `counts`）、`TaskRow`、`TaskDetail`、`DownloaderSummary`、`TaskFilters = { status?: string[]; since?: string; until?: string; channel?: string; keywordEntryId?: number; search?: string; page?: number; pageSize?: number }`。
  - 函数：`listInbox(params)`、`ignorePackages({candidateIds?, packageIds?, reason?})`、`unignorePackages(packageIds)`、`listTasks(filters: TaskFilters)`、`getTaskDetail(taskId)`、`getDownloaderSummary()`、`listDownloaderChannels()`、`retryDownloaderTask(taskId, { onlyFailed?: boolean })`。
  - 保留：`getDownloaderStatus`、`syncDownloaderPackages`、`syncDownloaderTasks`、`submitDownloaderBatches`、`controlDownloader`、`cancelDownloaderTask`。
  - 删除新页面不再使用的 `listDownloaderCandidates`、`selectDownloaderCandidate`、`listDownloaderTaskHistory`（全仓 grep 确认没有其他引用后再删）。

- [ ] **Step 1: 写测试**（mock `@/api/client`）：
  - `listTasks({status:['active','failed'], since:'2026-10-25T00:00:00+08:00', page:2})` 调用的 URL 含 `status=active%2Cfailed`、`since=...`、`page=2`、`page_size=20`。
  - `ignorePackages({candidateIds:[1,2]})` 发出 `POST /downloader/packages/ignore`，请求体为 `{candidate_ids:[1,2]}`。
- [ ] **Step 2–4:** 运行 `npm run test -- api/downloader`，先 FAIL，实现后 PASS。
- [ ] **Step 5: 检查点。**

### Task B6: 下载器页骨架与页头

**Files:**
- Modify: `frontend/src/pages/DownloaderPage.tsx`（改为薄入口）
- Create: `frontend/src/pages/downloader/DownloaderHeader.tsx`
- Test: `frontend/src/pages/DownloaderPage.test.tsx`

**Interfaces:**
- Consumes: B5 的 API；A2、A3 的组件。
- Produces:
  - `DownloaderPage` 用 `useSearchParams` 读写 `view`（`inbox | tasks`，非法值按 `inbox` 处理）。
  - 页面标题为「下载器」。
  - 两个视图用 `Segmented` 切换，选项文案为 `候选收件箱 (n 待确认)` 和 `任务看板与历史 (n 活跃)`，n 来自收件箱的 `counts.candidates` 和汇总的 `active_count`。
  - `DownloaderHeader` props：`{ status: DownloaderStatus | null; onSynced: () => void }`。显示连通状态点（绿/红，带文字）、上次同步的相对时间、「暂停全部」「恢复全部」「同步资源包」（主按钮）。同步时依次调用 `syncDownloaderPackages` 和 `syncDownloaderTasks`。

- [ ] **Step 1: 改写测试。**
  - 页面标题为「下载器」。
  - 未启用时显示「RN 下载器未启用」。
  - 默认显示收件箱；点击「任务看板与历史」后 URL 包含 `view=tasks`。
  - 以 `MemoryRouter initialEntries={['/downloader?view=tasks']}` 打开时，直接显示任务看板。
- [ ] **Step 2–4:** 运行 `npm run test -- DownloaderPage`，先 FAIL，实现后 PASS（两个视图先放占位组件，B7、B8 再替换）。
- [ ] **Step 5: 检查点。**

### Task B7: 候选收件箱

**Files:**
- Create: `frontend/src/pages/downloader/CandidatesInbox.tsx`、`FloatingActionBar.tsx`、`useUndoableIgnore.ts`
- Test: `frontend/src/pages/downloader/CandidatesInbox.test.tsx`、`useUndoableIgnore.test.ts`

**Interfaces:**
- Produces:
  - `CandidatesInbox` props：`{ onCountsChange: (counts) => void }`。
  - `useUndoableIgnore({ commit: (packageIds: number[]) => Promise<void>, delayMs = 5000 })`，返回 `{ schedule(items: {packageId:number,title:string}[]): void; undo(): void; pendingIds: Set<number>; flush(): Promise<void> }`。
    - `schedule` 之后，这些行立即从列表中隐藏（乐观更新）。
    - 5 秒后调用 `commit`。
    - 期间又有新的 `schedule` 时，先立即提交上一批，再开始新的计时。
    - `undo` 取消计时并恢复显示。
    - 组件卸载和 `pagehide` 时调用 `flush`。
    - `commit` 失败时恢复显示，并用 `message.error` 提示。
  - Toast 文案：`已忽略《{第一个标题}》等 {n} 个资源包`，只有 1 个时为 `已忽略《{标题}》`；按钮为「撤销」，按钮旁显示剩余秒数。用 antd `notification`，位置 `bottomRight`。

- [ ] **Step 1: 写测试。**
  - `useUndoableIgnore`（假定时器）：
    - `schedule` 后 4999ms 时 `commit` 未调用，5000ms 时调用一次。
    - `undo` 后不调用。
    - 连续两次 `schedule` 时，第一批立即提交。
    - 卸载时立即提交。
    - `commit` 抛错时，`pendingIds` 被清空（行恢复显示）。
  - `CandidatesInbox`（mock API）：
    - 列表显示复合单元格：标题、`#远端ID`、命中词胶囊、`2.4 GB · 18 媒体`、「3 天前」；`outdated` 且 `new_media_count=3` 的行显示「有更新 (+3)」。
    - 勾选 2 行后浮动条显示「已选 2 项 (共 …)」和「确认下载 2 个」；按 Enter 提交，`submitDownloaderBatches` 收到这两行的全部 `candidate_ids`（多命中词时会展开）。
    - 按 Shift 点击，选中两行之间的所有行。
    - 按「/」键聚焦搜索框。
    - 分段切到「已忽略」，每行显示「恢复」，点击后调用 `unignorePackages`。
    - 【Review Focus 4】当前页最后一行被提交后，自动请求 `page-1`。
    - 【Review Focus 5】`submitDownloaderBatches` 被拒绝时，显示错误，并且勾选保留。
- [ ] **Step 2:** 运行 `npm run test -- downloader/`。预期：FAIL。
- [ ] **Step 3:** 实现。
  - 表格只有 5 列：选择、资源包与来源、体量与发布、版本与状态、操作。
  - 操作列默认 `opacity: 0`，在行 `:hover` 或 `:focus-within` 时显示。键盘可达，不能只靠悬停。
  - 浮动条按 Global Constraints 的样式，并加上 `backdrop-filter: blur(16px)`。浅色背景 `rgba(255,255,255,0.85)`，深色背景 `rgba(31,41,55,0.85)`。
  - 「版本与状态」列悬停提示 `本地已完成 r{completed_revision}，远端新版 r{index_revision}`。
  - 提交成功后，被提交的行先淡出（200ms，`prefers-reduced-motion` 时直接移除）再从列表中移除；浮动条收起；右下角用 `notification.success` 提示「已提交 n 个下载批次」，跳过数不为 0 时追加「，跳过 m 个」。
- [ ] **Step 4:** 重跑。预期：PASS。
- [ ] **Step 5: 检查点。**

### Task B8: 任务看板与历史

**Files:**
- Create: `frontend/src/pages/downloader/TasksBoard.tsx`
- Test: `frontend/src/pages/downloader/TasksBoard.test.tsx`

**Interfaces:**
- Consumes: B5 的 `listTasks`、`getDownloaderSummary`、`listDownloaderChannels`、`cancelDownloaderTask`、`retryDownloaderTask`。
- Produces:
  - `TasksBoard` props：`{ onActiveCountChange: (n: number) => void; onOpenTask: (taskId: string) => void }`。
  - 页面结构：
    - 活跃任务摘要条：状态属于 `active` 的任务，每行显示名称、速率（`formatBytes(speed) + '/s'`）、进度条、活跃文件数。
    - 统计条：今日、近 7 天、进行中、近 7 天失败文件。
    - 筛选栏：状态 `Segmented`（全部 / 活跃中 / 已完成 / 部分完成 / 失败 / 已取消）、时间 `Select`（今天 / 近 7 天 / 近 30 天 / 自定义，选自定义时出现 `DatePicker.RangePicker`）、频道下拉、关键词下拉（数据来自现有关键词接口，只列白名单）、标题搜索。
    - 主表格。
  - 筛选条件写入 URL 参数：`status`、`range`、`channel`、`kw`、`q`、`page`。
  - 有活跃任务时，每 5 秒刷新列表和汇总；切走视图或页面隐藏（`document.visibilityState === 'hidden'`）时停止刷新。

- [ ] **Step 1: 写测试。**
  - 选「失败」状态 + 「近 7 天」时，`listTasks` 收到 `status:['failed']` 和 7 天前上海零点的 `since`。
  - 行内显示「部分完成」、`7.8 GB / 8.2 GB`、耗时「12 分 34 秒」。
  - 点击行时调用 `onOpenTask('task-1')`；点击「取消」按钮时不触发 `onOpenTask`（阻止冒泡）。
  - 【Review Focus 2】`remote_created_at` 为空的行显示 `-`，不崩溃。
- [ ] **Step 2–4:** 运行 `npm run test -- TasksBoard`，先 FAIL，实现后 PASS。
- [ ] **Step 5: 检查点。**

### Task B9: 侧边检查抽屉

**Files:**
- Create: `frontend/src/pages/downloader/TaskInspector.tsx`
- Modify: `frontend/src/pages/DownloaderPage.tsx`（挂载抽屉，URL 参数 `task` 记录当前打开的任务，便于刷新后恢复）
- Test: `frontend/src/pages/downloader/TaskInspector.test.tsx`

**Interfaces:**
- Consumes: `getTaskDetail`、`retryDownloaderTask(taskId, {onlyFailed:true})`。
- Produces: `TaskInspector` props：`{ taskId: string | null; onClose: () => void; onChanged: () => void }`。用 antd `Drawer`，宽 560，`keyboard` 开启（按 Esc 关闭），点击遮罩关闭。
  - 顶部：状态、耗时、`已下 / 总量`、关联资源包标题和频道、「重试全部失败文件」主按钮（只有失败文件时显示）。
  - 失败聚焦区：有失败文件时置顶显示警告卡片，每个文件显示文件名、大小、错误原因。不放单项重试按钮（见「与规范的偏差」第 1 条）。
  - 文件清单：文件名过滤输入框，状态 `Segmented`（全部 / 仅失败 / 仅成功）；用 antd `Table` 的 `virtual` 加 `scroll.y`，处理长列表。
  - 变更历史：用 `Collapse` 折叠，默认收起。

- [ ] **Step 1: 写测试。**
  - `taskId='task-1'` 时请求详情，并渲染失败卡片「003.jpg」和「Connection reset by peer」。
  - 点击「重试全部失败文件」，调用 `retryDownloaderTask('task-1', {onlyFailed:true})`，随后调用 `onChanged`。
  - 按 Esc 调用 `onClose`。
  - 选「仅失败」时只剩失败行；在过滤框输入「001」时只剩匹配行。
  - 没有失败文件时不渲染失败卡片和重试按钮。
- [ ] **Step 2–4:** 运行 `npm run test -- TaskInspector DownloaderPage`，先 FAIL，实现后 PASS。
- [ ] **Step 5:** 运行 `npm run test`、`npm run build`、`npm run lint` 全部通过。然后本地启动前后端，在浏览器中分别以浅色和深色截图收件箱、浮动条、撤销 Toast、任务看板、抽屉，确认没有横向滚动。**检查点**附截图。

### Task C1: 数据组页面迁移

**Files:**
- Modify: `frontend/src/pages/{ImportsPage,NodesPage,KeywordExtractorPage,KeywordsPage,KeywordDuplicatesPage,HitsPage}.tsx`、`frontend/src/index.css`（只动这些页面专属的样式）
- Test: 现有测试，加上本组页面的冒烟渲染测试 `frontend/src/pages/dataGroup.smoke.test.tsx`（mock `@/api/client` 返回空列表，断言每个页面都能渲染出 `PageScaffold` 标题）

**换皮规则（C1–C3 通用）：**
1. 页面根节点用 `PageScaffold`。
2. 筛选和操作区改用 `DataToolbar left/right`。
3. 状态枚举的 `Tag` 换成 `StatusTag`；本组出现的新状态域在 `statusText.ts` 中新增，并给每个值补单元测试。
4. 字节换成 `BytesText` / `formatBytes`，时间换成 `TimeText` / `formatShortDateTime`。
5. 内联的颜色值换成 CSS 变量。
6. 不改任何 API 调用、状态逻辑和交互路径。如果某个改动需要碰业务代码，就停下来记录，不要改。

- [ ] **Step 1:** 写冒烟测试，运行 `npm run test -- dataGroup`，预期 PASS（这是防回归基线）。
- [ ] **Step 2:** 逐页按规则迁移；每改完一页运行 `npm run test` 和 `npm run build`。
- [ ] **Step 3:** 运行 `grep -nE "#[0-9a-fA-F]{6}|rgba?\(" frontend/src/pages/{本组文件}`。预期：无输出，或只剩有注释说明的例外。
- [ ] **Step 4:** 浏览器逐页检查浅色和深色。**检查点**。

### Task C2: 流程组页面迁移

**Files:**
- Modify: `frontend/src/pages/{OrganizeTasksPage,PlansPage,PlanDetailPage,ExecutorPage,WhitelistBatchPage,ReviewIntakePage,EmbyMediaActionsPage,FileDedupePage,MagnetTasksPage}.tsx`
- Test: 现有测试（含 `ReviewIntakePage.test.tsx`）+ `frontend/src/pages/workflowGroup.smoke.test.tsx`

- [ ] **Step 1–4:** 同 C1，按换皮规则执行。`FileDedupePage.tsx` 里写死的紫色要改用令牌。

### Task C3: 系统组、登录页与孤儿样式清理

**Files:**
- Modify: `frontend/src/pages/{AuthCenterPage,OpenAuthPage,QrLoginPage,SettingsPage,LoginPage}.tsx`、`frontend/src/index.css`
- Test: `frontend/src/pages/systemGroup.smoke.test.tsx`

- [ ] **Step 1–2:** 同 C1，按换皮规则执行。登录页用新令牌，不再用紫色或渐变底。
- [ ] **Step 3:** 清理 `index.css` 中不再被引用的类。对每个候选类名，在 `frontend/src` 下用 `grep -rn "<类名>"` 确认已无引用后再删。只删本轮迁移产生的孤儿。
- [ ] **Step 4:** 运行 `grep -rnE "8b5cf6|139, ?92, ?246|purple" frontend/src`。预期：无输出。
- [ ] **Step 5: 检查点。**

### Task D1: 整体验收与记录

**Files:**
- Modify: `docs/DEVELOPMENT_GUIDE.md`（下载器接口和页面说明）、`README.md`（下载器一节）
- Create: `progress/2026-11-01-ui-redesign-downloader.md`

- [ ] **Step 1:** 后端全量：运行 `.venv/bin/python -m pytest tests/ -q`。预期全部通过；与本计划无关的既有失败逐条记录。
- [ ] **Step 2:** 前端：在 `frontend/` 下依次运行 `npm run test`、`npm run lint`、`npm run build`。预期全部通过。
- [ ] **Step 3:** 本地启动，浏览器巡检全部页面的浅色和深色。核对清单：
  - 没有紫色残留
  - 数字列对齐
  - 375px 宽度下外壳没有横向滚动
  - 键盘可以操作到收件箱的行内操作
  - 开启 `prefers-reduced-motion` 时没有滑动动画

  截图存到 `work/screenshots/2026-11-01/`。
- [ ] **Step 4:** 更新文档：写清新接口、URL 参数，以及「与规范的偏差」4 条。写进度日志（What was done / Testing / Notes：Changed files 和 Rollback）。
- [ ] **Step 5: 最终检查点**：汇总所有改动文件，等用户决定是否提交和部署。部署后需要强制刷新浏览器。
