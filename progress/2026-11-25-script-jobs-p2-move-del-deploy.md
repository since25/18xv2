# 2026-11-25 脚本中心第二、三段（MOVE + DEL）：合并与生产部署

## What was done

- 用户批准“合并部署”。
- **合并**：
  - 先删掉主目录里那份未跟踪的计划拷贝。这是我写的，和分支里的版本逐字节相同。
  - `worktree-script-jobs-p2-move-del` 快进合并到本地 `main`（`95226643..dcc2931f`）。
  - 主目录里其他会话留下的未提交文件都没有动。
- **推送**：`main` 推送到 GitHub，`95226643..dcc2931f`。
- **部署前检查**（22:25）：
  - 18x 没有排队或运行中的脚本，Unraid 上也没有 MOVE / DEL 进程；
  - 当时不在任何脚本的运行时间内；磁盘剩余 213G。
- **备份**：完整备份数据库到 `data/backup_20261125_before_move_del.sql`，202MB，结束标记完整。这次没有数据库迁移。
- **部署**：
  - 生产机 `git pull` 到 `dcc2931`，执行 `docker compose -f docker/docker-compose.yml up -d --build app`，容器按新挂载重建。
  - 部署日志在生产机 `/tmp/18x_deploy_20261125_p2.log`。
- **未做**：MOVE、DEL 的执行方仍是 `unraid`，定时仍由 Unraid 运行。演练对比和切换按 `docs/script-jobs.md` 的 MOVE / DEL 手册逐步请用户批准后再做。

## Testing

- 合并是快进，代码与分支上全量测试通过的 `dcc2931f` 完全相同：后端 718、前端 143，build、lint 通过。
- 部署后核对：
  - `alembic current` 为 `20261125_0018`；首页 200；未登录访问接口 401；启动日志没有错误行；“脚本调度循环已启动”。
  - 挂载：
    - `/mnt/cache/docker1/SSD_cache`、`/mnt/disk2/qbbtdn` 都以相同路径、可写挂载；
    - 原来单独的 `/mnt/disk2/qbbtdn/已整理` 挂载已去掉，容器里仍能看到这个目录，共 791 项，归属 99:users；
    - 其他挂载不变。
  - 容器里有 `/app/scripts/jobs/` 下的三个脚本；`bash`、`chown`、`find`、`stat` 都在；`requests` 可以导入。
  - 配置：sehuatang 为 18x、启用、01:28，不受影响；MOVE、DEL 为 unraid。
- 未做：页面验收、Jellyfin 本地媒体功能的回归检查（路径没变）、两边演练对比。

## 演练对比（2026-11-26 07:39，用户要求“现在做演练对比”）

- 18x 一侧：在容器里临时建登录会话调用接口发起演练，用完即删会话，不经过密码。Unraid 一侧按手册运行。用到的临时脚本已从生产删除。
- **MOVE**：18x 运行 #53 成功；Unraid 用原脚本 `--dry-run`。两边输出逐字相同。
  - 但源目录 `SSD_cache/已整理` 当时是空的（01:01 已全部搬走），这次只证明 18x 能跑通，没有比到真实文件。
- **DEL**：18x 运行 #54 成功；Unraid 用两个 Python 脚本，设置 `DRY_RUN=true`，跑 7 条整理任务。
  - 关键行（`[DRY-RUN]`、`[ERROR]`、`[WARN]`、`[AMBIGUOUS…]`、`[SKIP]`、`[MERGED]`）去掉行首空白后排序：两边各 370 行，完全一致。
  - 页面名单与 Unraid 日志条数一致：将删除目录 14、将删除文件 26、将移动 328（新 8、复查 320）。
  - 全文差异只有 3 类，都在预期内：
    1. 删除目录在 18x 里少了结尾的 `/`，删除名单不受影响；
    2. 日志文件路径改到运行目录；
    3. 18x 多一行“演练模式，跳过修正权限”。
- 对比文件留在生产 `/tmp/move_dry_{unraid,18x}.txt`、`/tmp/del_dry_{unraid,18x}.txt`。

## DEL 切换到 18x（2026-11-26 07:58，用户批准“现在切 DEL”）

- 切换前：没有脚本在运行。
- **Unraid**：
  - 先备份 `schedule.json`、`customSchedule.cron`，后缀 `.bak-20261126-del-to-18x`。
  - `schedule.json` 只把 DEL_SOMETHING 的 `frequency` 从 `custom` 改成 `disabled`（`custom` 字段保留 `9 12 * * *`），并从 `customSchedule.cron` 删掉 DEL 那一行。
  - 执行 `update_cron` 后，`/etc/cron.d/root` 里已经没有 DEL；MOVE（01:01）、restartNFS、vaultwarden_backup 不变。
- **18x**：
  - 通过接口把 DEL_SOMETHING 改为执行方 18x、启用，时间仍是 12:09。
  - 有修改记录（`script_job_config_changes` #2，记了改之前的值）。
  - 下次运行是 2026-11-26 12:09（上海时间）。
- 现在的配置：sehuatang 由 18x 运行，定时开，01:28；DEL 由 18x 运行，定时开，12:09；MOVE 仍由 Unraid 运行，01:01。

## Notes

- 待做：
  - 12:09 后核对 18x 第一次真实运行的 DEL：运行记录、名单、日志，以及宿主机上新整理目录的归属是不是 `nobody:users`。
  - 下午 MOVE 再演练对比一次，用户批准后在 01:01 前切换。
- DEL 的回滚：
  - 18x 里把 DEL 执行方改回 unraid，或关掉定时开关。
  - 用 `.bak-20261126-del-to-18x` 恢复 Unraid 的两个文件，再执行 `/usr/local/sbin/update_cron`。
- 2026-11-26 01:28 sehuatang 第一次真实运行，照原计划核对。
- Changed files：生产代码升到 `dcc2931`；生产 app 容器挂载；仓库里只有本日志。
- Rollback：
  - **代码和挂载**：生产机 `git checkout 95226643 -- .` 或 `git reset --hard 95226643`，再 `docker compose -f docker/docker-compose.yml up -d --build app`。挂载随 compose 文件恢复，没有数据库变更。
  - **数据库**：本次没有改，备份 `data/backup_20261125_before_move_del.sql` 只是保险。
