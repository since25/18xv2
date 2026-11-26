# 2026-11-01 收件箱行内下载 / 未命中视图上线（18x）

## What was done

- 推送 `0146ff9d` 到 GitHub main。
- Unraid：`git pull --ff-only`（9d5d542 → 0146ff9），重建 app 容器。本次无数据库迁移，未做备份。

## Testing

- 容器正常运行，`/healthz` 200，启动日志无 error / traceback。
- 容器内只读调用 `list_inbox`：待确认 3945、未命中 21978、已忽略 0；返回条目带 `boundary_status`。
- 路由表包含新接口 `/downloader/packages/download`。
- 未在生产实际提交「未命中」资源包下载（会触发远端下载器），留给用户在页面上试一两个包。

## Notes

- Changed files：本日志。代码改动见 `progress/2026-11-01-downloader-inbox-actions.md`。
- Rollback：revert `0146ff9d`，服务器 `git pull` 后重建 app 容器；无数据需要回滚。
