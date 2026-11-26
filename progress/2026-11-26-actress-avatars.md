# 2026-11-26 女优头像：从 Gfriends 拉取并上传 Jellyfin 人物主图（实施，未上线）

设计见 `docs/superpowers/specs/2026-11-26-actress-avatars-design.md`，计划见 `docs/superpowers/plans/2026-11-26-actress-avatars.md`，使用说明见 `docs/actresses.md`「头像」一节。在主工作区 `main` 上实施（用户同意），起点 `164ed1e4`。

## What was done

- 背景：女优档案的 1570 人和 Jellyfin 115 库的 2081 个人物都没有头像。试过 MDC-NG 自带的女优模块，它在 Jellyfin 上只能列出 10 个人物，不可用。用户选定由 18x 自己拉头像。上线前只读抽样：1346 人（86%）能在 Gfriends 匹配到，按片数加权 95%。
- **数据**：`actresses` 表加 `avatar_state` / `avatar_source` / `avatar_note` / `avatar_checked_at` 四列，迁移 `20261126_0020`。
- **找图**（`app/services/actresses/gfriends.py`）：
  - Gfriends 官方索引缓存 7 天，下载失败时沿用旧缓存；
  - 只按完整名字精确匹配，兼容 `-数字` 和「A（B）」两种写法；同名时取排序最前的来源目录；
  - 可经 MDC 对照表 `mapping_actor.xml` 把中文名换成日文名再查；
  - 下载限 30 秒、只收图片、最大 5MB。
- **贴图**（`app/services/actresses/avatar_service.py`）：
  - 用规范名和别名查 Jellyfin 人物，只给没有主图的人物上传；
  - Jellyfin 客户端新增 `get_person` 和 `upload_person_image`（`POST /Items/{id}/Images/Primary`，请求体为 base64）；
  - 逐人提交，每张图之间间隔 0.5 秒；
  - 「找不到」和「没有这个人物」7 天后重查，「已上传」和「本来就有」不回查；
  - 合并、加别名、删别名后，状态重置为待处理。
- **任务**：
  - 新任务 `actress:avatars`，接在每日链「女优刷新」之后；新开关 `ACTRESS_AVATARS_ENABLED`，默认关闭；每次处理上限 `ACTRESS_AVATARS_PER_RUN`，默认 300；
  - 手动接口 `POST /api/actresses/avatars/refresh`，可选 `actress_ids`、`limit`，只要求女优功能开启、Jellyfin 已配置；
  - 配了对照表却读不到时，在摘要 `name_map_note` 和日志里写明。
- **接口和页面**：
  - 头像接口改为规范名取不到时再按别名取；
  - 女优详情返回头像状态；
  - 女优页加「补头像」按钮，详情里显示头像状态，并加「重新找头像」按钮。
- **部署配置**：`docker/docker-compose.yml` 把 MDC 数据目录 `/mnt/user/docker1/mdc_ng/data` 只读挂到 `/app/mdc`。
- **文档**：更新 `docs/actresses.md`（「头像」一节、配置表、头像上线步骤、回退）和 `.env.example`；设计稿状态改为「已实施（待上线）」。

## Testing

- 按计划 7 个任务依次实施，每个任务都先写测试、确认失败，再实现、确认通过（各任务的 Spark 日志见 `~/ci/18x_v2/18x_v2/.remote-test-logs/`）。
- 新增测试：
  - `tests/actresses/test_gfriends.py`、`tests/actresses/test_avatar_service.py`；
  - `tests/jellyfin/test_client.py`：查人物、上传；
  - `tests/actresses/test_routes.py`：手动接口、详情字段、按别名取图；
  - `tests/actresses/test_job_runner.py`：开关、参数、对照表读不到时的提示；
  - `tests/jellyfin/test_job_runner.py`：每日链顺序；
  - `tests/actresses/test_archive_service.py`：名字变化后重置；
  - `tests/actresses/test_models.py`、`tests/test_migrations.py`：0020 的升级和降级；
  - 前端 `ActressesPage.test.tsx` 新增 3 条。
- 终审：请了一个独立评审看全部改动，没有 Critical 问题，有 3 条 Important：
  - 配了对照表却读不到时完全静默：已修复，先补测试、确认失败，再修复后通过；
  - compose 单文件挂载在文件缺失时会在 MDC 目录里建出空目录：已改为只读挂整个目录；
  - Jellyfin 上传格式依赖服务端版本：上线步骤里加了「在 Jellyfin 网页上亲眼确认图片正常」。
- 最终全量（Spark）：
  - 后端：`scripts/remote-test.sh backend` 退出码 0，1008 passed，3 warnings，日志 `20261126-220736-backend.log`；
  - 前端：`scripts/remote-test.sh frontend` test 退出码 0（164 passed），build 0，lint 0，日志 `20261126-215926-frontend.log`。之后没有再改前端代码。
- 没有对真实的 Gfriends 下载过图片，也没有对真实的 Jellyfin 上传过；上线步骤 2 验证。

## Notes

- Changed files：
  - 新增：`alembic/versions/20261126_0020_actress_avatars.py`、`app/services/actresses/gfriends.py`、`app/services/actresses/avatar_service.py`；
  - 修改：`app/models/actresses.py`、`app/core/config.py`、`app/schemas/actresses.py`、`app/api/routes/actresses.py`、`app/services/actresses/archive_service.py`、`app/services/actresses/job_runner.py`、`app/services/jellyfin/client.py`、`app/services/jellyfin/job_runner.py`；
  - 前端：`frontend/src/api/actresses.ts`、`frontend/src/pages/ActressesPage.tsx`，以及生成的 `frontend/openapi.json`、`frontend/src/api/schema.gen.ts`；
  - 部署与配置：`docker/docker-compose.yml`、`.env.example`；
  - 测试：上面列出的文件；
  - 文档：`docs/actresses.md`、设计稿、实施计划、本日志。
- 暂缓的小问题（终审 Minor，没修）：
  - 「A（B）」和「-数字」写法与原名同等优先，跨来源目录时可能抢占；
  - 任务运行中改名或合并，重置的待处理状态可能被任务写回覆盖；
  - 失败状态没有退避，永久性错误会每天重试；
  - 图片地址没有逐段编码，文件名含 `#` 或 `%` 时会下载失败；
  - 头像接口按别名回退会增加请求，Jellyfin 宕机时列表页会变慢；
  - 任务进度一直显示 0/0；
  - 每日链里头像步骤会把后面的合集同步顺延几分钟；
  - 索引缓存损坏且未过期时，任务最多连续失败 7 天；
  - 点了「重新找头像」后，详情不会自动刷新。
- 上线（每步由用户批准）：
  1. 部署代码（带迁移，开关关闭），配置 `ACTRESS_AVATAR_NAME_MAP=/app/mdc/mapping_actor.xml`；
  2. 用 1 个人验证上传，并在 Jellyfin 网页上亲眼确认图片正常；
  3. 再试 3 个人；
  4. 打开 `ACTRESS_AVATARS_ENABLED`。
- Rollback：先在新代码上执行 `alembic downgrade 20261126_0019`，删掉头像的四列；再把代码回退到 `164ed1e4` 重建。已经传进 Jellyfin 的人物图不会自动删除。
