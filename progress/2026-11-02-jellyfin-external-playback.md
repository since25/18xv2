# 2026-11-02 Jellyfin 115 影片外网播放修复

## What was done

- 定位根因：Jellyfin 的播放信息只有内网 OpenList 地址，`DirectStreamUrl` 为空，客户端直接连内网地址，不经过 MediaWarp。
- 新增改写层 `jellyfin-playback-rewrite`（nginx + njs，9003）：只改写 `/Items/{id}/PlaybackInfo` 中的内网 OpenList 地址，其余请求原样转发。
- 用户把 Lucky 入口 `jf18.wyichuan.cc:16666` 从 9002 改到 9003。
- 同步 `docker/jellyfin/docker-compose.yml` 和 `docker/jellyfin/README.md`。

## Testing

- 根因证据：家里播放时 OpenList 日志有局域网设备的直连请求；外网两次失败都没有取流请求。
- 模拟请求：单版本和多版本 115 影片均 302 到 115；本地影片不改写，取流 206；普通接口和 WebSocket 转发正常。
- 外网实测（用户确认能播）：PlaybackInfo 200 → `/Videos/{id}/stream` 302（来源 116.237.191.254）→ 上报开始播放。OpenList 同时段没有客户端直连。
- 未验证：外网 Infuse、外网网页端、外网本地影片。

## Notes

- 生产容器目前由 `docker run` 启动，未使用仓库 compose。之后用 compose 启动时，需先删除同名容器。
- 生产配置文件在 `/mnt/cache/docker1/jellyfin-playback-rewrite/`，不随 `git pull` 更新。
- 令牌只出现在给客户端的播放地址和 MediaWarp 访问日志里；9003 的日志不记录查询参数。
- Changed files：`docker/jellyfin/playback-rewrite/nginx.conf`、`docker/jellyfin/playback-rewrite/rewrite.js`、`docker/jellyfin/docker-compose.yml`、`docker/jellyfin/README.md`、本日志。未提交。
- Rollback：Lucky 改回 9002，然后 `docker rm -f jellyfin-playback-rewrite`。
