# 2026-11-12 下载器同步降频 / 低优先级词不进待确认

## What was done

- 资源包同步间隔默认 60 秒 → 6 小时（`DOWNLOADER_SYNC_INTERVAL_SECONDS=21600`），代码默认值、`.env.example`、README、开发指南一起改。
- 同步循环改为「启动先跑一轮，再按间隔睡」；远端失败时 5 分钟内重试，不再等满一个周期。
- 下载器白名单匹配跳过 `merge_policy=fallback_only` 的低优先级词：这类词只服务整理任务，不生成待确认候选；每轮同步末尾再兜底清理这类词留下的 pending/selected 候选（覆盖关键词中途改档、资源包已下架的情况）。
- 关键词页的整理优先级说明同步改写，写明低优先级不进下载器待确认。
- 提交：`3adb0faa`（主改动）、`84dde77a`（兜底清理）。

## Deploy

- Unraid：`git pull --ff-only`，`.env` 中 `DOWNLOADER_SYNC_INTERVAL_SECONDS` 由 60 改为 21600（原文件备份 `.env.bak.20261112203254`），`docker compose -f docker/docker-compose.yml up -d --build app` 重建容器。
- 健康检查 `/healthz` 200，容器 Up，启动日志无 error/traceback。

## Testing

- Spark：后端 `467 passed`；前端 `89 passed`，build 通过。lint 仍有 2 个既有错误（`EmbyMediaActionsPage.tsx`、`ReviewIntakePage.tsx`），与本次改动无关。
- 线上：重启后资源包同步立即跑一轮（run 5423，25,786 包，0 新候选）；到 21:05 未出现第二轮，旧节奏此时应已跑过 2 轮，确认 6 小时间隔生效。
- 任务进度同步未改动，仍在 15 秒节奏运行。
- 低优先级词候选：125 → 0（118 条随资源包匹配清理，7 条由兜底清理），待确认总数 4,301 → 4,176。

## Notes

- 无数据库迁移，纯代码 + 配置改动。
- 回滚：revert 上述两个提交，`.env` 恢复备份后重建 app 容器；低优先级候选会在下一轮同步按旧规则重新生成。
- 手动同步入口不变，仍在下载器页头「同步资源包」。
