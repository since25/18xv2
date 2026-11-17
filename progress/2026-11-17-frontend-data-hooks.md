# 2026-11-17 前端统一取数层

## What was done

按设计 `docs/superpowers/specs/2026-11-17-frontend-data-hooks-design.md` 和计划 `docs/superpowers/plans/2026-11-17-frontend-data-hooks.md`，把 22 个取数页面的加载、出错、刷新代码收敛到两个自写工具，并加上登录过期统一处理。用户选择一次全部迁移。实施由三个 Opus 子代理顺序完成，主会话在每段之间核对范围和测试结果。

- 新增 `frontend/src/hooks/useApiQuery.ts`（读取）和 `frontend/src/hooks/useApiAction.ts`（操作）。读取工具自带“只采用最后一次请求的结果”和“卸载后不更新”的保护。
- `frontend/src/api/client.ts` 新增登录过期处理函数注册；`frontend/src/App.tsx` 在已登录状态注册：接口返回 401 时回到登录页并提示“登录已过期，请重新登录”，重新登录后回到原地址（含地址里的筛选参数）。
- 迁移 22 个页面（含下载器的 4 个子组件，共 26 个文件）。定时轮询和进度推送的机制保留在页面里，只替换其中普通的读取和操作。
- 消除 2 个既有的规范检查报错（`EmbyMediaActionsPage.tsx`、`ReviewIntakePage.tsx`）；全仓前端代码里已没有 `eslint-disable`。
- `docs/DEVELOPMENT_GUIDE.md` 新增「3.4 前端页面取数约定」。

没有新增依赖，没有改后端、接口地址和类型定义，没有拆分页面或改样式文案。

## Testing

- 前端全量（主会话独立复跑）：`scripts/remote-test.sh frontend` 退出码 0。vitest 122 passed（改动前 92，新增 30 条），build 通过，lint 0 问题。日志：Spark `~/ci/18x_v2/18x_v2/.remote-test-logs/20261117-212714-frontend.log`。
- 后端全量（子代理）：`scripts/remote-test.sh backend` 退出码 0，499 passed。日志：`20261117-212411-backend.log`。本轮后端代码和测试没有任何改动。
- 现有测试文件一个都没有修改。
- 主会话逐行审读了两个工具、`client.ts` 和 `App.tsx` 的改动；26 个页面文件只核对了改动范围、测试结果和子代理的逐页汇报，没有逐行审读。
- **未做：没有在浏览器里实际打开任何页面。** 多数页面只有“能渲染出标题”级别的冒烟测试，下面列出的行为变化全部来自读代码，没有测试覆盖。没有部署。

## Notes

### 行为变化

设计内的已知变化：

1. 登录过期后自动回登录页并提示，不再在各页面弹英文报错。
2. 快速切换筛选或翻页时只显示最后一次请求的结果。

迁移中顺带修掉的问题（原代码缺陷）：

3. **计划列表、关键词管理翻页**：原来翻页后会被重置回第 1 页（加载函数依赖页码，触发了“筛选变化回第 1 页”的 effect）。现在正常停在目标页。
4. **白名单批处理**：扫描、提交完成后刷新候选列表，原来用任务开始时的筛选条件和页码，现在用当前的。
5. **脚本日报**：重复搜索同一段文字时表格不再一直转圈。
6. **文件去重**：切换筛选或翻页时不再重复查询进行中任务并重新订阅进度。

其他可见差异：

7. 命中结果页改汇总筛选时，不再连带重新请求“最近命中记录”。
8. 多个页面的加载指示在打开页面时立刻出现（原来晚一瞬间）。
9. 下载器收件箱里“撤销”“恢复”触发的刷新使用当前筛选条件（原来用点击当时的）。
10. 脚本日报名单按默认类别自动发第二次请求时，表格会显示加载中。

### 已知未覆盖

- 进度推送（白名单、去重的 EventSource）不经过 `client.ts`，登录过期时不会触发统一处理。
- 保留原写法的轮询（扫码登录、开放平台授权、Jellyfin 任务）遇到 401 仍按原方式处理。

### 验收时建议实际点开的页面

按风险从高到低：

1. 计划列表、关键词管理：翻到第 2 页，确认停在第 2 页；改筛选后回到第 1 页。
2. 待审收件：切换状态、搜索、批量批准/忽略。
3. 白名单批处理、文件去重：跑一次扫描，确认进度和完成后的列表刷新。
4. 下载器：收件箱忽略后撤销、任务看板的自动刷新。
5. 整理任务、关键词提取、Emby 媒体操作：打开页面并做一次常用操作。
6. 登录过期：登录后在另一个标签页退出登录，再回来点任意操作，确认回到登录页并提示。

### Changed files

新建：

- `frontend/src/hooks/useApiQuery.ts`、`frontend/src/hooks/useApiAction.ts`
- `frontend/src/hooks/useApiQuery.test.tsx`、`frontend/src/hooks/useApiAction.test.tsx`
- `frontend/src/api/client.test.ts`、`frontend/src/App.test.tsx`
- `docs/superpowers/specs/2026-11-17-frontend-data-hooks-design.md`
- `docs/superpowers/plans/2026-11-17-frontend-data-hooks.md`

修改：

- `frontend/src/api/client.ts`、`frontend/src/App.tsx`
- `frontend/src/pages/` 下 22 个页面文件：AuthCenterPage、DownloaderPage、EmbyMediaActionsPage、ExecutorPage、FileDedupePage、HitsPage、ImportsPage、JellyfinPage、KeywordDuplicatesPage、KeywordExtractorPage、KeywordsPage、MagnetTasksPage、NodesPage、OpenAuthPage、OrganizeTasksPage、PlanDetailPage、PlansPage、QrLoginPage、ReviewIntakePage、ScriptRunsPage、SettingsPage、WhitelistBatchPage
- `frontend/src/pages/downloader/` 下 4 个组件：CandidatesInbox、DownloaderHeader、TaskInspector、TasksBoard
- `docs/DEVELOPMENT_GUIDE.md`

### Rollback

改动尚未提交，只涉及前端代码和文档。恢复已修改文件并删除新建的代码文件即可：

```bash
git checkout -- frontend/src docs/DEVELOPMENT_GUIDE.md
```

```bash
rm -r frontend/src/hooks frontend/src/App.test.tsx frontend/src/api/client.test.ts
```
