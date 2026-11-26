# 2026-11-26 女优档案 + 黑白名单 + 115 联动删除：实施

工作区 `.claude/worktrees/magical-morse-7b759f`，分支 `claude/magical-morse-7b759f`，起点 `a0977f3b`（设计与计划文档 `636bd2ed`..`275c0595`，实施 `17da845e`..本次文档提交）。设计见 `docs/superpowers/specs/2026-11-25-actress-archive-design.md`，计划见 `docs/superpowers/plans/2026-11-25-actress-archive.md`，使用说明见 `docs/actresses.md`。

## What was done

- **数据表与迁移**：新增女优档案、别名、标记记录、片子演员、待删清单、保留名单、删除批次（批次 / 片子 / 文件三层）、白名单女优合集共 10 张表，迁移 `20261126_0019`（上一个是 `20261125_0018`）。
- **扫描**：Jellyfin 每日扫描时把每个 115 STRM 条目 NFO 里的演员名单存下来（原样名 + 归一化名，每次整体重算）；归一化后为空的名字跳过，超长名字截到 255 字。
- **女优档案**：新名字自动建档为未标、重算片数；改状态（来源网页 / 播放器 / 导入 / 合并，记标记记录）；别名增删（全体唯一）；合并（一黑一白拒绝）。名字比对在关键词归一化基础上再去掉空格。女优名不写关键词库。
- **删片规则与待删清单**：应删 = 有黑名单演员、没有受保护演员、没标保留、片子有效。受保护 = 档案白名单，或演员名（能对上档案时也比她的规范名和全部别名）命中启用中的 `whitelist` / `emby_whitelist` 关键词。清单在改状态、改别名、合并、撤销保留、每日任务时重算；勾选、保留、撤销保留；「检查 115」只读查看能否解析。
- **删除批次**：按 115 原文件 → `porn_tv1` STRM → `302porn_tv1` 番号目录的顺序逐部片执行，前一步失败就停在这部片；每个 115 文件删成功立刻落库，续跑不重删。新写删除守卫 `FilmDeleteGuard`（不改 Emby 的 `PathGuard`）：`porn_tv1` 下只删 `.strm`，`302porn_tv1` 下只删恰好两层的番号目录和变空的演员目录，路径经过链接一律拒绝。删掉片子后触发 Jellyfin 115 番号库的普通扫描（Default 模式，非全量刷新）。
- **白名单合集**：每个白名单女优一个带 `18x-managed` 标签的 Jellyfin 合集，接在关键词合集同步之后；与关键词合集或手工合集同名时只报告冲突；移出白名单后清空并删除。
- **任务与开关**：总开关 `ACTRESS_ENABLED`（默认关闭），另有 `ACTRESS_SOURCE_ROOT`、`ACTRESS_ORGANIZED_ROOT`、`ACTRESS_PATH_MAP`。每日链变为：扫描 → 女优刷新（`actress:refresh`）→ 合集同步（含女优合集）→ 显示名同步。删除任务 `actress:delete` 同一时间只跑一个。
- **接口**：`/actresses` 下的列表、详情、改状态、别名、合并、头像（转发 Jellyfin 人物图片）、按片查演员（给播放器，返回 `media_item_id`）、刷新、待删清单、保留名单、删除批次（建、查、续跑）。
- **旧 Emby 名单导入**：`scripts/actress_import_emby_lists.py`，默认只列出，`--apply` 才写。
- **前端**：「流程」导航下新增「女优」和「女优删除」两页；重新生成前端接口类型。
- **文档**：新增 `docs/actresses.md`；设计文档状态改为「已实施（待上线）」，5.4 补一句确认删除的实施时改动。
- **终审修复**：18x 重启时把执行中 / 待开始的删除批次标为中断（备注「服务重启时中断」），页面上可点「重试失败的」续跑；执行前删除根目录还要可写，否则整批失败、不调 115；换算后的 STRM 本身是符号链接、或番号目录里有扫描之后新加的 STRM 分段时，这部片判失败，不调 115；`porn_tv1` 里按地址找不到 STRM 时记一条已不存在的文件行；合并确认框显示选中时的目标名（之后再搜别的名字也不变），并说明对方是未标时会继承她的黑 / 白名单状态；建删除批次请求在途时女优删除页的勾选和按钮一律不可点；文档改正：收紧 `MISSING_MARKERS` 是首次真实删除前的硬性前提。

