# 2026-11-27 女优删片清理配套文件：部署与补清首删批次

实施记录见 `progress/2026-11-27-actress-leftover-cleanup.md`。

## What was done

- 分支 `claude/actress-leftover-cleanup` 快进合并进 `main`（`b3adf884` 功能、`9c7cec65` 首删日志），推送到 GitHub。
- 部署前只读检查生产机：代码 `887eb64`，没有执行中的后台任务。没有数据库迁移，没做备份。
- 部署命令（`git pull` + 重建 `docker-app-1`）由用户本人在终端执行（本机安全钩子会拦截）。
- 经用户批准，用补跑脚本清理首删批次（批次 1，RED-163）：
  - 预览：`python scripts/actress_clean_leftovers.py --batch 1` → 115 目录 1 个、本地目录 1 个，都是整目录删除；
  - 执行：加 `--apply` → 两个目录都已删除（115 进回收站）。

## Testing

- 部署后：生产代码 `9c7cec6`；容器运行中，重启 0 次；容器内 `/healthz` 200；`alembic current` 仍是 `20261126_0020 (head)`；启动后 10 分钟内日志没有 ERROR / Traceback；容器里有新脚本。
- 清理后只读核对：
  - 115：按路径查这个目录返回空结果，已不在；
  - OpenList：上级目录 `201-250` 共 49 项，里面没有 RED-163；
  - 本地：`porn_tv1/XXX_SERIES/201-250` 从 50 项变成 49 项，RED-163 目录已不存在；
  - 批次记录：新增 `remote_leftover`、`source_leftover` 各一行，状态都是已删除，没有错误。

## Notes

- Changed files：本日志（新增）。
- 待办：2026-11-28 再看一次 RED-163 有没有「删了又回来」（alist-strm / OpenList）。
- Rollback：代码回退到 `887eb64` 并重建容器（没有迁移）。被清理的 115 目录可以从回收站还原；本地 4 个配套文件已删除，不能还原。
