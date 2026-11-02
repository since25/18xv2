# 2026-11-02 Jellyfin 合集同步修复与空合集清理

## What was done

- 查明 710 个未受管合集由 18x 同步产生：读取单个条目时没带用户，Jellyfin 10.10.7 返回 400，打标签失败且映射未保存；这些合集全部为空。
- 修复同步：
  - 读取单个条目和合集成员时带管理员用户；
  - 拿不到影片列表时停止同步；
  - 没有已入库影片的关键词不建空合集；
  - 打标签失败时保留映射（状态 `untagged`），下次补标签；
  - 新建合集时成员分批写入，避免请求地址超长。
- 服务器元数据设置中，合集关闭 TMDb 的资料和图片下载。影片类型不变。
- 部署提交 `97f5c777`、`f497544f`。
- 备份后删除 710 个空合集，再做首次全量同步。

## Testing

- Spark 全部后端测试：445 passed。新增测试先确认失败，修复后通过。
- 生产冒烟（临时合集）：新建、打标签、回读、读成员、移除、删除都正常。
- 删除前逐个确认无标签、无成员、路径在合集目录；删除后合集 0 个，影片数 5526 不变。
- 首次全量同步：耗时 649 秒，新建 710，加入成员 38811，冲突 0，错误 0。
- 同步后核对：710 个合集全部带 `18x-managed`，无 TMDB 信息，无空合集，无重名；抽查影片数前 3 的合集与 18x 记录一致。
- 第二次全量同步：耗时 561 秒，新建、改名、删除、增减成员、冲突、错误全部为 0。

## Notes

- 待匹配 1384 条（115 1369、本地 15）。115 差值与分段、多版本合并的差值相同，推测是这些文件没有独立条目，未逐条确认。
- 同步耗时主要在读列表：完整读取约 8 分钟，单页约 4 秒且与每页大小基本无关。未优化。
- Changed files：`app/services/jellyfin/client.py`、`app/services/jellyfin/collection_sync_service.py`、`tests/jellyfin/test_client.py`、`tests/jellyfin/test_collection_sync.py`、`docker/jellyfin/README.md`、`docker/jellyfin/theme/ElegantFin-v25.10.27-zh.css`、本日志。
- 生产备份（`/mnt/cache/docker1/jellyfin/theme/`）：`system-config-backup-20261102.json`、`collections-backup-20261102.tgz`、`collections-deleted-20261102.json`。
- Rollback：
  - 代码回退到 `b907e0ff` 后重建 18x；
  - 元数据设置：把 `system-config-backup-20261102.json` 提交回 `POST /System/Configuration`；
  - 合集：删除带 `18x-managed` 标签的合集并清空 `jellyfin_keyword_collections`。旧的 710 个空合集没有恢复价值。
