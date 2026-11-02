# 2026-11-01 Jellyfin 第一版部署（进行中）

## What was done

- 提交 `d2b95921` 到 `jellyfin-v1`，推送分支，并快进到 `main`（生产从 `main` 拉取）。
- 生产服务器（服务器时间 2026-11-02 08:15）：
  - 备份：`backups/env-20261102-081500`、`backups/postgres-20261102-081500.sql`（约 125 MB）；
  - `git pull` 到 `d2b9592`，`.env` 末尾追加 Jellyfin 配置（`JELLYFIN_ENABLED`、`JELLYFIN_BASE_URL`、`JELLYFIN_DAILY_RUN_HOUR`、两个媒体根目录），API Key 暂未填；
  - 重建 `docker-app-1`，迁移 `20261101_0015 -> 20261101_0016` 成功，首页 200；
  - 新建 `/mnt/cache/docker1/jellyfin/{config,cache}`、`/mnt/cache/docker1/mediawarp-jellyfin/{config,logs}`；
  - `docker compose -p jellyfin up -d jellyfin` 启动 Jellyfin 10.10.7（8097），初始化向导尚未完成。
- 未做：MediaWarp-Jellyfin（等 API Key）、Lucky 外网入口、合集同步、播放验收。

## Testing

- 容器内跑一次真实扫描任务（约 409 秒）：
  - 本地 39800 个视频，37968 个匹配、1832 个未匹配；
  - 115 STRM 6895 个，全部未匹配，NFO 错误 0。
- 排查 STRM 全部未匹配：1198 个演员目录与 1557 个白名单关键词（含别名）无任何重合，忽略大小写和空格也是 0；NFO 正常含演员。结论是词库不含这些演员，不是程序错误。

## Notes

- 扫描整体约 7 分钟，主要耗在 disk2 上 4 万个文件；页面点「立即扫描」需要等这么久。
- Changed files：本日志；代码改动见提交 `d2b95921`。
- Rollback：
  - 18x：`.env` 用 `backups/env-20261102-081500` 还原，代码回到 `0146ff9`，重建容器；新表可保留（不影响旧功能），需要时用备份 SQL 还原；
  - Jellyfin：`docker compose -p jellyfin down`，删除 `/mnt/cache/docker1/jellyfin`、`/mnt/cache/docker1/mediawarp-jellyfin`。

---

# 续：API Key、媒体库、MediaWarp（同日，用户中途暂停）

## What was done

- 用户在 Jellyfin 完成初始化向导并生成 API Key（只写入生产 `.env` 的 `JELLYFIN_API_KEY` 和 MediaWarp 配置，不入库、不写文档）。
- 通过 API 建两个媒体库：
  - `115番号`：movies，路径 `302porn_tv1`，只读本地 NFO，无元数据和图片下载器；
  - `本地已整理`：homevideos，路径 disk2 已整理，无元数据下载器，图片只保留 Screen Grabber（本地截帧做封面）；
  - 两库都关闭：实时监控、章节图、Trickplay、保存 NFO、自动按 NFO 建合集。
- 「扫描媒体库」计划任务改为每天 02:30（原间隔触发已替换）；已手动触发首次扫库。
- 启动 `MediaWarp-Jellyfin`（MediaWarp 0.2.2，本地已有的 `akimio/mediawarp:latest`，与现有实例同一镜像），9002 正常。
- 重建（重启）`docker-app-1` 使 API Key 生效，首页 200。
- 外网入口 `https://jf18.wyichuan.cc:16666`（用户已在 Lucky 配好）返回 Jellyfin 信息，MediaWarp 访问日志可见经 Lucky 转发的请求。

## Testing

- API Key 校验 200；两库配置回读与设定一致。
- 首次扫库进行中（15% 时已入库 4070 部 115 影片）。本地机械盘较慢，用户决定不再等待，测试后自行告知。
- 302 未验证成功：扫库进行中对某个 115 影片取 `PlaybackInfo` / `Fields=MediaSources` 时 Jellyfin 返回 500（NullReferenceException），经 9002 取流也是 500。推测是入库未完成导致媒体信息不全，**待扫库完成后复测**，仍失败再排查。

## Notes

- 待办（新会话接着做）：
  1. 确认 Jellyfin 扫库完成（计划任务「扫描媒体库」Idle）；
  2. 复测 115 影片经 9002 是否 302（MediaWarp 日志），若仍 500 则排查 Jellyfin 10.10.7 与 STRM；
  3. 在 18x「Jellyfin」页面点「立即同步合集」，核对合集数量、冲突、待扫描数；
  4. 用户做播放验收矩阵（家里网页、外网网页、外网手机客户端 × 本地 / 115）；
  5. 验收后建议用户在 Jellyfin 里轮换 API Key（当前 Key 出现在聊天记录中），并同步更新 `.env` 与 MediaWarp 配置。
- 用户补充的后续方向已写入设计文档第十节（女优黑白名单、播放联动标记、联动删除；人物资料先调研现成库；115 目录树先用手动导出测试）。
- Rollback 补充：删除两个媒体库或整个 `/mnt/cache/docker1/jellyfin`；`docker compose -p jellyfin down` 同时停掉 MediaWarp-Jellyfin；`.env` 删除 `JELLYFIN_API_KEY` 行即可关闭同步（只保留扫描）。
