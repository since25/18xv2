# 生产机失联排查与脚本日报部署

## What was done

- 部署 `b907e0f` 到生产：先备份数据库，再快进拉取，构建成功后替换 `docker-app-1`，迁移升至 `20261102_0017`。
- 只替换 18x 应用容器，未改 Jellyfin、闲鱼监控和 `/boot` 下的生产脚本。
- 排查 2026-11-02 10:50–16:02（北京时间）的失联。

### 失联时间线（北京时间）

| 时间 | 事件 |
| --- | --- |
| 10:47 | Unraid 看门狗最后一次按时记录，此后到 16:02 中断 |
| 10:49:27 | Pi 会话在闲鱼项目执行 `docker compose -f docker-compose.local.yaml up --build -d app` |
| 10:49:36 | 构建容器网卡 `veth87dae8a` 创建 |
| 10:50:37 | Jellyfin 心跳告警的卡顿起点；Jellyfin、18x 日志随后中断 |
| 11:04 | Pi 的构建命令 900 秒超时 |
| 11:49–12:28 | SSH 三次触发 MaxStartups 限流 |
| 12:25 | 负载 594–612，可用内存 814MB，无 swap；`vue-tsc -b` 仍在运行 |
| 12:46 | 一次 SQUASHFS xz 解压错误；网页进程开始被批量 SIGKILL |
| 16:01–16:02 | 服务恢复；16:02:02 `veth87dae8a` 销毁 |

### 结论

- 直接触发点是闲鱼项目那次镜像构建：卡死和恢复都与构建容器的存在时段吻合。
- 机器未重启（运行 102 天），系统日志没有 OOM、内核挂起和硬盘报错。
- Jellyfin 扫描是加重因素，不是主因：扫描从 08:30 起已运行两个多小时未卡死，恢复后仍在运行；本次 18x 构建与扫描并行，136 秒完成，可用内存最低 3960MB。
- 未能确认：`vue-tsc` 的实际内存占用、构建为何持续 5 小时、16:01 恢复的直接原因。生产机未开启 sar 和 PSI，没有历史资源数据。

## Testing

- 备份：`data/backup_20261102_before_0017.sql`，134M，结束标记完整。
- 构建：退出码 0，用时 136 秒，最低可用内存 3960MB。
- 部署后：未登录访问 `/api/script-runs/summary` 返回 401（符合预期），首页 200，迁移版本 `20261102_0017`，两张新表存在，前端包含日报页，启动日志错误行 0。
- Jellyfin 8097 返回 302，容器 healthy；闲鱼容器未被改动。
- 未做：登录后的页面操作验收；真实脚本回报联调。

## Notes

- 脚本日报尚未接入：`report_script_run.py` 未复制，`DEL_SOMETHING` 和 `MOVE_SSD_CACHE_TO_DISK2` 未加回报片段，页面暂无真实记录。
- 闲鱼项目的改动未生效：运行中的镜像仍是 08:34 构建的版本。
- Changed files：本日志；生产代码快进到 `b907e0f`。
- Rollback：回退 18x 版本并执行 `alembic downgrade 20261101_0016`，只会删除脚本日报的两张表；数据库备份见上。

## 补充：闲鱼项目重新构建

### What was done

- 16:52 在生产机以内存和负载保护重新构建 `ai-goofish-monitor`，确认爬虫空闲后替换容器。
- 旧镜像保留为 `ai-goofish-monitor:rollback-20261102`。闲鱼目录的未提交改动未提交、未改动。

### Testing

- 构建：退出码 0，用时 126 秒，最低可用内存 3983MB，最高负载 19，`vue-tsc` 峰值 462MB；同时 Jellyfin 仍在扫描。
- 部署后：首页 200，启动日志错误行 0，汇总脚本可运行，新代码和前端页面已进入容器。
- 未做：浏览器中的页面验收。

### Notes

