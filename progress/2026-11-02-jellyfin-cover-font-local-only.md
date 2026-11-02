# 2026-11-02 Jellyfin 媒体库封面中文与只读本地策略

## What was done

- 查明媒体库封面上的方块：官方镜像没有中文字体，服务器生成封面时无法绘制中文。
- 把主机的文泉驿字体放到 `/mnt/cache/docker1/jellyfin/fonts/`，复制进运行中的容器后重启 Jellyfin，并在 compose 增加只读挂载（未提交，线上尚未用新 compose 重建）。
- 挪走 3 张旧封面并刷新媒体库。`115番号`、`本地已整理` 封面已重新生成。
- 按用户策略关闭 `本地已整理` 的 Screen Grabber；两个媒体库现在都不在线下载，也不在容器内截图。

## Testing

- 下载新封面查看：`115番号`、`本地已整理` 中文显示正常。
- `合集` 媒体库封面返回 404：旧封面已挪走，新封面未生成。
- 刷新结束后：三个库都 Idle，影片数 5526，合集 710 个全部带标签且非空，Jellyfin 健康，负载从约 35 回落到约 7。

## Notes

- 失误：刷新时用了 `MetadataRefreshMode=FullRefresh`，虽然 `Recursive=false`，仍把本地库约 2.8 万个视频重新读取，负载一度约 35，整体约 50 分钟。已写入部署说明，避免再用。
- 过程中有 848 次截帧相关日志，部分本地封面可能被重新截取；刷新后抽样 800 个中 786 个有封面（抽样在 Screen Grabber 关闭前）。
- 新入库的本地视频在 18x 截图上线前没有封面。
- Changed files：`docker/jellyfin/docker-compose.yml`、`docker/jellyfin/README.md`、`docs/superpowers/specs/2026-11-01-jellyfin-v1-design.md`、`AGENTS.md`、本日志。未提交。
- 生产备份（`/mnt/cache/docker1/jellyfin/theme/`）：`library-covers-backup-20261102/`、`virtualfolders-backup-20261102.json`。
- Rollback：把 `virtualfolders-backup-20261102.json` 中 `本地已整理` 的选项提交回 `POST /Library/VirtualFolders/LibraryOptions`；旧封面放回 `/mnt/cache/docker1/jellyfin/config/metadata/library/` 对应目录。容器内字体在重建前一直有效，不影响其他功能。
