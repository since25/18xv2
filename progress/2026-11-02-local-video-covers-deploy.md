# 2026-11-02 新视频封面功能上线

## What was done

- 合并到 `main` 并推送（`b65a2852`），生产机构建新镜像后替换 18x 容器。
- 用新 compose 重建 Jellyfin 容器，中文字体改为正式只读挂载；其他容器未动。
- 18x 的 `已整理` 挂载改为可写，Jellyfin 仍为只读。
- 生产 `.env` 增加 `JELLYFIN_COVER_SINCE=2026-11-02T23:14:35+08:00`，功能开启，每天 02:00 运行。

## Testing

- 构建：退出码 0，最低可用内存 3770MB，最高负载 2.98，镜像 819MB。
- 开启前核对：磁盘 39800 个视频全部有 18x 记录，首晚候选数 0。
- 手动运行一次任务：耗时 37.8 秒，候选 0，生成 0，已有视频跳过 39800，失败 0；没有新增封面或残留临时文件。
- 容器：18x 首页 200，Jellyfin 健康，封面循环已启动，媒体库封面 200，容器内有字体和 ffmpeg。
- 未验证：真实新视频的完整流程（封面生成、属主、Jellyfin 显示、不被收成照片、后补封面何时生效）。需要等下一批新视频。

## Notes

- 待办：下一批新视频入库后，查看 `jellyfin:covers` 任务摘要和 Jellyfin 显示。
- 待办：核对今晚 02:30 扫描和 03:00 同步（修复后首次自动运行）。
- 部署时检查脚本因容器重启时 curl 连接被重置而提前退出，配置已写入且未重复，之后补做了检查。
- Changed files：本日志；代码和文档见 `b65a2852`。worktree `local-video-covers` 保留。
- 生产 `.env` 备份在 `/mnt/user/docker1/18xv2/backups/env-*`。
- Rollback：
  - 只关功能：删除 `.env` 的 `JELLYFIN_COVER_SINCE` 后执行 `docker compose -f docker/docker-compose.yml up -d --no-build app`；
  - 回退代码：回到 `f497544f` 重建 18x。已生成的 `*-poster.jpg` 不会自动删除。
