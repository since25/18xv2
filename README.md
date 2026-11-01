# 18x Organizer

115 文件整理、关键词管理、计划执行与登录保护一体化工具。

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
