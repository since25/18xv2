# 前端统一取数层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用两个自写 hook 和一个全局 401 处理，替换 22 个页面里手写的加载、出错和刷新代码。

**Architecture:** `frontend/src/hooks/` 下新增 `useApiQuery`（读取）和 `useApiAction`（操作），建在现有 `api/client.ts` 与各 `api/*.ts` 模块之上。`api/client.ts` 增加 401 处理函数注册，`App.tsx` 注册并负责回登录页。页面逐个迁移。

**Tech Stack:** React 19、antd 6、react-router 7、vitest + testing-library。无新依赖。

**Spec:** `docs/superpowers/specs/2026-11-17-frontend-data-hooks-design.md`（执行前必须先读）

## Global Constraints

- 只改 `frontend/` 下的文件；不改后端、不改接口地址、不改 `frontend/src/api/types.ts` 里的类型定义。
- 无新依赖：不改 `package.json` 的依赖。
- 不拆分页面、不调整页面结构和样式、不改文案。
- 每个请求原来的出错表现必须保留：原来弹错误的仍弹同样的文字，原来静默的用 `silent`。
- 不得添加 `eslint-disable`；不得删除或放宽现有测试用例。
- 进度推送订阅、轮询定时器、带中途分支提示的多请求串联流程可以保留原写法，但必须在汇报里逐个列出。
- 代码注释用中文，保持各文件现有风格（无分号、单引号、两空格缩进）。
- **不做任何 git 操作。**
- 测试只在 Spark 上跑：`scripts/remote-test.sh frontend`（依次跑 vitest、build、lint，全部通过退出码才为 0）。每次只启动一次并前台等待，不轮询。本机不跑 npm / vitest。
- 判断 401 用 `(error as { status?: number }).status === 401`，不要用 `instanceof ApiError`（现有测试只模拟了 `api` 对象）。

## Review Focus

1. 筛选条件连续变化两次、先发的请求后返回 → 页面显示后一次的结果。（Task 1 测试）
2. 页面卸载后请求才返回 → 不更新状态、不报 React 警告。（Task 1 测试）
3. 原来静默失败的请求（如 `PlansPage` 的批量操作历史）出错 → 仍然不弹提示。（各页面迁移时逐个核对，Task 3 起）
4. 多个请求同时返回 401 → 只提示一次“登录已过期”，只跳转一次。（Task 2 测试）
5. 登录接口本身返回 401（密码错误）→ 不触发“登录已过期”，仍在登录页显示原来的错误。（Task 2 测试）

---

## Interfaces（所有任务共用，名字和类型不得更改）

```ts
// frontend/src/hooks/useApiQuery.ts
export interface UseApiQueryOptions<T> {
  enabled?: boolean      // 默认 true；false 时不自动执行
  silent?: boolean       // 默认 false；true 时出错不弹提示
  initialData?: T
}
export interface UseApiQueryResult<T> {
  data: T | undefined    // 传了 initialData 时类型为 T
  loading: boolean
  error: Error | null
  reload: (options?: { silent?: boolean }) => Promise<void>  // silent: 不切换 loading
  setData: (updater: T | ((prev: T | undefined) => T)) => void
}
export function useApiQuery<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList,
  options?: UseApiQueryOptions<T>,
): UseApiQueryResult<T>

// frontend/src/hooks/useApiAction.ts
export type ApiActionResult<R> = { ok: true; data: R } | { ok: false; error: Error }
export interface UseApiActionOptions<A extends unknown[], R> {
  successMessage?: string | ((data: R, ...args: A) => string)
  onSuccess?: (data: R, ...args: A) => void | Promise<void>
  silent?: boolean
}
export function useApiAction<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>,
  options?: UseApiActionOptions<A, R>,
): { run: (...args: A) => Promise<ApiActionResult<R>>; loading: boolean }

// frontend/src/api/client.ts（新增导出）
export function setUnauthorizedHandler(handler: (() => void) | null): void
```

出错提示统一用 antd 静态 `message.error(error.message)`；401 不提示。

---

### Task 1: 两个 hook

**Files:**
- Create: `frontend/src/hooks/useApiQuery.ts`、`frontend/src/hooks/useApiAction.ts`
- Test: `frontend/src/hooks/useApiQuery.test.tsx`、`frontend/src/hooks/useApiAction.test.tsx`

- [ ] **Step 1: 写失败测试**（用 `renderHook`；antd `message` 用 `vi.mock('antd', ...)` 局部替换或 `vi.spyOn(message, 'error')`）。用例：
  - `useApiQuery`：挂载自动执行并返回数据；`loading` 先真后假；依赖变化重新执行；`enabled: false` 不执行；先发后到的旧结果被丢弃；卸载后返回不更新状态；出错时 `error` 有值并调用 `message.error`；`silent` 时不调用；401 时不调用；`reload()` 重新取数；`reload({ silent: true })` 期间 `loading` 保持假；重新加载期间 `data` 保留旧值；`initialData` 生效；`setData` 可直接改数据。
  - `useApiAction`：成功返回 `{ ok: true, data }` 并按 `successMessage`（字符串与函数两种）提示、调用 `onSuccess`；失败返回 `{ ok: false, error }` 并提示错误；`silent` 不提示；401 不提示；`run` 不抛异常；执行期间 `loading` 为真。
