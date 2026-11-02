# 2026-11-01 Jellyfin 的 MediaWarp 配置改为沿用现有实例

## What was done

- 按用户要求，把生产 `MediaWarp-Jellyfin` 的配置改为现有 Emby 实例配置的副本，只改 `server` 段的类型、地址和认证，然后重启容器（服务器时间 2026-11-02 09:43）。
- 同步仓库模板 `docker/jellyfin/mediawarp-config.example.yaml`：补上 OpenList 登录段（账号密码用占位符）。

## Testing

- 容器启动成功，上游为 Jellyfin（8097）。
- 手工请求 9002 取流：302 到 115 CDN。改配置前同样是 302。
- 经 9002 取播放信息：地址仍是内网 `192.168.70.138:5244`，`DirectStreamUrl` 仍为空，与改配置前相同。
- 外网客户端播放：待用户复测，尚未验证。

## Notes

- 改配置前的日志：外网 SenPlayer 和 Infuse 都取了播放信息，但都没有向 MediaWarp 取流。
- Changed files：`docker/jellyfin/mediawarp-config.example.yaml`、本日志。未提交。
- 生产配置备份：`/mnt/cache/docker1/mediawarp-jellyfin/config/config.yaml.bak-20261102-094305`。
- Rollback：用备份覆盖 `config.yaml`，执行 `docker restart MediaWarp-Jellyfin`。
