# 2026-11-26 女优删片 OpenList 刷新：部署（开关仍关闭）

改动内容见 `progress/2026-11-26-actress-openlist-refresh.md`（提交 `b0f5bfcd`）。

## What was done

- 把 `main`（`b0f5bfcd`）推到 GitHub。部署命令被本机安全钩子拦截，由用户本人在终端执行：拉取代码并重建 `docker-app-1`。
- 本次没有数据库迁移，没有改生产 `.env`：`ACTRESS_ENABLED` 仍关闭，`OPENLIST_URL` / `OPENLIST_TOKEN` 都没配置（删除后不会刷新）。

## Testing

- 部署后核对（2026-11-26 20:31 CST 左右）：
  - 生产机代码是 `b0f5bfc`；`docker-app-1` 在运行，重启次数 0；
  - `alembic current` 是 `20261126_0019 (head)`，没有变化；
  - 容器内 `/healthz` 返回 200，宿主 `8010` 首页返回 200；
  - 接口文档里已有 `openlist_dir` 分组和 `refreshed` 状态，`app.services.actresses.openlist` 能正常导入；
  - 容器内 `actress_enabled` 为 False，OpenList 未配置；
  - 启动后日志里没有 ERROR 或 Traceback。
- 部署前的 Spark 全量测试见改动日志。

## Notes

- Changed files：本日志（新增）。
- 下一步：写入 `ACTRESS_*` 和 `OPENLIST_*` 配置，打开开关（需用户批准），再做首次真实删除（只删 1 部）。
- Rollback：生产机代码切回 `df4b23e`，重建容器。没有迁移要回退。
