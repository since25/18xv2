# 2026-11-28 NFO 重新翻译：简介去番号上线

改了什么、怎么测的，见 `progress/2026-11-28-nfo-retranslate-plotnum-fix.md`。用户先说「合并并推送」，然后自己在终端执行了部署。

## What was done

- 合并：本地 main 从 `83a6adb1` 快进到 `2b22061b`，带上 `a64263b1`、`04f058c3`、`2b22061b` 三个提交，没有生成合并提交。这一步由主目录会话完成；合并前主目录没有未提交文件，推送前检查过新增的日志里没有密钥。
- 推送：`origin/main` 推到 `83a6adb1..2b22061b`，没有强推。
- 部署：用户执行 `git pull` 和 `docker compose -f docker/docker-compose.yml up -d --build app`，`docker-app-1` 已重建并启动。
- 这次没有数据库迁移，也没有改 `.env` 和 docker 配置。

## Testing

- 合并前，同一个提交在 Spark 上跑了全量后端测试：1137 passed，18 warnings。
- 部署后的只读检查：
  - 生产代码在 `2b22061`；
  - 容器在运行，重启 0 次；
  - 容器内 `/healthz` 返回 200；
  - 容器里的 `scripts/nfo_retranslate.py` 已包含简介去番号的那一行；
  - 启动后 10 分钟内的日志里，没有 error、traceback 或 exception；
  - 没有在跑的翻译脚本。

## Notes

- Changed files：只有本日志。生产机只换了代码。
- 还没做：补翻跳过的 78 部和全量运行里失败的字段。141 个超过 60 字的标题怎么处理，等用户定。
- Rollback：生产代码回到 `83a6adb` 并重建容器。没有迁移；这次也没有写过 NFO。
