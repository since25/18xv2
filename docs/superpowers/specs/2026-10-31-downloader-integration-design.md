# 18x 白名单驱动 RN 下载器集成设计

## 目标

让 18x_v2 作为统一控制台，读取 RN 服务器上已经扫描好的 Telegram 资源包，用 18x 的白名单、别名和黑名单做候选匹配；用户在 18x 中确认候选包后，18x 调用下载器的精确资源包入口创建下载批次，并在本地持久化候选、提交记录、任务状态和文件进度。

第一阶段采用人工确认模式。白名单变化不会自动下载历史资源包，也不会覆盖下载器现有的监控规则。

## 边界与决策

- 两个项目通过 RN 下载器现有 HTTP Web API 通信；不共享 SQLite 文件，不直接读取 RN 文件系统。
- 18x 只负责资源包候选治理和控制命令，下载器继续负责 Telegram 访问、文件下载、上传和本地运行态。
- 资源包匹配字段为下载器返回的 `title`。白名单条目的 canonical name 和所有别名均可命中；黑名单条目和别名命中时排除。
- 仅匹配 `boundary_status=stable` 的资源包。已成功下载的包默认保留在历史中，但不生成新的待确认候选。
- 候选状态由 18x 管理：`pending`、`selected`、`dismissed`、`submitted`、`completed`、`failed`。候选不是下载器任务的替代品。
- 提交使用下载器的精确 `POST /api/packages/{package_id}/download-batch` 入口和幂等键，不使用 Web 控制台的全局选择状态。
- 下载器用户名不参与认证；现有下载器 Web 登录只需要密码。密码只从环境变量读取，不进入数据库、日志或响应。
- RN 地址、登录密码、超时和同步周期由 18x_v2 环境变量配置；未配置地址时集成保持禁用。

## 数据流

1. 用户在“下载器资源包”页面点击同步，18x 调用 RN `/api/packages` 分页读取资源包。
2. 18x upsert 资源包快照，并载入 active 的 whitelist/blacklist 关键词及 aliases。
3. 对 stable 资源包执行标准化字面量子串匹配，写入/更新候选关系和命中理由。
4. 页面展示候选包、命中的白名单、命中的黑名单、资源包状态和上次同步时间。
5. 用户选择一个或多个 `pending` 候选并提交；18x 对每个远端 package_id 创建一次幂等下载批次，记录远端 batch/task 标识。
6. 后台同步或页面刷新读取 RN `/api/tasks`、`/api/tasks/{task_id}` 和 `/api/task-dashboard`，把任务摘要与文件进度快照写入 18x。
7. 用户可以从 18x 发起下载器全局暂停/恢复、单任务取消和失败重试；每个命令都经过远端登录会话和 CSRF token。

## API 设计

18x 后端新增受保护的 `/downloader` 路由：

- `GET /downloader/status`：返回集成启用状态、RN 健康状态、最近同步时间和当前下载器状态。
- `POST /downloader/sync`：同步资源包并刷新候选，返回新增/更新/候选数量。
- `GET /downloader/packages`：读取本地资源包和候选，支持 `candidate_status`、`keyword_entry_id`、`search`、分页。
- `POST /downloader/packages/{candidate_id}/select`：将待确认候选标记为 `selected` 或恢复为 `pending`。
- `POST /downloader/download-batches`：提交选中的候选，返回本地提交记录和远端批次/任务标识。
- `GET /downloader/tasks`：读取本地任务快照；默认按最近更新时间倒序。
- `POST /downloader/tasks/sync`：同步远端任务和文件进度。
- `POST /downloader/control`：显式设置 `pause` 或 `resume`。
- `POST /downloader/tasks/{task_id}/cancel`、`POST /downloader/tasks/{task_id}/retry`：执行单任务控制。

## 错误与恢复

- RN 不可达、登录失败、CSRF 失败、超时等错误统一转为 502/503，并把安全的错误码写入 `DownloaderSyncRun`；不保存原始密码或 Cookie。
- 资源包同步是幂等 upsert；单个包异常不阻塞其他包，响应返回失败计数。
- 提交使用稳定幂等键 `18x:{node_key}:package:{remote_package_id}:r{package_revision}`。同一资源包被多条白名单命中时仍只创建一个远端批次。
- 远端提交成功但本地响应中断时，下一次同步按 package_id/task_id 关联现有记录；无法确认的记录标为 `unknown`，保留人工重试入口。
- 服务重启不自动触发下载；未完成的本地同步运行标记为 interrupted。

## 验证标准

- 单元测试覆盖：标题白名单/别名命中、黑名单排除、stable 边界过滤、候选状态转换、幂等提交、任务快照 upsert。
- HTTP 客户端测试使用 mock transport，验证登录、CSRF、分页、提交和控制命令的请求方法/路径/头部。
- FastAPI 路由测试覆盖同步、候选选择、提交、任务同步和错误映射。
- 前端页面测试覆盖候选筛选、选择提交和状态刷新。
- 不连接生产 RN 服务器执行测试；部署前再用只读健康检查和一条人工选择的资源包做现场验收。
