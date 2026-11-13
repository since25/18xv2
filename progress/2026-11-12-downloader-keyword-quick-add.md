# 2026-11-12 下载器收件箱：搜索词一键加入白名单 / 黑名单

## What was done

- 设计：`docs/superpowers/specs/2026-11-12-downloader-keyword-quick-add-design.md`；计划：`docs/superpowers/plans/2026-11-12-downloader-keyword-quick-add.md`。
- 后端新增 `POST /downloader/keyword-quick-add`（`app/services/downloader/keyword_quick_add.py`）：
  - 写入关键词后只重算标题包含该词的资源包，复用同步时的 `_load_terms` / `_match_package`，匹配规则不变；
  - `dry_run=true` 走同一流程后回滚，预览数字与实际一致；
  - 已存在的词按不分大小写查找（含别名）：类型不同或已停用返回 409，类型相同则只重算。
- 前端收件箱搜索框有内容时出现「加入白名单」「加入黑名单」按钮，弹窗显示影响数量和示例标题，确认后刷新列表。
- 开发指南补充接口说明。

## Testing

- Spark 后端全量：`477 passed`（新增 10 条：服务 9 条、路由 1 条）。
- Spark 前端：`92 passed`（新增 3 条），build 通过；lint 仍为原有的 2 个错误 + 1 个警告（`EmbyMediaActionsPage.tsx`、`ReviewIntakePage.tsx`），与本次无关。
- 未部署，未在生产环境实际点击。

## Notes

- Changed files：
  - `app/services/downloader/keyword_quick_add.py`（新）、`app/schemas/downloader.py`、`app/api/routes/downloader.py`
  - `frontend/src/api/downloader.ts`、`frontend/src/pages/downloader/CandidatesInbox.tsx`
  - `tests/downloader/test_keyword_quick_add.py`（新）、`tests/api/test_downloader_routes.py`、`frontend/src/pages/downloader/CandidatesInbox.test.tsx`
  - `docs/DEVELOPMENT_GUIDE.md`、上述设计 / 计划文档、本日志
- 无数据库迁移。
- 尚未提交 git。
- Rollback：撤销上述文件改动后重建 app 容器。通过本功能加入的词，到关键词页删除即可；被移走的候选会在下一轮同步时恢复。
