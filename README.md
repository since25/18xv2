# 18x Organizer

115 文件整理、关键词管理、计划执行与登录保护一体化工具。

## RN 下载器资源包集成

18x_v2 可以把 RN 服务器上的 Telegram 下载器作为外部执行节点：同步下载器已经扫描好的资源包，用 18x 的白名单/别名匹配标题并用黑名单排除；用户在“下载器资源包”页面确认候选后，才会按明确的资源包 ID 创建下载批次。18x 会保存候选、提交记录和任务/文件进度，并提供暂停、恢复、取消和重试入口。

在 `.env` 中配置：

```dotenv
DOWNLOADER_ENABLED=true
DOWNLOADER_BASE_URL=http://rn-server:5000
DOWNLOADER_PASSWORD=下载器 Web 登录密码
DOWNLOADER_NODE_KEY=rn
DOWNLOADER_TIMEOUT_SECONDS=10
DOWNLOADER_SYNC_INTERVAL_SECONDS=60
```

未启用或未配置地址时，后台不会连接 RN，也不会自动创建下载任务。启用后后台只同步资源包和任务状态；下载仍需在 18x 页面人工确认。
