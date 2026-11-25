# 2026-11-25 脚本中心第一段：执行框架 + sehuatang

## What was done

- 设计和计划：`docs/superpowers/specs/2026-11-25-scripts-into-18x-design.md`（已批准）、`docs/superpowers/plans/2026-11-25-script-jobs-p1-framework-sehuatang.md`。
- 分支 `feat/script-jobs`（独立工作区 `.claude/worktrees/script-jobs`），从 `main` 的 `0c21cfaf` 分出。未合并、未推送、未部署。
- 后端：
  - 迁移 `20261125_0018`：`script_runs` 加 `trigger`、`dry_run`、`log_path`、`error_reason`、`pid`，结束时间和退出码改为可空；新表 `script_job_configs`（三条默认配置，执行方都是 unraid，与 Unraid 现状一致）、`script_job_config_changes`、`sehuatang_posts`。
  - 执行器：每次运行一个独立子进程（自成进程组）。支持同组互斥排队、停止（SIGTERM，30 秒后 SIGKILL）、超时、重启后结束残留进程并标“已中断”。被停止或打断时，从逐帖进度文件找回已做的部分。
  - 调度：每分钟检查一次，预定时间后 2 小时内补跑；手动运行和演练不影响定时；预定时间之后才改的配置当天不补跑。日志保留 30 天。
  - sehuatang：重写为仓库内模块。标题用 18x 黑名单过滤（NFKC、去空格、不分大小写），已提交过的帖子跳过，检查种子内文件名，通过 qB 接口提交（不再写监视目录），能识别 cookie 失效。站点 cookie 和 User-Agent 在页面设置（文件 0600，不回显），qB 凭证走 `.env`。
  - 接口：`/script-jobs`（列表、修改、修改记录、手动运行、站点会话），`/script-runs/{id}/stop`、`/script-runs/{id}/log`；“今日状态”改按配置表判断，删除 `SCRIPT_REPORT_SCHEDULES`。
  - 切换用的导入脚本 `scripts/seed_sehuatang_posts.py`：导入最近 14 天 CSV 里的帖子编号。
- 前端：「脚本日报」扩展为「脚本中心」，包括脚本卡片（立即运行、演练、停止、看日志、设置）、设置抽屉（含站点 cookie）、实时日志、cookie 失效红条，运行记录加演练和手动标记。
- 文档：新增 `docs/script-jobs.md`（使用说明、sehuatang 切换运行手册、回滚），更新 `docs/unraid-script-reports.md`。
- 最终审阅：4 个重要问题已修复，分别是日志超过 64KB 被截断、停止或中断后丢失已提交记录、回滚顺序和降级残留、切换后立即补跑。12 个小问题暂缓，见 Notes。

## Testing

- 全部在 Spark 上通过 `scripts/remote-test.sh` 运行。
- 基线：后端 540 passed。
- 最终：`scripts/remote-test.sh all` → 后端 686 passed，前端 140 passed，build 和 lint 通过。
- 有一个真实子进程冒烟测试：从运行目录启动 sehuatang 子进程，没有 cookie 时以“尚未设置站点 cookie”结束，不访问网络。
- 未做：
  - 浏览器里实际查看页面。
  - 在 PostgreSQL 上实跑迁移（只在 SQLite 上测过）。
  - 对真实站点和真实 qB 联调。
  - 任何生产操作。

## Notes

- 暂缓的小问题：
  - 重启回收只发 SIGTERM，没有升级到 SIGKILL。
  - 不能在 18x 执行的脚本（MOVE、DEL）仍显示“演练”按钮。
  - 日志读取失败一次就不再重试。
  - qB 失败时，红条仍提示去换 cookie。
  - 红条在一次停止或中断后就消失。
  - 日志被 30 天清理后，日志页签显示报错。
  - 日志里有坏字节时，汉字边界处理有小缺陷。
  - 配置修改记录没有记录操作人。
  - 开发库并发首次访问时，可能出现一次 500。
  - 5 秒轮询不刷新趋势图。
  - 补跑窗口不跨午夜。
  - 迁移需要在 PostgreSQL 上验证。
- 生产切换（8 个 AI 词预估和加词、部署、填 qB 凭证、设置 cookie、导入帖子编号、演练对比、停 Unraid 定时）按 `docs/script-jobs.md` 的手册逐步做，每一步都要用户批准。
- 第二段（MOVE）和第三段（DEL 和 docker 挂载）的计划，等 sehuatang 切换稳定后再写。
- Changed files：
  - `alembic/versions/20261125_0018_script_jobs.py`
  - `app/models/script_runs.py`
  - `app/schemas/script_runs.py`、`app/schemas/script_jobs.py`
  - `app/services/script_jobs/**`
  - `app/api/routes/script_runs.py`、`app/api/routes/script_jobs.py`
  - `app/main.py`、`app/core/config.py`
  - `pyproject.toml`、`.env.example`
  - `scripts/seed_sehuatang_posts.py`
  - `frontend/src/api/{client,scriptJobs,scriptRuns}.ts`、`frontend/src/pages/ScriptRunsPage*.tsx`、`frontend/src/pages/scriptCenter/*`、`frontend/src/layout/navigation.tsx`
  - `frontend/openapi.json`、`frontend/src/api/schema.gen.ts`
  - `docs/script-jobs.md`、`docs/unraid-script-reports.md`
  - 设计、计划文档
  - `tests/**` 中对应测试
- Rollback：
  - 未部署时，删除分支即可。
  - 部署后：先用新版本容器执行 `alembic downgrade 20261102_0017`，再回退代码版本（见 `docs/script-jobs.md`）。
