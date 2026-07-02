# Emby IINA 媒体动作设计

## 背景

当前媒体链路是：

1. 115 通过 Alist/OpenList 挂载。
2. 针对特定网盘目录生成本地 `.strm`。
3. MoviePilot 监控源 STRM 目录，并生成刮削整理后的媒体库结构。
4. Emby 挂载整理后的媒体目录。
5. Emby 播放 `.strm`，实际播放地址为 Alist/OpenList 的 `/d/115_OPEN/...` URL。

用户希望在 IINA 播放时触发快捷动作，实现：

- 为当前媒体生成安全删除计划，覆盖 Emby 整理产物、源 STRM、115 原文件。
- 保存当前媒体 NFO/Emby 元数据快照。
- 在 Web UI 中选择演员加入 Emby 专用黑白名单。

本设计新建独立模块 `emby_media_actions`，不混入现有 `review_intake`。

## 已确认约束

- IINA 只提交当前播放项，不直接删除文件，也不直接修改黑白名单。
- 115 原文件删除只走 `18x_v2` 现有 115 OpenAPI 能力，不使用 Alist API 删除。
- 删除必须先生成 draft 计划，经 Web UI 二次确认后才执行。
- 剧集删除粒度在 Web UI 中选择：当前集、当前季、整部剧。
- 黑白名单流程先保存完整 NFO/元数据快照，再在 Web UI 勾选具体演员进入 `emby_blacklist` 或 `emby_whitelist`。
- STRM 与整理产物原本可能通过硬链接生成；当前部分文件硬链接断开，是因为历史上批量修改过 `d/115` 到 `d/115_OPEN`。删除和映射逻辑不能依赖 inode/link count，只能依赖路径归属和 STRM 内容 URL。

## 远端目录观察

远端基础目录：

```text
/mnt/cache/docker1/alist-strm/video
```

已观察到的主要目录：

- `115strm`
- `302porn_tv1`
- `alist_mv1`
- `alist_tv1`
- `kuake2`
- `mp302_mv`
- `mp302_tv`
- `porn_tv1`

抽样和统计显示，`.strm` 内容 URL 是最稳定的关联键。全库约 10153 个唯一 STRM URL，其中约 8432 个 URL 在多个 `.strm` 文件中出现。

典型映射关系：

- `alist_mv1` -> `mp302_mv`
- `alist_tv1` / `115strm` / `kuake2` -> `mp302_tv`
- `302porn_tv1` -> `porn_tv1`

示例：源 STRM 和 Emby 整理后 STRM 可以指向同一个 `/d/115_OPEN/...` URL，即使它们当前不是硬链接。

## 总体架构

`emby_media_actions` 模块由六个边界清晰的部分组成：

1. IINA 入口
   - Lua 脚本提供菜单或快捷键。
   - 调用本地 helper 或直接请求后端 API。
   - 只提交当前播放路径、标题、URL、动作类型等上下文。

2. API 层
   - 提供 `/api/emby-media-actions/*` 路由。
   - 接收 IINA 请求。
   - 创建媒体动作会话、删除计划、名单候选记录。

3. Emby 解析层
   - 使用 Emby API 解析 item、媒体类型、剧集层级、MediaSources、演员和元数据。
   - 从 `.env.emby` 或主配置读取 Emby base URL 和 API key。

4. STRM 映射层
   - 读取配置的源目录和整理目录。
   - 以 `.strm` 内容 URL 为 canonical key 建立映射。
   - 解码 `/d/115_OPEN/...` 为 115 路径。
   - 通过 115 OpenAPI 解析 `file_id` 等可删除标识。

5. 删除计划层
   - 生成 draft 删除计划。
   - 将删除项分成 Emby 整理产物、源 STRM、115 原文件三组。
   - 执行时逐项记录状态和错误。

6. Web UI
   - 展示当前媒体上下文、NFO/演员、删除计划。
   - 对剧集提供当前集、当前季、整部剧的粒度选择。
   - 对删除提供二次确认。
   - 对黑白名单提供演员勾选。

## 数据模型

### `emby_media_mappings`

