# 2026-11-25 Jellyfin 本地视频显示名：设计与实施计划

## What was done

- 和用户讨论 Jellyfin 联动的整体方向，定为三段：合集显示名 → 女优档案与联动删除 → fklema 扩展（接 Jellyfin、Mac 版、mpv 兜底）。本次只做第一段的设计和计划。
- 用户批准命名规则：本地视频显示为 `关键词/资源包 · 序号`，只改 Jellyfin 里的显示名并锁定，不动文件、目录、硬链接。
- 新增设计文档 `docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`。
- 新增实施计划 `docs/superpowers/plans/2026-11-25-jellyfin-display-names.md`（5 个任务：命名规则、客户端、同步服务、任务接入与命令行、部署试跑）。
- 讨论中的只读核查（生产，均未写入）：
  - Emby + IINA 媒体动作实际只用过一次：`emby_delete_plans` 1 条（2026-07-04，completed）、`emby_metadata_candidates` 1 条、`emby_media_mappings` 8 条。
  - 视频格式：本地约 4.1 万个，h264/hevc 的 mp4/mov 占 98.8%，约 500 个 mpeg4/av1；115 番号 6895 个，mp4 占 89%，mkv/wmv/avi/flv 共 758 个。
  - 本地路径层级：2 层 149、3 层 34200、4 层及以上 6747；3669 个目录中 2044 个不止一个视频，单目录最多 460 个。
  - mdc-ng 仓库只有说明和发布包，没有黑白名单功能，最后更新 2026-07。

## Testing

- 只写了文档，没有代码改动，未跑测试。

## Notes

- Changed files：
  - `docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`（新增）
  - `docs/superpowers/plans/2026-11-25-jellyfin-display-names.md`（新增）
  - 本日志（新增）
- 未提交。实施完成后，实施记录接着写在本日志里，随实施改动一起提交。
- Rollback：删除上述三个文件。

---

# 续：实施（同日，工作区 `.claude/worktrees/jellyfin-display-names`，分支 `worktree-jellyfin-display-names`，起点 `dcc2931f`）

## What was done

- 命名规则 `app/services/jellyfin/display_names.py`：按相对根目录路径取「关键词/资源包」分组，自然排序编号，位数随分组大小补零。
- Jellyfin 客户端新增：读取条目名字和锁定字段（`Fields=Path,Settings`）、改名并锁定 / 解锁、把合集设为按名字排序；分页逻辑抽成共用的私有方法，`iter_media_paths` 行为不变。
- 改名服务 `app/services/jellyfin/display_name_sync_service.py`：只改名字不对或没锁的条目；支持只预览、按关键词（规范名或别名）执行、回滚（改回文件名并解锁）；单条失败只计数；拿不到列表时不写任何东西。
- 后台任务 `jellyfin:names`，接在每日合集同步之后；新开关 `JELLYFIN_DISPLAY_NAMES_ENABLED`（默认关闭）。
- 手动命令 `scripts/jellyfin_display_names.py`（`--dry-run`、`--keyword`、`--restore`），结果写进后台任务记录并打印摘要。
- 文档：`docker/jellyfin/README.md` 新增「本地视频显示名」，`scripts/README.md`、`.env.example` 补充说明。
- 动手前对生产 Jellyfin 10.10.7 做了只读核对：列表带 `Fields=Settings` 会返回 `LockedFields`（当前都是空）；18x 合集有 `DisplayOrder` 字段，当前为 `PremiereDate`。

## Testing

- 基线（改代码前）：`scripts/remote-test.sh backend` → 718 passed。
- 新增测试均先确认失败再实现：命名规则 7 个、客户端 5 个、改名服务 12 个、任务接入 3 个。
- 实施完成时：`scripts/remote-test.sh backend` → 745 passed。
- 独立审查（Opus）结论"修完再合并"：无严重问题，4 个重要问题。修复（均先写失败测试）：
  - 连续 20 次写入 Jellyfin 失败就停止本轮并记为失败，避免 Jellyfin 挂掉时一轮拖上几天、挡住后续任务；
  - 拿不到 Jellyfin 列表、本地根目录没配置时，任务按失败收尾，不再显示"完成"；
  - 命令行有失败条目时返回非 0；按 Ctrl+C 中断时把任务记为失败，不会一直显示"运行中"；
  - NFO 风险只读核对：生产「本地已整理」库 `MetadataSavers: []`、`SaveLocalMetadata: false`，改名不会写 `.nfo`；已写进 README 前提和部署试跑检查步骤。
- 修复后：`scripts/remote-test.sh backend` → 752 passed（Spark，日志 `~/ci/18x_v2/jellyfin-display-names/.remote-test-logs/20261126-114128-backend.log`）。
- 命令行 `--help` 在本机能正常解析参数。生产上的真实改名还没做，按计划 Task 5 逐步批准。
- 审查提出的 9 个小问题暂缓（多根目录同名合并编号、`--keyword` 不过滤停用关键词、长时间运行无进度输出等），记录在工作区台账里，需要时再做。

## Notes

- Changed files（实施部分）：
  - 新增：`app/services/jellyfin/display_names.py`、`app/services/jellyfin/display_name_sync_service.py`、`scripts/jellyfin_display_names.py`、`tests/jellyfin/test_display_names.py`、`tests/jellyfin/test_display_name_sync.py`、`tests/jellyfin/test_display_names_cli.py`
  - 修改：`app/services/jellyfin/client.py`、`app/services/jellyfin/job_runner.py`、`app/core/config.py`、`tests/jellyfin/test_client.py`、`tests/jellyfin/test_job_runner.py`、`.env.example`、`docker/jellyfin/README.md`、`scripts/README.md`
- 工作区里的 `.venv` 是指向主仓库 venv 的软链，只为远程测试复刻依赖，不提交。
- 未部署。部署和试跑（只预览 → 单关键词 → 用户验收 → 重扫保持 → 全量 → 开每日开关）每一步都要用户批准。
- Rollback：代码未合并时删除工作区和分支即可；部署后先把开关改回 `false` 并重建 18x，再执行 `docker exec docker-app-1 python scripts/jellyfin_display_names.py --restore`，最后把代码回退到 `dcc2931f` 重建。不需要数据库回滚（没有新表和字段）。