- 修正上文结论：同一构建这次没有复现卡死，`vue-tsc` 内存也不高，不能再认定它耗尽内存，也不能认定构建是唯一原因。10:49 的构建只与卡死开始时间吻合。16:02 网卡销毁也可能是系统恢复后的结果，而不是恢复的原因。
- 12:26 的数据是负载约 600，可运行任务只有 14 个，说明大量任务在等待，而不是在抢 CPU。等待的具体对象未查明。
- Rollback：把 compose 使用的 `ai-goofish-monitor:local` 重新指向回滚标签后执行 `docker compose -f docker-compose.local.yaml up -d --no-build app`。

## 补充：资源记录与网卡环路核查

### What was done

- 在生产机安装每分钟资源记录：脚本 `/mnt/cache/docker1/sysmon/sysmon.sh`，日志 `/mnt/cache/docker1/sysmon/logs/`，保留 7 天；定时配置 `/boot/config/plugins/dynamix/sysmon.cron`，重启后保留。
- 记录内容：负载、内存、FUSE 等待数、网卡和磁盘累计计数、D 状态进程及其等待点、CPU 和内存占用前五。
- 核查网卡环路猜测。

### Testing

- 单次运行 0.19 秒，CPU 时间 0.156 秒，约占 1 核的 0.26%。
- 每次约 1.2KB，折合每天约 1.7MB、7 天约 12MB。
- 定时任务已按分钟触发（17:01:01、17:02:01）。
- 网卡（累计 102 天）：eth0、eth1 链路故障 0 次，广播各约 910 万个（平均约 1 个/秒），`rx_missed` 2，softnet 丢包 0，syslog 无链路或环路告警；当前约 200 包/秒。

### Notes

- 结论：不支持网卡环路是这次卡死的原因。5 小时内若有持续广播风暴，累计广播数不会只有约 910 万；看门狗在卡死期间连"无响应"也没写，说明本机任务本身卡住。
- 无法排除：未到达本机的交换机侧问题，或单播环路。它们解释不了本机卡死，但可能单独造成外部不可达。
- 待验证猜测：FUSE 文件系统（shfs、clouddrive2）卡住。依据是大量任务在等待、Docker 命令无响应；现有记录已能验证（`fuse_waiting`、`D_by_wait`）。
- Rollback：删除 `/boot/config/plugins/dynamix/sysmon.cron`，运行 `/usr/local/sbin/update_cron`，再删除 `/mnt/cache/docker1/sysmon`。

## 补充：脚本日报接入生产脚本

### What was done

- 备份原脚本到 `/boot/config/plugins/user.scripts/backup_20261102_before_report/`。
- 复制 `report_script_run.py` 到 `/mnt/cache/docker1/python/scripts/delsomethin/`，校验和与仓库版本一致。
- 按 `docs/unraid-script-reports.md` 把回报片段插入 `DEL_SOMETHING`（`flock` 判断后）和 `MOVE_SSD_CACHE_TO_DISK2`（`DRY_RUN` 解析后），两边都没有删除原有行。
- 未手动运行真实任务，等定时运行：`MOVE_SSD_CACHE_TO_DISK2` 每天 01:01，`DEL_SOMETHING` 每天 12:09。

### Testing

- 语法检查：两个脚本 `bash -n` 通过。
- 模拟运行（回报程序换成桩）8 个场景全部通过：退出码 0、1、3、7 和 `set -e` 失败时退出码不变，输出完整保留，临时文件已清理，演练模式不回报。
- 真实 `MOVE_SSD_CACHE_TO_DISK2 --dry-run`：原版和接入版退出码都是 0，输出无差异。
- 真实日志解析（只算不发）：`DEL_SOMETHING` 60215 行、`MOVE_SSD_CACHE_TO_DISK2` 7189 行，未识别行都是 0。
- 用生产凭证登录成功，`/api/script-runs/summary` 返回 200；`script_runs` 仍为 0 行，没有写入测试数据。
- 未做：真实写入回报的端到端验证，要等 2026-11-03 01:01 首次定时运行。`DEL_SOMETHING` 的完整流程只用模拟脚本验证，没有实跑。

### Notes

- Changed files：生产的两个 `/boot` 脚本和 `delsomethin/report_script_run.py`；仓库无代码改动。
- Rollback：把备份目录中的 `DEL_SOMETHING.script`、`MOVE_SSD_CACHE_TO_DISK2.script` 复制回各自目录的 `script`。
