# 2026-11-26 女优功能：写生产配置并打开开关

经用户批准，在生产写入女优和 OpenList 配置，并打开 `ACTRESS_ENABLED`。没有改代码，也没有改数据库结构。

## What was done

- 先只读验证沿用的 OpenList 令牌：用 strm_webhook 配置（`/mnt/user/docker1/strm_webhook/config.yaml` 的 `alist_token`）列出 `/115_OPEN`，不带刷新，返回 code 200，共 60 项。令牌的来源由用户选定。
- 备份生产 `.env` 到 `/mnt/user/docker1/18xv2/data/env_backup_20261126_before_actress.env`，再在 `.env` 末尾追加以下配置：
  - `ACTRESS_ENABLED=true`
  - `ACTRESS_SOURCE_ROOT=/mnt/cache/docker1/alist-strm/video/porn_tv1`
  - `ACTRESS_ORGANIZED_ROOT=/mnt/cache/docker1/alist-strm/video/302porn_tv1`
  - `ACTRESS_PATH_MAP=/mnt/user/docker1/alist-strm/video=>/mnt/cache/docker1/alist-strm/video`
  - `OPENLIST_URL=http://192.168.70.138:5244`
  - `OPENLIST_TOKEN`（值只在生产 `.env` 里）

  原有的 89 行经比对没有变化。
- 用户在终端执行 `docker compose ... up -d --force-recreate app`，让配置生效（本机安全钩子会拦截重建命令）。

## Testing

- 重建后核对：
  - `docker-app-1` 在运行，重启次数 0，`/healthz` 返回 200；
  - 容器内 `actress_enabled` 为 True，`actress_delete_ready` 为 True，OpenList 客户端已建出；
  - 路径换算能把 `/mnt/user/...302porn_tv1/...` 换成 `/mnt/cache/...`；
  - 启动后日志里没有 ERROR 或 Traceback。
- 18x 容器能连通 OpenList：`/ping` 返回 200。
- 用户选择现在建档：在容器里用统一任务启动器依次跑了一次 `jellyfin:scan`（与每日扫描相同，只读本地 NFO，写扫描条目和演员行）和 `actress:refresh`，两个任务都是「完成」，没有报错。结果如下：
  - 演员行 8293 行；
  - 女优档案 1570 人，全部为「未标」，人数与上线前只读统计一致；
  - 有效 115 条目 6895 个；
  - 待删清单 0 部（还没人被标黑名单）。
- 没有建任何删除批次，也没有删除任何文件。

## Notes

- Changed files：本日志（新增）。生产改动只有 `.env`。
- 开关生效后，每天 03:00 的任务链会多跑「女优刷新」（建档、重算待删清单），再同步白名单女优合集。档案已手动建好；目前没有人被标黑名单或白名单，所以待删清单为空，也没有女优合集。
- 下一步：在「女优」页标黑名单，再做首次真实删除。只删 1 部用户指定的片子，核对 115 回收站、OpenList 刷新、本地文件和 Jellyfin。
- Rollback：把 `.env` 换回备份文件，或者把 `ACTRESS_ENABLED` 改成 `false`，然后执行 `up -d --force-recreate app`。
