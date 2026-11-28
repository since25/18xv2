# 2026-11-28 NFO 重新翻译：番号重复修复上线

修复内容和验证记录在 `progress/2026-11-28-nfo-retranslate-fix-deploy.md` 的「修复：标题里番号重复」一节。用户依次说了「合并并推送」，然后自己在终端执行了部署命令。

## What was done

- 合并：本地 main 从 `b0fdd838` 快进到 `83a6adb1`，没有生成合并提交。这一步由主目录会话完成，合并前主目录没有未提交的文件。
- 推送：`origin/main` 从 `b0fdd838` 推到 `83a6adb1`，没有强推。
- 部署：用户执行 `git pull` 加 `docker compose -f docker/docker-compose.yml up -d --build app`，`docker-app-1` 已重建并启动。
- 这次没有数据库迁移，也没有改 `.env` 和 docker 配置。

## Testing

- 合并前，同一个提交在 Spark 上跑过全量后端测试：1136 passed，18 warnings。
- 部署后的只读检查：
  - 生产代码在 `83a6adb`；
  - 容器在运行，重启 0 次；
  - 容器内 `/healthz` 返回 200；
  - 启动后 10 分钟内的日志里，error、traceback、exception 都是 0 行。
  - 在容器里直接调用新的 `strip_num`：
    - `FC2-4343195 FC2-PPV-4343195 【無修正】x` 去掉后剩 `【無修正】x`；
    - `ABC-1234 y` 在番号是 `ABC-123` 时保持原样。

## 写回 20261128-140251（第一次改生产 NFO）

用户原话：「按照你的推荐写回」。推荐的做法是跳过 FC2-4343195 和 JUVR-068，其余全部写回。

### What was done

- 先建了跳过名单 `data/nfo_retranslate/skip-20261128-140251.txt`（容器内路径），里面是两个番号：
  - FC2-4343195：用修复前的代码翻的，标题写回后番号会重复；
  - JUVR-068：简介把意思译反了。
- 执行 `apply --run 20261128-140251 --skip data/nfo_retranslate/skip-20261128-140251.txt`，汇总如下：
  - 写入 25 个 NFO，共 18 部片（有多段片）；
  - 跳过名单挡下 2 个；
  - 翻译失败不写的 0 个；
  - 文件被改动或读写出错的 0 个；
  - Jellyfin 刷新 18 个条目，0 个失败；
  - 另有 7 个 NFO「找不到条目」。
- 那 7 个「找不到条目」都是多段片的后几段：DTCVR-002 的 cd2、cd3，FC2-1751110 的 cd2，FC2-2543627 的 cd2，IPVR-055 的 cd1–cd3。
  - 在 18x 的 Jellyfin 记录里，这些段都没有自己的条目 ID。Jellyfin 把它们并到了第一段的条目下，例如 DTCVR-002 的条目显示分 3 段、FC2-1751110 显示分 2 段。
  - IPVR-055 在 Jellyfin 里只有一个条目，对应 `IPVR-055.strm`。
  - 所以 18 部片在 Jellyfin 里都已刷新，没有漏掉。

### Testing

只读抽查：

- NFO 内容：
  - REBD-695 的标题是「REBD-695 Remu5 诱惑的海边·凉森玲梦」，简介结尾是「由 qwen38 提供翻译」；
  - FC2-1751110-cd2 的标题保留了 ` cd2` 后缀；
  - IPVR-055-cd3 的标题和简介都已写入。
- Jellyfin 条目：REBD-695、DTCVR-002（简介）、FC2-1751110（标题）、FC2-2543627、IPVR-055 的名称和简介，都已经是新译文。

### Notes

- 写进去的译文里有几处已知的小毛病，是用户按推荐接受的：
  - FC2-1751110 的标题结尾被截断，成了「…当场生中」；
  - IPVR-055 的简介有一两处生硬。
- Rollback：执行 `restore --run 20261128-140251`。
  - 它会用 `data/nfo_retranslate/20261128-140251/backup/` 里的备份还原这次写入的 25 个 NFO，然后刷新 Jellyfin。
  - 写入之后又被改过的文件会跳过，不会覆盖。

## Notes

- Changed files：只有本日志。生产机上除了换代码，还多了跳过名单文件，以及这次运行的 `apply.jsonl` 和 `backup/`，另外改了 25 个 NFO。跨运行的写入记录 `applied.jsonl` 也追加了这次写入的内容。
- Rollback：
  - 代码：生产代码回到 `b0fdd83`，然后重建容器。
  - NFO：见上面的 `restore`。
