# 2026-11-02 新入库本地视频封面（18x 生成）

## What was done

- 由 Codex（gpt-6-astra）在 worktree `worktree-local-video-covers` 开发，Claude 写任务书和验收，返工两轮。
- 新增 `app/services/jellyfin/cover_service.py`：取 12 帧，过滤过暗、过亮、单调、模糊的帧，选最清晰的一张；全被过滤时退回 50% 处；写入 `<视频名>-poster.jpg`，不覆盖已有文件。
- 新增独立每日任务（默认 02:00，02:25 后不再开始新视频），任务类型 `jellyfin:covers`；配置 `JELLYFIN_COVER_SINCE`、`JELLYFIN_COVER_RUN_HOUR`、`JELLYFIN_COVER_DEADLINE_MINUTE`。上线时间为空时功能关闭。
- Dockerfile 增加 ffmpeg；compose 中 18x 的本地视频目录改为可写。

## Testing

- Spark 全部后端测试：464 passed。
- 真实 ffmpeg 处理合成视频（前 2 秒黑屏）：生成 720x406 的封面，权限 664，目录里没有残留临时文件，再次运行跳过，未覆盖。
- 未验证：生产环境镜像构建、属主设置、Jellyfin 读取封面、Jellyfin 是否把封面收成照片、已入库视频后补封面何时生效。

## Notes

- 验收时修正：逐像素 Python 计算改用 Pillow 的 C 实现；截止时间改成绝对时刻；临时文件改用短名；候选按路径排序。
- 上线前要核对首晚候选数：路径不在 18x 记录里的文件都会被当成新视频。
- 视频被单独删除或移动时，旁边的封面会留下，第一版不清理。
- Changed files：`.env.example`、`app/core/config.py`、`app/main.py`、`app/services/jellyfin/cover_service.py`、`app/services/jellyfin/job_runner.py`、`docker/Dockerfile`、`docker/docker-compose.yml`、`tests/jellyfin/test_cover_service.py`、`tests/jellyfin/test_job_runner.py`、本日志。未提交，未部署。
- Rollback：放弃此分支即可，线上未改动。上线后清空 `JELLYFIN_COVER_SINCE` 并重启 18x 即可关闭功能。
