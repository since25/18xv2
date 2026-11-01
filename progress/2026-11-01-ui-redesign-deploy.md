# 2026-11-01 整站重设计与下载器双流改造上线

## What was done

- 将 `worktree-ui-redesign`（`1ba1ee2e`）快进合并进 `main`，并合并 p115client 间接依赖锁定修复（`f343408e`），合并提交为 `0f9f5679`，已推送到 GitHub。
- 合并修复的原因：生产 Dockerfile 先 COPY 代码、后 `pip install`，代码有任何变动都会全新解析依赖；不锁定的话，`python-asynctools` 0.2.x 会导致 p115client 无法导入。
- 生产服务器执行了 `git pull --ff-only`，然后 `docker compose -f docker/docker-compose.yml up -d --build app`。容器启动时自动执行了迁移 `20261031_0014 -> 20261101_0015`。

## Testing

- 部署前，在 Spark 上用 Python 3.12 从 `pyproject.toml` 全新安装（模拟生产构建）：`import p115client` 成功，后端 pytest 380 passed。
- 部署后：
  - `docker-app-1` 正常运行，`/api/healthz` 返回 200。
  - `alembic current` 为 `20261101_0015 (head)`。
  - 容器内 `from p115client import P115OpenClient` 成功。
  - 启动日志中没有 error 或 traceback。
- 回填结果：`downloader_task_snapshots` 共 208 行，208 行有开始时间和完成时间，201 行有字节数；另外 7 行是没有文件明细的旧任务。

## Notes

- Changed files：本文件（部署记录）。代码改动见 `progress/2026-11-01-ui-redesign-downloader.md` 和 `progress/2026-11-01-p115client-deps.md`。
- 备份：生产服务器上的 `data/backup_20261101_before_ui_redesign.sql`（117M，pg_dump 完整结束）。
- Rollback：
  1. 在服务器上 `git checkout bfba5b7`（或 revert `0f9f5679`、`1ba1ee2e`）。
  2. 在容器内执行 `alembic downgrade 20261031_0014`。
  3. 重建 app 容器。
  4. 必要时用上面的备份恢复数据库。
- 部署后需要在浏览器按 Cmd+Shift+R 强制刷新。
