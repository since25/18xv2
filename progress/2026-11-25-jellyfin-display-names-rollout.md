# 2026-11-25 Jellyfin 显示名：提速版部署与第二次试跑

## What was done

- 提速版（提交 `15129fa7`）快进合并进 `main` 并推送；主工作区其他会话的未提交文件照旧未带入。
- 生产（北京时间 2026-11-26）：12:41 拉取，12:41–12:42 单独构建镜像，确认没有运行中的后台任务后切换容器。
- 用户选「徐妤瞳」（111 个视频、3 个资源包）试跑：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --keyword 徐妤瞳`。

## Testing

- 部署后：首页 200；`/api/jellyfin/status` 未登录 401；`Application startup complete`；容器内配置为每页 5000、超时 30 秒、每日开关 False。
- 徐妤瞳试跑（12:45:18–12:45:25，共 7 秒，含 Python 启动）：改名 111、合集排序 1、失败 0、未入库 0。
- 试跑前后 3 个资源包目录文件清单一致（111/111，无新增文件）。
- 读回 Jellyfin：名字为 `序号 · 徐妤瞳/<资源包>`、均锁定；合集 `DisplayOrder: SortName`，按 10941 → 33073 → 33116、包内 01 起顺序排列。
- 由此估算：单条写入约 0.04 秒，全量约 4.1 万条约 25 分钟，加上读取约 35 秒。
- 扫库后名字保持（设计第八节第 4 条）：经用户同意，12:47 手动启动 Jellyfin 计划任务「扫描媒体库」（`RefreshLibrary`，与每晚 02:30 相同，不是元数据刷新），12:47:05–12:47:57 完成，结果 Completed。之后对两个关键词只预览：何娃娃待改 0、已正确 14；徐妤瞳待改 0、已正确 111 → 名字、强制排序名、名字锁均未被扫库改回。

## Notes

- Changed files：本日志（新增）。代码见提交 `15129fa7`。
- 生产上已改名：全部已入库的本地视频（41072 条）；24 个新视频待 Jellyfin 入库。
- 全量（经用户同意，`docker exec docker-app-1 python scripts/jellyfin_display_names.py`，12:48:48–13:01:52，784 秒）：改名 40947、已正确 125（试跑过的两个关键词）、失败 0、未入库 24、跳过 0、合集排序 735。开始前确认无运行中任务；前后「已整理」目录下 `.nfo` 数量均为 0。
- 全量后再只预览一次（81 秒）：待改 0、已正确 41072、失败 0、未入库 24。
- 打开每日开关（经用户同意，13:05）：备份生产 `.env` 到 `backups/env-20261126-before-display-names`，追加 `JELLYFIN_DISPLAY_NAMES_ENABLED=true`（带中文注释，除新增两行外与备份一致），确认无运行中任务后 `docker compose -f docker/docker-compose.yml up -d --force-recreate app`。重建后首页 200、`Application startup complete`；容器内开关 True、每日会执行 True、每日小时 3。今后每天 03:00 扫描 → 合集同步 → 显示名同步，新视频（含这 24 个未入库的）会自动改名。
- 待核对：明天（2026-11-27）03:00 后第一次每日显示名任务的摘要（`background_jobs` 里 `jellyfin:names`），预期只改当天新入库的视频。
- Rollback：先关开关（`.env` 用 `backups/env-20261126-before-display-names` 还原，或把该行改成 `false`，再 `up -d --force-recreate app`）；再 `docker exec docker-app-1 python scripts/jellyfin_display_names.py --restore`（可加 `--keyword`）；代码需要时回退到 `5c0f9138` 后重建 18x。
