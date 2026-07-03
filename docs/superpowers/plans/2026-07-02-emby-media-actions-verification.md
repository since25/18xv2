# Emby Media Actions Verification

## 验证范围

本文件记录 `emby_media_actions` 分支的本地验证结果，以及部署到 Unraid / Emby / IINA 链路前需要确认的配置。

验证目标：

- IINA / helper 只提交当前播放上下文，不直接删除文件，不直接写黑白名单。
- 后端为删除动作生成 draft plan；真实删除必须通过 Web UI 二次确认。
- 115 网盘原文件删除只走 18x_v2 内已有的 115 OpenAPI client。
- 电影、单集、整季、整剧范围都通过后端 mapping 和 Web UI 选择生成计划。
- 演员黑白名单候选先保存 Emby/NFO 快照，再由 Web UI 选择演员并写入 `emby_blacklist` 或 `emby_whitelist`。

## 本地验证结果

执行环境：

- Worktree: `/Users/wangyichuan/Desktop/wangcodemac/18x_v2/.worktrees/emby-media-actions`
- Branch: `codex/emby-media-actions`
- Python: `.venv/bin/python`
- Pytest: `.venv/bin/pytest`
- Frontend: `cd frontend && npm run build`

已执行命令：

```bash
.venv/bin/pytest tests/emby_media_actions tests/api/test_emby_media_actions_routes.py -v
.venv/bin/pytest tests/services/test_review_intake_service.py tests/api/test_review_intake_routes.py tests/dedupe/test_delete_plan_service.py -v
cd frontend && npm run build
git diff --check
```

结果：

- `tests/emby_media_actions` + `tests/api/test_emby_media_actions_routes.py`: 81 passed, 1 existing Starlette/httpx deprecation warning.
- `review_intake` + `dedupe` related regression suite: 12 passed, 1 existing Starlette/httpx deprecation warning.
- Frontend build: passed.
- `git diff --check`: passed.

已知非阻断项：

- Vite 报告主 bundle 超过 500 kB。
- 早前 `npm ci` 报告 7 个 audit vulnerabilities，未在本任务内处理。
- Starlette/httpx deprecation warning 来自现有 TestClient 依赖组合。

## 必需环境变量

生产环境建议值：

```bash
EMBY_MEDIA_ACTIONS_ENABLED=true
EMBY_BASE_URL=http://192.168.70.138:8096
EMBY_API_KEY=<keep-out-of-git>
EMBY_USER_ID=<emby-user-id>
EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=true
```

`EMBY_USER_ID` 用于后端配置化 Emby client 的用户级 item 查询。`EMBY_API_KEY` 必须保留在 `.env` / secret 中，不提交到仓库。

`EMBY_MEDIA_ACTIONS_ENABLED=false` 时，`/emby-media-actions/*` 路由会返回 disabled，不再接收 IINA 或 Web UI 请求。

`EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=true` 时，删除计划仍可生成和查看，但 `/delete-plans/{id}/confirm` 会拒绝真实删除。完成端到端 dry-run 检查后，如需真实删除，需要在服务器环境中显式设置：

```bash
EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=false
```

## STRM 与媒体根目录

扫描总根：

```bash
EMBY_MEDIA_ACTIONS_STRM_ROOTS=/mnt/cache/docker1/alist-strm/video
```

整理后、Emby 入库侧 roots：

```bash
EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS=/mnt/cache/docker1/alist-strm/video/mp302_mv,/mnt/cache/docker1/alist-strm/video/mp302_tv,/mnt/cache/docker1/alist-strm/video/porn_tv1
```

源 STRM roots：

```bash
EMBY_MEDIA_ACTIONS_SOURCE_ROOTS=/mnt/cache/docker1/alist-strm/video/alist_mv1,/mnt/cache/docker1/alist-strm/video/alist_tv1,/mnt/cache/docker1/alist-strm/video/115strm,/mnt/cache/docker1/alist-strm/video/kuake2,/mnt/cache/docker1/alist-strm/video/302porn_tv1
```

当前设计把 STRM URL 作为映射主键依据，`inode` / `link_count` 只作为诊断信息，不用于推断硬链接关系。

## 删除链路检查

上线前建议按顺序确认：

1. IINA 菜单触发 `emby-delete-plan` 后，后端 `/emby-media-actions/intake` 返回 `delete_plan.status=draft`。
2. Web UI `/emby-media-actions` 输入 Plan ID 后能加载计划项。
3. 对剧集计划，在 Web UI 选择 `单集` / `整季` / `整剧` 后点击生成范围计划，只产生新的 draft plan，不删除任何内容。
4. draft plan 中本地 STRM / 整理后 STRM 路径均位于 allow-list roots 内；不在 roots 内的路径应显示 blocked。
5. `remote_115` 项必须有 `remote_file_id`，并且 dry-run 没有 blocked 后，才允许确认执行。
6. 真实删除前先保持 `EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=true` 做一次端到端演练，并确认 `/confirm` 被阻止。
7. 确认测试媒体可删除后，再把服务器环境改为 `EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=false`，重启后端，再执行一次真实删除。

## 演员名单链路检查

上线前建议按顺序确认：

1. IINA 菜单触发 `emby-blacklist-candidate` 或 `emby-whitelist-candidate` 后，后端返回 `metadata_candidate.status=pending`。
2. Web UI 输入 Candidate ID 后能看到 snapshot title、NFO 路径和演员勾选项。
3. 只勾选目标演员并提交后，candidate 变为 `applied`。
4. 新增关键词写入 `KeywordEntry.keyword_type` 为 `emby_blacklist` 或 `emby_whitelist`。
5. 如果同一演员已存在另一名单类型，接口应返回冲突错误，并保持 candidate 未应用。

## IINA Helper

相关文件：

- `scripts/emby_media_action_shortcut.py`
- `scripts/iina_emby_media_actions.lua`

IINA / Lua 只负责收集当前播放路径、URL、标题和可选 Emby 上下文，并调用 helper 提交到后端。删除确认和名单写入都必须回到 Web UI 完成。

## 回滚建议

如上线后需要快速停用：

```bash
EMBY_MEDIA_ACTIONS_ENABLED=false
```

同时移除或禁用 IINA Lua 菜单脚本，避免继续创建新的候选或删除计划。已创建的 draft plan 不会自动执行；只要不调用确认接口，就不会删除本地文件或 115 原文件。