保存当前 Emby item 与 STRM URL/115 原文件之间的主映射。一个 STRM URL 可以对应多个本地 `.strm` 路径，具体路径放在 `emby_media_mapping_paths`。

建议字段：

- `id`
- `emby_item_id`
- `emby_item_type`
- `emby_title`
- `emby_series_id`
- `emby_season_id`
- `emby_episode_id`
- `alist_url`
- `alist_mount_name`
- `remote_provider`
- `remote_path`
- `remote_file_id`
- `remote_pick_code`
- `remote_sha1`
- `remote_size`
- `created_at`
- `updated_at`

### `emby_media_mapping_paths`

保存同一个 STRM URL 反查到的所有本地路径。

建议字段：

- `id`
- `mapping_id`
- `path_role`
- `path`
- `root_name`
- `root_path`
- `file_size`
- `inode`
- `link_count`
- `created_at`

`path_role` 可用：

- `organized_strm`
- `organized_metadata`
- `source_strm`

`inode` 和 `link_count` 只作为诊断信息保存，不作为删除关系判断依据。

### `emby_delete_plans`

删除计划主表。

建议字段：

- `id`
- `source`
- `emby_item_id`
- `scope`
- `status`
- `summary`
- `created_by`
- `created_at`
- `confirmed_at`
- `started_at`
- `finished_at`

`status` 可用：

- `draft`
- `confirmed`
- `running`
- `completed`
- `failed`
- `cancelled`

`scope` 可用：

- `episode`
- `season`
- `series`
- `movie`

### `emby_delete_plan_items`

删除计划明细表。

建议字段：

- `id`
- `plan_id`
- `group`
- `target_type`
- `target_path`
- `remote_file_id`
- `display_name`
- `status`
- `blocked_reason`
- `error_message`
- `dry_run_result`
- `executed_at`

`group` 可用：

- `emby_library`
- `source_strm`
- `remote_115`

### `emby_metadata_snapshots`

保存 NFO/Emby 元数据快照。

建议字段：

- `id`
- `emby_item_id`
- `mapping_id`
- `snapshot_type`
- `title`
- `nfo_path`
- `nfo_xml`
- `emby_json`
- `actors_json`
- `created_at`

### 演员黑白名单

推荐先复用或扩展现有关键词体系，新增类型：

- `emby_blacklist`
- `emby_whitelist`

同时在 Emby 元数据快照中保存来源上下文，便于追溯某个演员是从哪部影片或剧集加入名单的。

如果后续需要更强的结构化查询，再独立拆出 `emby_actor_list_entries`。

## 删除流程

1. IINA 触发“生成删除计划”。
2. IINA 提交当前播放项到 `POST /api/emby-media-actions/intake`。
3. 后端识别 Emby item id、标题、媒体类型、当前播放 URL。
4. 如果当前路径是 `.strm`，读取文件内容；如果是 URL，直接使用 URL。
5. 标准化 Alist/OpenList URL。
6. 在配置的 STRM 根目录中反查内容相同的 `.strm`。
7. 根据目录归属把匹配结果分为源 STRM 和 Emby 整理产物。
8. 解码 `/d/115_OPEN/...` 为 115 路径。
9. 使用 115 OpenAPI 解析原文件 `file_id`。
10. 对剧集生成可选 scope：当前集、当前季、整部剧。
11. 创建 `draft` 删除计划。
12. Web UI 展示三组删除项。
13. 用户二次确认。
14. 后端逐项执行删除：
    - 删除 Emby 整理产物。
    - 删除源 STRM。
    - 通过 115 OpenAPI 删除网盘原文件。
15. 每个删除项独立记录状态和错误。

## 黑白名单流程

1. IINA 触发“提交黑名单候选”或“提交白名单候选”。
2. 后端创建候选会话。
3. 后端解析当前 item 的 Emby 元数据和 NFO。
4. 保存完整元数据快照。
5. Web UI 展示标题、海报、演员列表、NFO 摘要。
6. 用户勾选具体演员。
7. 后端写入 `emby_blacklist` 或 `emby_whitelist`。
8. 记录来源 item 和 snapshot id，便于后续审计。

## 安全规则

