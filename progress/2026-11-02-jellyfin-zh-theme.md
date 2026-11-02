# 2026-11-02 Jellyfin 扫描核对、中文与皮肤

## What was done

- 确认首次扫描已完成：「扫描媒体库」计划任务状态 Completed，结束于 18:50（北京时间）。
- 给生产 Jellyfin 换上 ElegantFin v25.10.27，去掉 Google 字体和图标外链，写死的英文改成中文。
- 服务器语言已是 zh-CN，未改；网页端按浏览器语言显示。
- 发现 710 个未带 18x 管理标签的合集，18x 同步记录为 0，其中 674 个与关键词同名。未处理，等用户决定。

## Testing

- 115：磁盘 6895 个 STRM，入库 5526 部影片；1014 个目录是多文件（分段或多版本）。有 3 个目录没有对应影片，31 个多文件目录未完全体现。
- 本地：磁盘 39800 个视频，入库 39785 个，差 15 个，未逐个查原因。
- 皮肤：内网和外网入口的 `/Branding/Css` 与文件一致；外网登录页显示新皮肤和中文标题。
- 未验证：登录后的首页、详情页、播放页显示（需要用户登录）。

## Notes

- Changed files：`docker/jellyfin/theme/ElegantFin-v25.10.27-zh.css`、`docker/jellyfin/README.md`、本日志。未提交。
- 生产改动：Jellyfin 品牌配置；`/mnt/cache/docker1/jellyfin/theme/` 下的皮肤和备份。
- Rollback：把 `/mnt/cache/docker1/jellyfin/theme/branding-backup-20261102.json` 的内容提交到 `POST /System/Configuration/branding`。
- 合集来源未确认：创建时间集中在 09:57–09:59，与扫描开始时间接近，18x 没有对应记录。
