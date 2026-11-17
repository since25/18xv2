# 2026-11-17 后台任务统一启动器

## What was done

按设计 `docs/superpowers/specs/2026-11-17-background-job-runner-design.md` 和计划 `docs/superpowers/plans/2026-11-17-background-job-runner.md`，把 9 个后台长任务收敛到一个统一启动器。实施由 Opus 子代理完成，主会话审读了全部改动并独立复跑了后端测试。

- 新增 `app/services/job_runner.py`：判重（进程内锁 + 查库同类型未完成任务）、建记录、后台线程执行、进度回调、成败统一收尾、进度推送、过期清理。
- 迁移到启动器的任务：目录导入 1 个，白名单批处理 2 个（扫描、提交），文件去重 3 个（扫描、远端确认、限流删除），Jellyfin 3 个（扫描、合集同步、封面）。
- 删除各路由里的内存锁、内存进度字典、重复的执行包装和两个内容相同的清理循环；`app/main.py` 只启动一个清理循环，且不再从路由文件导入。
- 白名单和去重的后台任务改用全局唯一的 115 客户端（原来 3 处各自新建客户端，不受全局请求间隔和令牌刷新锁控制）。
- `docs/DEVELOPMENT_GUIDE.md` 新增「8.1 后台长任务」小节，说明以后新增长任务的三步写法。

接口地址、返回格式、数据库表结构、前端均未改动。

## Testing

- 后端全量（主会话独立复跑）：`scripts/remote-test.sh backend`，退出码 0，499 passed。日志：Spark `~/ci/18x_v2/18x_v2/.remote-test-logs/20261117-203827-backend.log`。改动前基线为 477 passed，新增 22 个用例。
- 后端全量（子代理，两次）：均为 499 passed。
- 前端（子代理）：`scripts/remote-test.sh frontend`，测试 92 passed、构建通过，**lint 退出码 1**（2 errors, 1 warning）。日志：`20261117-203511-frontend.log`。
  - 报错位置：`frontend/src/pages/EmbyMediaActionsPage.tsx` 204 行、`frontend/src/pages/ReviewIntakePage.tsx` 243 行，规则 `react-hooks/set-state-in-effect`。
  - 本轮 `frontend/` 下没有任何文件改动，这两个文件最后一次修改是 2026-11-01，属于既有问题，未处理。
- 未做：没有启动真实服务、没有连真实 115 验证；“后台任务与页面操作共用 115 请求间隔”只由单元测试覆盖（验证后台任务拿到的是全局客户端对象）。没有部署。

## Notes

已知行为变化（设计文档已列，用户已确认）：

1. 批量任务对 115 的请求与页面操作共用一个请求间隔，两边同时进行时都会慢一些。
2. 同类型任务判重以数据库为准。副作用：如果某个任务连“写失败记录”都失败，库里会留下未完成记录，同类型任务会一直被拒绝，直到服务重启时由启动恢复逻辑清掉。
3. 目录导入的进度推送在完成后再推一帧即断开（原来等 5 秒）。该接口目前没有页面使用。

与计划不一致的地方：

- `app/main.py` 的清理循环改动提前到 Jellyfin 迁移之前做，否则 Jellyfin 路由测试在基线就因导入失败而报错。
- Jellyfin 扫描的干活函数写成工厂 `scan_work(job_id)`，因为扫描服务需要任务编号。
- 目录导入失败时，把导入批次置为失败之前先回滚会话（原来没有回滚，会话出错时这一步会失败）。
- 合集同步去掉了 except 里多余的一次 `client.close()`，只保留 `with client:`。

遗留（未处理，不在本轮范围）：

- 前端两处 lint 报错（见 Testing）。
- `app/services/importer/remote_tree_service.py:163` 有一行注释还提到已删除的 `_import_lock`。
- `app/api/routes/dedupe.py` 里的 `logger` 现在没有被使用。

### Changed files

新建：

- `app/services/job_runner.py`
- `tests/services/test_job_runner.py`
- `docs/superpowers/specs/2026-11-17-background-job-runner-design.md`
- `docs/superpowers/plans/2026-11-17-background-job-runner.md`

修改：

- `app/api/routes/whitelist_batch.py`
- `app/api/routes/dedupe.py`
- `app/api/routes/imports.py`
- `app/api/routes/jellyfin.py`
- `app/services/jellyfin/job_runner.py`
- `app/main.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `tests/whitelist/test_whitelist_batch_routes.py`
- `tests/api/test_dedupe_routes.py`
- `tests/api/test_imports_async.py`
- `tests/jellyfin/test_job_runner.py`
- `tests/jellyfin/test_routes.py`

### Rollback

改动尚未提交，不涉及数据库和配置。恢复已修改文件并删除新建的两个代码文件即可：

```bash
git checkout -- app/ tests/ docs/DEVELOPMENT_GUIDE.md
```

```bash
rm app/services/job_runner.py tests/services/test_job_runner.py
```
