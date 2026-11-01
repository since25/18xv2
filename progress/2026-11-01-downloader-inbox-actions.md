# 2026-11-01 收件箱行内下载与频道忽略挪位

## What was done

- 候选收件箱每行操作改为「下载」（主按钮，直接提交该资源包的全部候选）和「忽略」；去掉行内「忽略频道」。勾选 + 底部浮动栏批量下载保留。
- 顶部工具栏新增「频道」筛选下拉（选项来自已有的 `GET /downloader/channels`）；选中频道后出现「忽略此频道」，忽略后自动清掉筛选，5 秒内可撤销。
- 后端 `GET /downloader/packages?view=...` 新增可选参数 `channel_title`（精确匹配），计数也按该筛选统计。
- `docs/DEVELOPMENT_GUIDE.md` 同步接口参数和页面操作说明。

## Testing

- `npx vitest run src/pages`：9 个文件 54 个用例通过（新增行内下载用例，频道忽略用例改为走工具栏）。
- `tsc` 类型检查、eslint（改动文件）无报错。
- `pytest tests/downloader -q`：34 通过（新增按频道筛选用例）。
- 未在真实页面里目视检查布局，未部署。

## Notes

Changed files：
- app/services/downloader/query_service.py
- app/api/routes/downloader.py
- tests/downloader/test_query_service.py
- frontend/src/api/downloader.ts
- frontend/src/pages/downloader/CandidatesInbox.tsx
- frontend/src/pages/downloader/CandidatesInbox.test.tsx
- docs/DEVELOPMENT_GUIDE.md

Rollback：还原以上文件即可；新增参数是可选的，不涉及数据库结构。

---

# 追加：收件箱新增「未命中」视图

## What was done

- 收件箱分段改为「待确认 / 未命中 / 已忽略」。未命中＝已同步、没被忽略、当前版本没有未作废白名单候选的资源包（包括黑名单排除的、已下载完成的）。
- 未命中视图里每行可直接「下载」或「忽略」；上游未整理完成（非 stable）的包下载按钮置灰。该视图隐藏白名单词筛选；下载状态筛选新增「已完成」。
- 后端新增 `POST /downloader/packages/download`（按 `package_ids` 提交），提交记录 `candidate_id` 为空；不涉及数据库结构变更。
- 原候选提交 `submit_selected` 的单包提交逻辑抽成 `_submit_package` 复用，行为不变；`list_inbox` 计数循环合并为三视图统一统计，`counts` 新增 `unmatched`。

## Testing

- 后端全量 `pytest tests -q`：387 通过（新增未命中列表 + 按包提交幂等、拒绝非 stable 两个用例；已有的计数断言补上 `unmatched` 字段）。
- 前端全量 `npx vitest run`：19 个文件 81 个用例通过；`tsc`、eslint 无报错。
- 未在真实页面目视检查，未部署。

## Notes

Changed files（本次追加）：
- app/services/downloader/sync_service.py、query_service.py
- app/api/routes/downloader.py、app/schemas/downloader.py
- tests/downloader/test_sync_service.py、test_query_service.py、tests/api/test_downloader_routes.py
- frontend/src/api/downloader.ts、frontend/src/pages/downloader/CandidatesInbox.tsx、CandidatesInbox.test.tsx
- docs/DEVELOPMENT_GUIDE.md

Rollback：还原以上文件；新接口和 `unmatched` 计数都是新增项，无数据迁移。