- [ ] **Step 2: 跑测试确认失败** `scripts/remote-test.sh frontend`，预期因模块不存在失败。
- [ ] **Step 3: 实现**两个 hook。实现须通过 `react-hooks` lint 规则（含 `set-state-in-effect`），不得禁用规则。
- [ ] **Step 4: 跑测试** 同上命令；新增用例全部通过，lint 报错数不多于基线（基线为 2 个既有报错）。

### Task 2: 登录过期统一处理

**Files:**
- Modify: `frontend/src/api/client.ts`、`frontend/src/App.tsx`
- Test: `frontend/src/api/client.test.ts`（新建）、`frontend/src/App.test.tsx`（新建）

- [ ] **Step 1: 写失败测试**：
  - client：401 且路径不是 `/auth/login`、`/auth/me` 时调用已注册处理函数并仍抛出 `ApiError`；这两个路径的 401 不调用；非 401 错误不调用；`setUnauthorizedHandler(null)` 后不调用。
  - App：已登录状态下触发处理函数 → 显示登录页、提示“登录已过期，请重新登录”；连续触发多次只提示一次；重新登录后跳回触发时所在的地址；登录接口返回 401 时仍显示原错误且不出现“登录已过期”。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现**：`client.ts` 增加处理函数注册与调用；`App.tsx` 在已登录状态注册、未登录或卸载时注销。回登录页沿用现有的 `state.from` 机制。
- [ ] **Step 4: 跑测试确认通过。**

### Task 3: 迁移 9 个简单页面

**Files:** `frontend/src/pages/` 下的 `ImportsPage.tsx`、`NodesPage.tsx`、`PlansPage.tsx`、`PlanDetailPage.tsx`、`ExecutorPage.tsx`、`HitsPage.tsx`、`KeywordDuplicatesPage.tsx`、`AuthCenterPage.tsx`、`SettingsPage.tsx`

- [ ] **Step 1: 逐页迁移**，按设计文档“迁移规则”。每页迁移前先记下该页每个请求原来的出错表现（弹什么 / 静默）和成功提示，迁移后逐个对照。
- [ ] **Step 2: 跑测试** `scripts/remote-test.sh frontend`。现有用例全部通过。
- [ ] **Step 3: 汇报**每页：迁移了哪些请求、保留原写法的请求及原因、删除的状态和 effect 数量。

### Task 4: 迁移 7 个中等页面

**Files:** `DownloaderPage.tsx` 及 `pages/downloader/` 下的 `CandidatesInbox.tsx`、`DownloaderHeader.tsx`、`TaskInspector.tsx`、`TasksBoard.tsx`；`JellyfinPage.tsx`、`ScriptRunsPage.tsx`、`QrLoginPage.tsx`、`OpenAuthPage.tsx`、`MagnetTasksPage.tsx`、`WhitelistBatchPage.tsx`

- [ ] **Step 1: 逐页迁移**。轮询（`TasksBoard` 5 秒刷新、`JellyfinPage` 任务轮询、`QrLoginPage` / `OpenAuthPage` 扫码轮询）用 `reload({ silent: true })` 或保留原定时器；进度推送订阅保留原写法。`useUndoableIgnore.ts` 不改。
- [ ] **Step 2: 跑测试**，现有用例全部通过。
- [ ] **Step 3: 汇报**，同 Task 3。

### Task 5: 迁移 6 个大页面

**Files:** `ReviewIntakePage.tsx`、`KeywordExtractorPage.tsx`、`FileDedupePage.tsx`、`KeywordsPage.tsx`、`OrganizeTasksPage.tsx`、`EmbyMediaActionsPage.tsx`

- [ ] **Step 1: 逐页迁移**，一次只改一个页面。不拆分文件、不调整结构。`EmbyMediaActionsPage.tsx` 204 行和 `ReviewIntakePage.tsx` 243 行的既有 lint 报错（`react-hooks/set-state-in-effect`）在迁移对应 effect 时一并消除。
- [ ] **Step 2: 跑测试** `scripts/remote-test.sh frontend`，预期退出码 0（测试、构建、lint 全过）。
- [ ] **Step 3: 汇报**，同 Task 3。

### Task 6: 收尾

- [ ] **Step 1: 残留检查**：在 `frontend/src/pages` 下统计 `catch` 和 `setTimeout(` 的剩余处数，逐处说明保留原因。
- [ ] **Step 2: 文档**：`docs/DEVELOPMENT_GUIDE.md` 增加一小节，说明新页面取数应使用这两个 hook 及其用法示例。
- [ ] **Step 3: 全量验证** `scripts/remote-test.sh frontend` 退出码 0；`scripts/remote-test.sh backend` 退出码 0（确认后端未受影响）。
