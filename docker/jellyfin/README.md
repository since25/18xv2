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

- 只读本地：关闭所有在线元数据下载器和图片下载器，也关闭 Screen Grabber 等容器内截图（缺封面由 18x 负责）；
- 关闭「将媒体图像保存到媒体文件夹」和「NFO 保存」；
- 定时扫描设为每天 02:30（在 01:01 移盘脚本之后、18x 03:00 同步之前）。

服务器元数据设置：合集（BoxSet）关闭 TMDb 的资料和图片下载，否则 18x 按关键词建的合集会被错误改名、换封面。影片类型不受影响。

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

## 界面语言与皮肤

- **语言**：服务器默认语言已是 `zh-CN`。网页端按浏览器语言显示，也可在每台设备的「设置 → 显示 → 显示语言」选「汉语 (简体字)」；手机和电视客户端用各自的语言设置。
- **皮肤**：`theme/ElegantFin-v25.10.27-zh.css`，由 ElegantFin v25.10.27（GPL-2.0）改成不依赖外部网络，中文字体用系统无衬线字体，写死的英文改成中文。升级 Jellyfin 大版本前要重新检查兼容性。
- **应用方式**：把文件内容写入 Jellyfin「品牌」配置的自定义 CSS（`POST /System/Configuration/branding`），立即生效，不用重启。皮肤只影响网页端，Infuse、SenPlayer 等客户端不受影响。
- **中文字体**：官方镜像没有中文字体，服务器生成媒体库封面时中文会变成方块。部署前把文泉驿字体放到 `/mnt/cache/docker1/jellyfin/fonts/wqy-zenhei.ttc`，compose 会只读挂载。已有的错误封面要删除旧图后刷新媒体库才会重新生成；**不要用 `MetadataRefreshMode=FullRefresh`**，它会把库里的视频重新读取一遍。
- **还原**：把 `/mnt/cache/docker1/jellyfin/theme/branding-backup-20261102.json` 的内容提交回同一接口。

## 新视频封面

- Jellyfin 不生成封面。18x 每天 02:00 给新入库的本地视频生成 `<视频名>-poster.jpg`，放在视频旁边，02:25 后不再开始新视频；没做完或失败的第二天继续。
- 配置在 18x 的 `.env`：`JELLYFIN_COVER_SINCE`（上线时间，带时区；为空时功能关闭）、`JELLYFIN_COVER_RUN_HOUR`、`JELLYFIN_COVER_DEADLINE_MINUTE`。
- 只处理上线时间之后出现的视频，已有视频和已有封面不动。18x 的 `已整理` 挂载因此可写，Jellyfin 仍是只读。

## 本地视频显示名

- **规则**：本地已整理库的视频在 Jellyfin 里显示为 `序号 · 关键词/资源包`（直接放在关键词下的显示为 `序号 · 关键词`），同一资源包按文件名自然排序编号。另写入强制排序名 `关键词/资源包 · 序号`（数字补零），合集仍一个包一个包地按序号排列。详见 `docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`。
- **只改 Jellyfin 数据库**：通过接口改名字并锁定名字字段，文件、目录、硬链接都不动；115 番号库不处理。18x 合集同时设为按名字排序。
- **开关**：18x `.env` 的 `JELLYFIN_DISPLAY_NAMES_ENABLED=true` 时，每天合集同步之后自动执行（默认关闭）。
- **读取范围**：全量只读「本地已整理」这一个库（按 `MEDIA_LIBRARY_LOCAL_ROOTS` 对应的库位置找库；找不到时退回读全部）；`--keyword` 只读该关键词的 18x 合集成员（没有合集时退回读本地库）。每页条数 `JELLYFIN_DISPLAY_NAMES_PAGE_SIZE`（默认 5000）、超时 `JELLYFIN_DISPLAY_NAMES_TIMEOUT_SECONDS`（默认 30 秒），与合集同步的 `JELLYFIN_PAGE_SIZE` 分开。2026-11-26 实测：读全部条目每页 500 条约 5 秒、全库约 9 分钟；只读本地库每页 5000 条约 3.6 秒、全库约 35 秒。
- **手动命令**（在生产机执行，不受开关限制）：
  - 只预览：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --dry-run`
  - 只改一个关键词：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --keyword <名字>`
  - 全量：`docker exec docker-app-1 python scripts/jellyfin_display_names.py`
  - 回滚（名字改回文件名、清掉强制排序名并解锁，可加 `--keyword`）：`docker exec docker-app-1 python scripts/jellyfin_display_names.py --restore`
- **前提**：「本地已整理」库的元数据保存器必须为空、不保存本地元数据（`GET /Library/VirtualFolders` 里 `MetadataSavers: []`、`SaveLocalMetadata: false`；2026-11-25 已核对）。否则 Jellyfin 改名时会尝试往视频旁写 `.nfo`。
- **出错时**：连续 20 次写入 Jellyfin 失败会停止本轮并记为失败（多半是 Jellyfin 重启或卡住），恢复后重新运行即可；命令行在有失败条目时返回非 0；按 Ctrl+C 中断会把任务记为失败，不会挡住下一次运行。
- **回滚顺序**：先把开关改回 `false` 并重建 18x，再执行回滚命令，否则第二天又会改回来。回滚把名字改成「文件名去掉扩展名」，个别名字可能和 Jellyfin 原来自动起的名字略有不同；合集的排序方式不会改回。**不要用 `MetadataRefreshMode=FullRefresh`**。