- 所有本地删除路径必须落在配置的白名单根目录下。
- 不在白名单根目录下的路径只能展示为 blocked，不能执行删除。
- 115 删除必须解析到 `file_id` 后才允许确认。
- 删除计划在 draft 状态下只做 dry-run，不执行实际删除。
- IINA 不提供直接删除入口。
- 删除执行逐项记录结果，部分失败不能吞掉错误。
- 对剧集删除整季或整部剧时，Web UI 必须展示展开后的 episode 列表和远端文件列表。
- 对空目录清理要单独标记，不能默认递归删除父目录。

## 配置建议

新增配置项：

```env
EMBY_BASE_URL=http://192.168.70.138:8096
EMBY_API_KEY=...
EMBY_MEDIA_ACTIONS_ENABLED=true
EMBY_MEDIA_ACTIONS_STRM_ROOTS=/mnt/cache/docker1/alist-strm/video
EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS=/mnt/cache/docker1/alist-strm/video/mp302_mv,/mnt/cache/docker1/alist-strm/video/mp302_tv,/mnt/cache/docker1/alist-strm/video/porn_tv1
EMBY_MEDIA_ACTIONS_SOURCE_ROOTS=/mnt/cache/docker1/alist-strm/video/alist_mv1,/mnt/cache/docker1/alist-strm/video/alist_tv1,/mnt/cache/docker1/alist-strm/video/115strm,/mnt/cache/docker1/alist-strm/video/kuake2,/mnt/cache/docker1/alist-strm/video/302porn_tv1
EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=true
```

实际 API key 不写入设计文档或代码。

这些路径是生产环境服务器路径。第一版执行删除时要求 `18x_v2` 后端运行在能直接访问这些路径的环境中，或由容器把这些根目录只挂载到白名单路径下。macOS 本地开发只使用 fixture 或 dry-run，不直接删除远端真实文件。

## IINA 动作

IINA 脚本提供三个动作：

- 生成删除计划
- 提交黑名单候选
- 提交白名单候选

推荐复用现有 `scripts/iina_review_intake.lua` 和 helper 的风格，但新建独立脚本，例如：

- `scripts/iina_emby_media_actions.lua`
- `scripts/emby_media_action_shortcut.py`

默认 API base 与现有脚本一致，指向 `http://192.168.70.138:8010/api`。

## API 草案

- `POST /api/emby-media-actions/intake`
  - IINA 统一入口。
  - 参数包含 action、path、url、title、player、timestamp。

- `POST /api/emby-media-actions/delete-plans`
  - 创建删除计划。

- `GET /api/emby-media-actions/delete-plans/{id}`
  - 查看删除计划详情。

- `POST /api/emby-media-actions/delete-plans/{id}/confirm`
  - 二次确认并开始执行。

- `POST /api/emby-media-actions/metadata-candidates`
  - 创建黑白名单候选会话。

- `POST /api/emby-media-actions/metadata-candidates/{id}/apply`
  - 将选中演员写入黑白名单。

## 测试策略

- 单元测试：
  - STRM URL 标准化。
  - `/d/115_OPEN/...` 路径解码。
  - 源目录和整理目录归类。
  - 删除路径白名单校验。
  - NFO 演员解析。

- 服务测试：
  - IINA intake 创建候选会话。
  - 删除计划 dry-run 生成三组明细。
  - 剧集当前集、当前季、整部剧 scope 展开。
  - 115 file_id 解析失败时阻止远端删除。

- 集成测试：
  - 使用本地 fixture `.strm` 和 `.nfo` 模拟远端目录。
  - mock 115 OpenAPI，验证只在 confirm 后调用真实删除接口。

## 非目标

- 不实现 Alist API 删除。
- 不在 IINA 中直接删除任何内容。
- 不以 inode/link count 判断媒体关系。
- 不一次性重构现有 `review_intake`。
- 不在第一版实现复杂推荐或自动拉黑逻辑。

## 实施顺序建议

1. 后端模型和 migration。
2. STRM 映射与路径安全校验服务。
3. Emby API 解析服务。
4. 删除计划 dry-run API。
5. NFO 快照和演员候选 API。
6. Web UI 审核页面。
7. IINA 脚本和 helper。
8. 115 OpenAPI confirm 执行。
