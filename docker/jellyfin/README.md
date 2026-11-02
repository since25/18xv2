# Jellyfin 第一版部署说明

设计依据：`docs/superpowers/specs/2026-11-01-jellyfin-v1-design.md`。本目录与 18x 主 compose、现有 Emby 和 MediaWarp（9001）完全独立，启停互不影响。

## 组成

| 容器 | 宿主机端口 | 作用 |
|---|---|---|
| `jellyfin` | 8097 | 媒体库与播放，只读挂载媒体目录 |
| `MediaWarp-Jellyfin` | 9002 | 播放 115 STRM 时 302 到 115 直链 |
| `jellyfin-playback-rewrite` | 9003 | 改写播放信息后转发给 MediaWarp，Lucky 外网入口指向这里 |

## 为什么需要 9003

STRM 里是内网 OpenList 地址。Emby 的播放信息带 `DirectStreamUrl`，客户端会走 MediaWarp；Jellyfin 的播放信息没有这个字段，客户端（已确认 SenPlayer、Infuse）直接连内网地址，外网起不了播。

9003 只改写 `/Items/{id}/PlaybackInfo` 的响应：把内网 OpenList 地址换成当前访问地址下的 `/Videos/{id}/stream`，同时填上 `DirectStreamUrl`。其余请求（含本地影片取流和 WebSocket）原样转发，视频流量仍由 115 直连客户端。

## 部署步骤（每一步都需要先经用户批准）

1. 建配置目录：`/mnt/cache/docker1/jellyfin/{config,cache}`、`/mnt/cache/docker1/mediawarp-jellyfin/{config,logs}`。
2. 先只启动 `jellyfin`，在网页端完成初始化并建两个媒体库（见下方清单）。
3. 在 Jellyfin 控制台「API 密钥」中生成一个 Key：
   - 填进 MediaWarp 配置：把 `mediawarp-config.example.yaml` 复制为 `/mnt/cache/docker1/mediawarp-jellyfin/config/config.yaml`，再填 `auth`；
   - 填进 18x 的生产 `.env`：`JELLYFIN_API_KEY`。
4. 启动 `MediaWarp-Jellyfin`。
5. 18x 的 `.env` 增加以下配置，然后重建 18x 容器（主 compose 已加两条只读挂载）：
   - `JELLYFIN_ENABLED=true`
   - `JELLYFIN_BASE_URL=http://<内网>:8097`
   - `MEDIA_LIBRARY_LOCAL_ROOTS=/mnt/disk2/qbbtdn/已整理`
   - `MEDIA_LIBRARY_STRM_ROOTS=/mnt/user/docker1/alist-strm/video/302porn_tv1`
6. 把 `playback-rewrite/` 下的文件复制到 `/mnt/cache/docker1/jellyfin-playback-rewrite/`，启动 `jellyfin-playback-rewrite`。
7. 在 Lucky 新增外网入口，指向 9003，并转发原始 Host 和 `X-Forwarded-Proto`。
8. 在 18x 的「Jellyfin」页面依次点「立即扫描」「立即同步合集」。

## Jellyfin 媒体库设置清单

两个库通用：

- 关闭所有在线元数据下载器和图片下载器；
- 关闭「将媒体图像保存到媒体文件夹」和「NFO 保存」；
- 定时扫描设为每天 02:30（在 01:01 移盘脚本之后、18x 03:00 同步之前）。

各库单独设置：

- **115 番号**：库路径只填 `/mnt/user/docker1/alist-strm/video/302porn_tv1`，元数据读取器启用本地 NFO。**不要加 `porn_tv1`**，否则约 6300 个视频会重复。
- **本地已整理**：库路径填 `/mnt/disk2/qbbtdn/已整理`。库类型以"不联网识别、标题用文件名、可按文件夹浏览"为准，实测后选定。

## 验收矩阵

| 场景 | 本地视频 | 115 STRM |
|---|---|---|
| 家里网页端 | 能播 | 能播 |
| 外网网页端 | 能播 | 能播，并在 9003 和 MediaWarp 日志里看到 302 |
| 外网手机客户端（由用户指定一款） | 能播 | 能播，并确认是 302 |

另外两项检查：

- 部署前后对比，Emby 的配置目录和 STRM 目录没有任何文件变化；
- Jellyfin 没有往媒体目录写入任何文件。
