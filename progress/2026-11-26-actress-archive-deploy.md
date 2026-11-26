# 2026-11-26 女优档案：合并与部署（开关保持关闭）

实施记录见 `progress/2026-11-26-actress-archive.md`，上线清单见 `docs/actresses.md`「上线检查清单」。

## What was done

- 分支 `claude/magical-morse-7b759f`（`636bd2ed`..`d7c41195`，30 个提交）快进合并进 `main`；另把主工作区里 8 份未提交的旧日志（11-01 至 11-25）单独提交为 `df4b23ee`，一并推到 GitHub。
- 部署前在生产机备份 organizer 库：`/mnt/user/docker1/18xv2/data/backup_20261126_before_0019.sql`（202M，pg_dump 正常结束）。
- 生产机拉取 `df4b23ee` 并重建 `docker-app-1`（部署命令被本机安全钩子拦截，由用户本人在终端执行）。容器启动时 alembic 从 `20261125_0018` 升到 `20261126_0019`。
- `ACTRESS_*` 四个配置项都没有写进生产 `.env`，`ACTRESS_ENABLED` 为默认的关闭：每日任务不跑女优步骤，女优写接口返回 409。
- 合并后删除本地分支 `claude/magical-morse-7b759f` 和它的工作区（远端没有这个分支）。工作区里未提交的 5 张讨论用示意图 `visuals/actress-*.svg` 在清理前已不知去向，全盘未找到，未恢复；正式设计与计划文档不受影响。

## Testing

- 合并前代码的全量测试见实施记录（Spark：后端 931 passed，前端 161 passed、build、lint 通过）。
- 生产部署后核对（2026-11-26 19:50 CST 左右）：
  - 生产机代码 `df4b23e`；`docker-app-1` 运行中，重启次数 0；
  - `alembic current` → `20261126_0019 (head)`；
  - 迁移的 10 张表都已建出（`actresses`、`actress_aliases`、`actress_marks`、`jellyfin_media_actors`、`actress_delete_candidates`、`actress_kept_films`、`actress_delete_batches`、`actress_delete_batch_films`、`actress_delete_batch_files`、`jellyfin_actress_collections`），新表为空；
  - 容器内 `/healthz` 200，宿主 `8010` 首页 200；接口文档里有 18 个 `/actresses` 路径；
  - 容器内读到的 `actress_enabled` 为 `False`；
  - 启动后日志里没有 ERROR / Traceback。
- 没有在浏览器里看过新页面，也没有调用任何女优写接口。

## Notes

- Changed files：本日志（新增）。代码改动见实施记录。
- 下一步：按上线清单第 1～6 条只读核对生产数据和外部服务，结果出来前不配置 `ACTRESS_*`、不开开关、不删任何文件。
- Rollback：
  - 停用：现在本来就是关闭状态，无需操作。
  - 回退代码：先在新代码上 `docker exec docker-app-1 alembic downgrade 20261125_0018`（删除女优相关的 10 张表，目前都是空的），再把生产机代码切回 `15129fa` 重建容器；必要时用上面的备份恢复整库。