实施中相对设计 / 计划的改动（都已写进 `docs/actresses.md`）：

- 「确认删除」只删页面上当时勾选的那份清单（确认框里的 N 部就是这些片子，请求带 `film_dirs`），不按服务端存的勾选去删；清单在此期间有变化时提示「清单有变化，请刷新后再确认 / 请重新确认」，一部都不删。页面同步中（勾选写库、清单重拉、检查 115、保留）禁用勾选与确认。
- 受保护除了档案白名单，也包括 NFO 演员名或其档案规范名 / 别名命中启用中的 `whitelist` / `emby_whitelist` 关键词。
- 删一部片前先用删除守卫规则核对本地番号目录（必须在 `302porn_tv1` 可写根下恰好两层、不经过链接、真实存在）和 STRM 位置，不合格这部片一个 115 文件都不删。
- 115「已不存在」只认中文「不存在」，其余报错（含英文 not found）一律当失败、本地不删。
- `MEDIA_LIBRARY_STRM_ROOTS` 没配置时，刷新档案、重算清单、合集同步等都拒绝执行、不改数据。
- 旧 Emby 名单导入不覆盖档案里已有的相反状态，列为冲突。
- 按片查演员返回 `media_item_id`；功能关闭时写接口（含按片查演员，它会当场建档）返回 409，读接口照常。
- 待删清单的「115 能否解析」改为按钮触发（一次最多 50 部），不在列表加载时逐部查 115。

## Testing

- 各任务按测试先行实施，每个任务完成后都经过独立审查，修复项先补失败测试再改。
- 全部文件和外部服务用夹具和假客户端：文件系统用临时目录，115 用假客户端 / 桩客户端，Jellyfin 用假客户端和 httpx 模拟传输；夹具只用「甲」「乙」「ABC-001」这类占位。
- 最终全量（Spark，当前提交 `5d0bd5b7` 的代码，加本次文档改动），依次各跑一次：
  - `scripts/remote-test.sh backend` → 退出码 0，925 passed，18 warnings，用时约 3 分钟。18 个警告都是既有的、与本功能无关：`StarletteDeprecationWarning` ×16（`fastapi/testclient.py` 提示改用 httpx2）、alembic `path_separator` 的 `DeprecationWarning` ×2。日志 `~/ci/18x_v2/magical-morse-7b759f/.remote-test-logs/20261126-173720-backend.log`。
  - `scripts/remote-test.sh frontend` → test 退出码 0（31 个测试文件、159 passed），build 退出码 0，lint 退出码 0。build 只有既有的 Vite 打包体积提示（chunkSizeWarningLimit）。日志 `~/ci/18x_v2/magical-morse-7b759f/.remote-test-logs/20261126-174035-frontend.log`。
  - 已知偶发问题：`MagnetTasksPage.test.tsx` 偶尔报「window is not defined」让 vitest 退出码为 1，是既有问题、与本功能无关；本次全量没有出现。
- 终审修复后再跑全量（Spark，依次各一次）：`scripts/remote-test.sh backend` → 退出码 0，931 passed，18 warnings（同上，都是既有的），日志 `~/ci/18x_v2/magical-morse-7b759f/.remote-test-logs/20261126-180340-backend.log`；`scripts/remote-test.sh frontend` → test 退出码 0（161 passed），build 0，lint 0，日志 `~/ci/18x_v2/magical-morse-7b759f/.remote-test-logs/20261126-180649-frontend.log`。每个修复项都先补测试、确认失败后再改。
- 迁移只在 SQLite 上测过（`tests/test_migrations.py` 升降级），PostgreSQL 上要部署时确认。
- 生产上没有做任何操作：没部署、没开开关、没删过任何真实文件。

