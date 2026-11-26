# 2026-11-01 下载器失败原因与同步改动上线（RN + 18x）

## What was done

- 推送到 GitHub：
  - 18x：`05aa29d7`（功能）、`9d5d5422`（进度日志）。
  - RN：`f246bba`。
- RN（rn 服务器）：
  - 部署前用 SQLite 在线备份了 `channel_library.sqlite3` 和 `web_tasks.sqlite3`，放在 `backups/deploy-20261101-channel-errors/`，两份都通过 integrity_check。
  - 确认没有进行中的下载批次，也没有扫描任务。
  - checkout 从 `3fad1b5` 切到 `f246bba`，重启 `tg-downloader.service`。
- 18x（Unraid）：`git pull --ff-only`，然后重建 app 容器。

## Testing

- RN：
  - 服务状态 active，`channel_libraries` 已自动补上 `last_error` 和 `last_error_at` 两列。
  - 启动日志中没有 error，`/login` 返回 200。
- 18x：
  - 容器正常运行，`/healthz` 返回 200。日志显示两个同步循环已分开启动，没有出现 sync failed。
  - 频道名回填：211 个任务快照中，还有 11 个没有频道名。这 11 个任务在 RN 那边已被清除，同步不会再访问它们。其余都已补齐，包括涩涩合集群的失败任务。
  - 资源包同步一轮从 270～560 秒降到 121 秒，原因是复用了登录。
  - RN 资源包载荷已带上失败原因，涩涩合集群的失败包是 `not_found`。目前带失败原因的资源包按原因统计：download_failed 91、cancelled 38、not_found 9、upload_failed 3 等。
  - `channel_last_error` 目前还是空的。要等今晚零点的扫描，或者对该频道再次发起下载，才会被标记。

## Notes

- Changed files：本日志。代码改动见 `progress/2026-11-01-downloader-errors-sync.md` 和 RN 的 `progress.md`。
- Rollback：
  - RN：`git checkout 3fad1b5`，然后重启服务。必要时先停服务，再从上面的备份目录恢复数据库。
  - 18x：revert `05aa29d7`，然后重建容器。
