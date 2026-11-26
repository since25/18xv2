# 生产机内存不足卡顿排查与处置

## What was done

- 读取 `/mnt/cache/docker1/sysmon/logs/` 现场日志，定位 2026-11-04 08:18–12:17（北京时间）卡顿。
- 经用户确认后处理生产机：
  1. 备份系统日志到 `/mnt/cache/docker1/sysmon/incident-20261104/syslog.gz`，再清空 `/var/log/syslog`。
  2. 只丢弃 `/boot/bzfirmware` 的内存缓存，清除损坏副本；未重启，未改 U 盘文件。
  3. 用 `docker update` 给 `ai-goofish-monitor-app` 设 3GB 内存上限；未重启容器。
- 仓库代码无改动。

### 时间线（北京时间）

| 时间 | 事件 |
| --- | --- |
| 08:05–08:10 | 闲鱼 `m2pro` 正常跑完 |
| 08:15 | 闲鱼启动 `m3pro` |
| 08:17 | `flaresolverr` 收到第一个站点请求 |
| 08:18 | 负载升到 23，缺页明显上升 |
| 08:23 | `flaresolverr` 同时收到 4 个站点签到请求，随后 Chrome 启动失败 |
| 08:25 后 | 负载近 300，100+ 进程等待 I/O；闲鱼后续任务被跳过 |
| 10:06 起 | SQUASHFS 报错持续刷屏 |
| 12:13 | `m3pro` 日志最后写入（约 4 小时，正常约 5 分钟） |
| 12:14–12:17 | 负载回落，服务恢复 |
| 12:25 | `/var/log` 写满 |

### 结论

- 直接机制（日志证实）：可用内存约 1.3GB、无 swap，缺页由约 100 次/分钟升到约 28000 次/分钟；U 盘启动盘和 Docker 镜像盘接近满载。
- 触发（相关性强，未做对照实验）：闲鱼爬虫与 `flaresolverr` 的 Chrome 重叠。08 点最重，可能是因为 `flaresolverr` 的站点签到只集中在这个时段。调用方未确认，疑似 MoviePilot。
- 18x 和 Jellyfin 与卡顿时间无相关性，但 18x 常驻约 38% 单核、0.9GB，并约每 17 秒登录一次下载器，压缩了内存余量。
- FUSE 猜测排除（`fuse_waiting` 基本为 0）；网络正常。SSH 卡在查公钥，`/root/.ssh` 位于 U 盘，二者对应关系是推断。
- 11-02 的卡死没有现场日志，时间也与闲鱼定时不符，不能认定是同一原因。

## Testing

- 备份：`gzip -t` 通过。
- 清空后 `/var/log` 从 100% 降到 14%；13:00 复查为 17%，SQUASHFS 最后一条为 12:59:12。
- `/boot/bzfirmware`：丢弃缓存前有 1 字节不同（偏移 0x10fbe000，原值 0xF9，缓存为 0）；之后差异 0 字节，校验值与 `.sha256` 一致。
- 闲鱼：`memory.max` 为 3221225472，容器运行中，页面返回 200；历史峰值约 2.6GB，`oom_kill` 为 0。
- 未验证：上限在下一轮爬虫时的效果；是否防止再次卡顿。

## Notes

- `docker update` 的上限在容器重启后保留，但 `docker compose up` 重建容器后会丢失；闲鱼目录有用户未提交的改动，本次未改 compose。
- 内核不支持 swap 限制，命令有提示；机器无 swap，不影响上限生效。
- 单字节损坏原因未明，建议择机跑 memtest。
- Changed files：本日志；生产机改动见上。
- Rollback：`docker update --memory 0 --memory-swap -1 ai-goofish-monitor-app` 取消上限；日志备份见上。

## 补充：清理内存盘

### What was done

- 经用户确认，删除生产机 `/root/.vscode-server/cli/servers/` 下 3 个未运行的版本（`261c84cb`、`2c33b50b`、`e6468682`），保留运行中的 `6d62b1d5`。
- 删除 `/tmp/bench`、9 月的 7 个测试视频（`u1`、`u2`、`u4`、`u5`、`r30`、`fix_test`、`flv_test`）和 2 个 `app_migration_*.sqlite3`。
- 其他 `/tmp` 文件用途不明，未动。

### Testing

- 删除前检查：目标文件未被进程打开，3 个版本没有运行中的进程。
- 内存盘占用由 4.6GB 降到 1.9GB；可用内存由 4095MB 升到 6904MB；共享内存由 5125MB 降到 2328MB。
- 清理后 18x `/healthz` 200，Jellyfin 302，Unraid 网页 302，ReaderSelf 200。

### Notes

- 删除的文件不可恢复；下次用对应版本的 VS Code 连接时会重新下载约 640MB，仍占内存盘。
