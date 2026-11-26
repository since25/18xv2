# 2026-11-12 下载器搜索词一键加黑/白名单上线

## What was done

- 提交 `8130d14f` 并推送 GitHub `main`（只添加本功能相关文件）。
- Unraid：`git pull --ff-only`（84dde77 → 8130d14），先 `docker compose -f docker/docker-compose.yml build app` 单独构建，再 `up -d --no-build app` 替换容器。无数据库迁移，未做备份。

## Testing

- 构建：退出码 0，构建期间最低可用内存约 5.3GB，负载 1.07。构建时带内存守护（低于 1.5GB 中止），未触发。
- `/healthz` 200，容器 Up，启动日志无 error / traceback。
- 容器内 dry_run 预览：黑名单「合集」→ 涉及 561 个资源包、将移走 124 条候选、示例 5 条。
- 预览后核对数据库：`keyword_entries` 中无「合集」，待确认候选仍为 4176，确认预览未落库。
- 未在页面上实际确认加入任何词，留给用户使用。

## Notes

- Changed files：本日志。
- Rollback：服务器 `git checkout 84dde77`（或 revert `8130d14f` 后 pull），`docker compose -f docker/docker-compose.yml up -d --build app`。
