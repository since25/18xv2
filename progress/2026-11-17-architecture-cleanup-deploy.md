# 2026-11-17 架构整理五个提交上线

## What was done

用户明确要求“部署到生产”。

- 推送 GitHub `main`：`8130d14f..d9396d34`，共五个提交：
  - `9498a4f0` 删除 7 个旧版内嵌网页
  - `b836c387` 后台长任务统一启动器，改用全局 115 客户端
  - `1f038868` 前端统一取数层，登录过期统一处理
  - `8cc5f5e5` 前端类型由后端接口定义生成
  - `d9396d34` 磁力任务页批次号修复
- Unraid（`/mnt/user/docker1/18xv2`）：`git pull --ff-only`（8130d14 → d9396d3），先 `docker compose -f docker/docker-compose.yml build app` 单独构建，再 `up -d --no-build app` 替换容器。
- 这五个提交没有数据库迁移，没有依赖和 Docker 配置变化，未做数据库备份。

## Testing

- 部署前：生产机可用内存约 6.5GB，负载 0.25；`background_jobs` 中没有未完成的任务（替换容器前又查了一次，仍为 0）。北京时间 22:20，不在闲鱼定时任务窗口内。
- 构建：退出码 0。构建期间最低可用内存约 5.15GB，带内存守护（低于 1.5GB 中止），未触发。
- 替换后：容器 Up；`/api/healthz` 200；未登录访问 `/api/auth/me`、`/api/plans/data` 返回 401（符合预期）；启动日志无 error / traceback，`Application startup complete`，下载器同步循环正常请求。
- 容器刚启动的头几秒 `/api/` 返回过 502（后端还在启动），约 10 秒内恢复。
- 部署后可用内存约 6.8GB，负载 1.57（构建刚结束）。
- **未做：没有登录网页实际点开任何页面。** 页面验收留给用户，清单见 `progress/2026-11-17-frontend-data-hooks.md` 的“验收时建议实际点开的页面”，另加：磁力任务页拉取一次目录树，确认提示里的批次号是数字。也没有在真实 115 上跑白名单扫描或去重。

## Notes

- 部署后浏览器需要强制刷新，否则看到的还是旧页面（nginx 没给 index.html 设缓存头）。
- 对应看板卡片 TASK-150，已追加部署备注，状态未改，等用户验收。
- Changed files：本日志。
- Rollback：服务器 `git checkout 8130d14`，再 `docker compose -f docker/docker-compose.yml up -d --build app`。不涉及数据库。
