# 18x Organizer

115 文件整理、关键词管理、计划执行与登录保护一体化工具。

## Jellyfin 关键词合集

18x_v2 只读扫描本地「已整理」目录和 MDC 刮削后的 115 STRM（`302porn_tv1`），按白名单关键词精确匹配（本地按顶层目录名，`甲__乙` 组合目录拆成多个关键词；115 侧先按 NFO 演员名，未命中再按目录名），再通过 Jellyfin API 为每个关键词维护一个带 `18x-managed` 标签的合集。没有这个标签的合集一律不改。播放 115 内容时，由独立的 MediaWarp 实例 302 到 115 直链。部署步骤见 `docker/jellyfin/README.md`。

在 `.env` 中配置：

```dotenv
JELLYFIN_ENABLED=true
JELLYFIN_BASE_URL=http://jellyfin:8096
JELLYFIN_API_KEY=在 Jellyfin 控制台生成
MEDIA_LIBRARY_LOCAL_ROOTS=/mnt/disk2/qbbtdn/已整理
MEDIA_LIBRARY_STRM_ROOTS=/mnt/user/docker1/alist-strm/video/302porn_tv1
JELLYFIN_DAILY_RUN_HOUR=3
```

只开 `JELLYFIN_ENABLED` 时只能扫描；同步合集还需要地址和 API Key。根目录不存在或为空时，扫描会直接失败，不会把已有条目标为失效。

## RN 下载器集成

18x_v2 把 RN 服务器上的 Telegram 下载器作为外部执行节点，下载器页面采用“候选收件箱 + 任务看板”双流模型。候选收件箱用于按白名单/别名筛选资源包、确认下载或忽略候选；忽略操作提供 5 秒原地撤销，长期回溯可切换到已忽略视图。任务看板集中展示进行中任务与历史任务，点击任务会在侧边检查抽屉中查看文件进度、失败项和任务详情。资源包的每个 `index_revision` 都会单独生成候选；确认新版本时，RN 只提交此前完整成功版本中没有出现过的媒体。18x 会保存候选、提交记录和任务/文件进度，并提供暂停、恢复、取消和重试入口。

在 `.env` 中配置：

```dotenv
DOWNLOADER_ENABLED=true
DOWNLOADER_BASE_URL=http://rn-server:5000
DOWNLOADER_PASSWORD=下载器 Web 登录密码
DOWNLOADER_NODE_KEY=rn
DOWNLOADER_TIMEOUT_SECONDS=10
DOWNLOADER_SYNC_INTERVAL_SECONDS=60
DOWNLOADER_TASK_SYNC_INTERVAL_SECONDS=15
```

未启用或未配置地址时，后台不会连接 RN，也不会自动创建下载任务。启用后后台只同步资源包和任务状态；下载仍需在 18x 页面人工确认。旧 RN 客户端省略下载模式时仍使用完整下载模式，18x 集成使用 `mode=incremental`。