## Notes

- Changed files：
  - 数据表 / 迁移：`app/models/actresses.py`（新增）、`alembic/versions/20261126_0019_actresses.py`（新增）、`alembic/env.py`
  - 服务：`app/services/actresses/`（新增：`__init__.py`、`archive_service.py`、`candidates_service.py`、`collection_sync.py`、`delete_batch_service.py`、`delete_guard.py`、`emby_import.py`、`films.py`、`job_runner.py`、`names.py`、`remote_115.py`、`rules.py`）
  - 接口 / 模型：`app/api/routes/actresses.py`（新增）、`app/schemas/actresses.py`（新增）、`app/main.py`
  - 扫描：`app/services/jellyfin/scan_service.py`
  - Jellyfin 客户端 / 任务链：`app/services/jellyfin/client.py`、`app/services/jellyfin/job_runner.py`
  - 配置：`app/core/config.py`、`.env.example`
  - 脚本：`scripts/actress_import_emby_lists.py`（新增）
  - 前端：`frontend/src/App.tsx`、`frontend/src/layout/navigation.tsx`、`frontend/src/api/actresses.ts`（新增）、`frontend/src/pages/ActressesPage.tsx`（新增）、`frontend/src/pages/ActressDeletePage.tsx`（新增）
  - 测试：`tests/actresses/`（新增 15 个文件）、`tests/conftest.py`、`tests/jellyfin/test_client.py`、`tests/jellyfin/test_job_runner.py`、`tests/jellyfin/test_scan_service.py`、`tests/test_migrations.py`、`frontend/src/pages/ActressesPage.test.tsx`（新增）、`frontend/src/pages/ActressDeletePage.test.tsx`（新增）
  - 生成的接口类型：`frontend/openapi.json`、`frontend/src/api/schema.gen.ts`
  - 文档：`docs/actresses.md`（新增）、`docs/superpowers/specs/2026-11-25-actress-archive-design.md`、`docs/superpowers/plans/2026-11-25-actress-archive.md`、本日志（新增）
- 未部署、未合并。上线按 `docs/actresses.md` 的「上线检查清单」逐项找用户批准：只读统计生产数据并核实路径换算和 115 报错文本 → 备份数据库后部署、配置并打开开关 → 首次真实删除只删 1 部 → 首删之后再导入旧 Emby 名单。
- 已知遗留的小问题（审查时记下、暂缓）：
  - 女优功能开着而 `MEDIA_LIBRARY_STRM_ROOTS` 没配置时，女优合集同步报错会让整个合集同步任务记为失败（关键词合集已先同步完），更合适的做法是只记进摘要；
  - 删除批次：删完番号目录、还没落库时进程被杀，续跑会判「本地目录不存在」失败（次日扫描后这部片失效，会被跳过并移出清单）；
  - 女优页：合并搜索没有防抖，每次搜索都会读全清单；
  - 女优删除页：批次详情轮询出错一次就停；
  - 迁移只在 SQLite 上验证过。
- Rollback：
  - 只想停用：把 `ACTRESS_ENABLED` 改回 `false` 并重建 18x 容器让配置生效，不动代码和库。每日链不再跑女优步骤，删除接口返回 409。
  - 要回退代码：`docker/entrypoint.sh` 在 `set -e` 下先执行 `alembic upgrade head`，库已在 `20261126_0019` 时先换回旧代码会让容器起不来。必须先在新代码上把迁移降到 `20261125_0018`（删掉女优相关全部表和数据，先备份），再把代码回退到 `a0977f3b` 重建。
  - 已删的 115 文件只能从 115 回收站找回（前提是删除进了回收站）；本地 STRM 和番号目录由 alist-strm 和 MDC 按 115 目录重新生成。
