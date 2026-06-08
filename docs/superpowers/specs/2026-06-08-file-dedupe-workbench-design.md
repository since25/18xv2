# 文件去重工作台设计

日期：2026-06-08

## 背景

项目当前已有目录树导入、`TreeImport`、`NodeFile`、115 文件详情查询、清理删除、白名单批处理 Job/SSE 等能力。用户希望恢复并重做文件去重能力，核心目标不是简单找同名文件，而是从导入的全量目录树中低成本发现疑似重复文件，人工审批后再少量调用 115 API 做确认，最后通过限流删除计划执行。

默认输入是文件名目录树，例如 `/Users/wangyichuan/Desktop/wangcodemac/18x_v2/根目录20260419_目录树.txt`。该样例是 UTF-16LE 纯目录树，约 3677 个节点，其中约 3071 个文件、606 个文件夹；不包含 115 `file_id`、`sha1`、文件大小等远端元数据。因此第一版必须以结构型目录树为默认输入，不能依赖导入阶段已有远端文件标识。

## 目标

1. 新增独立的文件去重工作台页面。
2. 扫描阶段只走本地目录树检索和相似度分析，避免高频调用 115 文件搜索 API。
3. 支持可编辑的文件名归一化规则，包括噪音词、正则、预览归一化结果。
4. 扫描结果进入持久化候选账本，支持分批审核、刷新后继续、丢弃、恢复、重新确认。
5. 对审批后的少量候选调用 115 API 做路径解析和文件详情确认。
6. 按确认等级区分 `已验证重复`、`高概率重复`、`仅文件名疑似`。
7. 删除必须通过删除计划二次确认，并由后台限流逐个执行。

## 非目标

1. 不在扫描阶段调用 115 文件搜索 API。
2. 不因为文件名相似直接删除文件。
3. 不把仅文件名疑似的候选默认批量勾选。
4. 第一版不要求远端快照导入时保存完整文件级 `file_id`，后续可作为优化。
5. 第一版不做复杂暂停恢复调度，失败项重试可以先做成计划项级重试入口。

## 总体架构

第一版采用“候选账本 + 删除计划双阶段”的最小闭环。

1. 目录树导入沿用现有 `TreeImport` 和 `NodeFile`。
2. 本地去重扫描 Job 读取某个 `tree_import_id` 下的 `NodeFile`，执行归一化、分桶、相似度打分。
3. 扫描结果写入 `dedupe_scan_runs`、`dedupe_groups`、`dedupe_candidates`。
4. 用户在工作台中审核候选组，选择保留项和待删除项。
5. 远端确认 Job 仅处理用户选中的候选，按路径解析 `remote_file_id`，再查询文件详情。
6. 确认后的候选可以生成 `dedupe_delete_plans` 和 `dedupe_delete_plan_items`。
7. 删除计划二次确认后启动执行 Job，按限流逐个调用 115 删除接口。

候选账本只负责发现、判断和审批。删除计划只负责执行和审计。两者分离，避免候选审核页面直接产生不可逆副作用。

## 数据模型

### `dedupe_scan_runs`

记录每次扫描。

建议字段：

- `id`
- `tree_import_id`
- `status`
- `scope_path_prefix`
- `included_extensions`
- `candidate_threshold`
- `high_confidence_threshold`
- `rules_snapshot_json`
- `total_files`
- `total_groups`
- `total_candidates`
- `summary_json`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

### `dedupe_groups`

记录一个疑似重复组。

建议字段：

- `id`
- `scan_run_id`
- `tree_import_id`
- `group_key`
- `representative_name`
- `normalized_name`
- `score_max`
- `confidence_level`
- `status`
- `suggested_keep_candidate_id`
- `review_note`
- `created_at`
- `updated_at`

建议状态：

- `pending_review`
- `confirmed`
- `dismissed`
- `planned`
- `partially_planned`

建议确认等级：

- `filename_suspected`
- `high_probability`
- `verified_duplicate`

### `dedupe_candidates`

记录组内每个文件。

建议字段：

- `id`
- `group_id`
- `node_file_id`
- `raw_name`
- `raw_path`
- `file_ext`
- `normalized_name`
- `similarity_score`
- `suggested_action`
- `suggested_reason`
- `user_action`
- `user_reason`
- `created_at`
- `updated_at`

建议动作：

- `keep`
- `delete`
- `undecided`

### `dedupe_remote_confirmations`

记录远端确认阶段的结果。

建议字段：

- `id`
- `candidate_id`
- `status`
- `remote_file_id`
- `remote_parent_id`
- `remote_path`
- `remote_name`
- `sha1`
- `size_bytes`
- `file_status`
- `error_message`
- `confirmed_at`

建议状态：

- `pending`
- `resolved`
- `not_found`
- `ambiguous`
- `detail_failed`
- `stale_remote_info`

### `dedupe_delete_plans`

记录删除计划头。

建议字段：

- `id`
- `name`
- `source_scan_run_id`
- `tree_import_id`
- `status`
- `confirm_token`
- `rate_limit_seconds`
- `total_items`
- `deleted_count`
- `failed_count`
- `skipped_count`
- `created_at`
- `confirmed_at`
- `started_at`
- `finished_at`

建议状态：

- `draft`
- `confirmed`
- `running`
- `completed`
- `completed_with_errors`
- `cancelled`

### `dedupe_delete_plan_items`

记录每个待删除文件。

建议字段：

- `id`
- `plan_id`
- `candidate_id`
- `node_file_id`
- `remote_file_id`
- `raw_path`
- `remote_path`
- `confirmation_level`
- `delete_reason`
- `status`
- `error_message`
- `deleted_at`
- `created_at`
- `updated_at`

建议状态：

- `pending`
- `deleting`
- `deleted`
- `skipped`
- `failed`
- `stale_remote_info`

## 扫描算法

扫描阶段只读本地数据库，不调用 115 文件搜索 API。

### 输入过滤

默认只扫描 `NodeFile`。默认媒体后缀：

- `.mp4`
- `.mkv`
- `.avi`
- `.mov`

可选扩展到字幕、图片、压缩包。支持按目录路径前缀限制扫描范围，例如只扫描 `/根目录/待整理`。

### 文件名归一化

为每个文件保存原始名称，同时生成 `normalized_name`。

默认归一化规则：

1. 去扩展名。
2. 统一大小写、空白、全半角、常见分隔符。
3. 剥离站点前缀和水印词。
4. 剥离分辨率、编码、画质标签。
5. 识别 `part`、`cd`、`ep`、集数等序列标记。
6. 识别 `copy`、`副本`、`(1)`、`_1` 等复制标记。
7. 保留必要的标题主体和关键数字，避免把系列不同集误并。

规则集必须可编辑。工作台应提供噪音词、正则、保留词配置，并支持对若干样本预览归一化前后结果。

### 分桶

为避免全量两两比较，先按候选 key 分桶。

可用桶 key：

- 归一化名称指纹
- 前若干中文或英文 token
- 数字序列
- 文件扩展名
- 父目录上下文

只有同桶或近桶文件进入相似度计算。

### 相似度打分

综合以下信号：

- 归一化名称字符相似度
- token 重叠度
- 数字、集数、part 序列一致性
- 扩展名一致性
- 父目录相近性
- 复制标记权重
- 命名质量权重

默认阈值：

- `>= 0.92`：高概率重复
- `0.82 - 0.92`：仅文件名疑似
- `< 0.82`：不入队

`已验证重复` 只能在远端确认阶段产生。

## 工作台页面

新增前端页面：`文件去重`。

建议导航位置：与 `导入批次`、`目录内容`、`整理任务`、`白名单批处理` 平级。

页面分三栏。

### 左侧：扫描与规则

功能：

- 选择目录树批次。
- 选择扫描范围。
- 配置后缀、阈值、分桶策略。
- 选择或编辑规则集。
- 预览归一化结果。
- 启动本地扫描。
- 接回进行中的扫描 Job。

页面必须明确提示：扫描阶段不调用 115 文件搜索 API。

### 中间：候选组列表

功能：

- 统计卡片：全部组、待审核、高概率、已验证、已入计划。
- 分页列表候选组。
- 筛选：状态、确认等级、建议动作、路径关键词、分数区间、是否可批量删除。
- 批量选择，但默认只允许 `已验证重复` 自动勾选。
- 支持丢弃、恢复、重新确认、加入删除计划。

### 右侧：详情与审批

功能：

- 展示组内所有文件。
- 展示原始文件名、归一化名、完整路径、扩展名。
- 展示远端解析结果、`sha1`、`size`、错误状态。
- 展示系统建议保留或删除的原因。
- 支持人工选择保留项和待删除项。
- 支持给审批结果添加备注。

## API 和 Job

新增路由前缀：`/dedupe`。

### Job 接口

- `POST /dedupe/scan-jobs`
- `POST /dedupe/confirm-jobs`
- `POST /dedupe/delete-plans/{plan_id}/execute-jobs`
- `GET /dedupe/jobs/{job_id}/progress`
- `GET /dedupe/jobs/active`

Job 进度结构沿用白名单批处理：

- `job_id`
- `job_type`
- `stage`
- `current`
- `total`
- `done`
- `error`
- `summary`
- `started_at`
- `finished_at`

### 候选接口

- `GET /dedupe/groups`
- `GET /dedupe/groups/{group_id}`
- `POST /dedupe/groups/{group_id}/review`
- `POST /dedupe/groups/bulk-review`
- `POST /dedupe/groups/{group_id}/dismiss`
- `POST /dedupe/groups/{group_id}/restore`

### 删除计划接口

- `POST /dedupe/delete-plans`
- `GET /dedupe/delete-plans`
- `GET /dedupe/delete-plans/{plan_id}`
- `POST /dedupe/delete-plans/{plan_id}/confirm`
- `POST /dedupe/delete-plans/{plan_id}/items/retry-failed`

## 远端确认

确认阶段只处理用户选择的少量候选。

默认流程：

1. 从 `NodeFile.raw_path` 转成 115 可解析路径。
2. 逐级列目录或调用已有路径解析能力，得到 `remote_file_id`。
3. 查询文件详情，尽量获取 `sha1`、`size`、文件状态、远端路径。
4. 写入 `dedupe_remote_confirmations`。
5. 更新候选组确认等级。

如果路径解析失败、命中多个同名项、详情接口缺字段或远端文件已变化，则候选不能自动进入删除计划。

## 删除安全策略

1. 扫描阶段不能删除。
2. 未解析到 `remote_file_id` 的候选不能入删除计划。
3. 仅文件名疑似不能批量删除。
4. 已验证重复才允许自动批量勾选。
5. 高概率重复必须逐组人工确认。
6. 删除计划必须二次确认。
7. 执行删除前再次轻量校验远端信息。
8. 默认限流为每 `1.5 - 3` 秒删除一个文件。
9. 单项失败不阻断整个计划。
10. 每个计划项保留完整审计信息，包括来源重复组、确认等级、远端信息快照、删除理由和执行结果。

## 删除策略配置

默认策略：

1. 优先保留 `/已整理`、归档类目录中的文件。
2. 优先删除 `/待整理`、`/重复`、含 `copy`、`副本`、`(1)` 的文件。
3. 优先保留命名质量更高、站点水印更少的文件。
4. 同 SHA 或同大小确认后，才允许批量自动勾选。
5. 只靠文件名相似的候选只能进入人工审核。

第一版可以内置策略并保留配置入口。完整策略编辑器可后续增强。

## 测试计划

### 解析与归一化

- UTF-16LE 目录树解析。
- 文件和文件夹识别。
- 媒体后缀过滤。
- 站点前缀、水印、分辨率、`copy`、`(1)`、`part` 归一化。

### 扫描算法

- 完全同名文件进入同组。
- 高相似文件进入高概率组。
- 明显不同文件不入组。
- 数字、集数、part 不一致时降低分数。
- 重复扫描不无限新增候选。

### 远端确认

使用 `Fake115Client` 覆盖：

- 路径解析成功。
- 路径解析失败。
- 同路径多命中。
- 详情缺少 `sha1`。
- 大小不同。
- SHA 一致。

### 删除计划

- 禁止未解析项入计划。
- 禁止仅文件名疑似批量入计划。
- 已验证重复可入计划。
- 二次确认后才能执行。
- 单项失败不阻断后续。
- 删除前远端信息变化时跳过。

### 前端

- TypeScript 编译和 lint。
- 页面选择导入批次。
- 启动扫描并显示 SSE 进度。
- 筛选候选组。
- 查看详情并审批。
- 创建删除计划。
- 展示执行结果和错误状态。

## 分阶段落地

### 阶段 1：后端扫描闭环

- 新增模型和 Alembic migration。
- 实现归一化规则服务。
- 实现本地扫描服务。
- 实现扫描 Job 和候选列表 API。
- 添加后端测试。

### 阶段 2：工作台审核闭环

- 新增前端页面和导航。
- 实现候选组列表、筛选、详情。
- 实现规则预览和临时噪音词。
- 实现人工审批和远端确认 Job。

### 阶段 3：删除计划闭环

- 实现删除计划模型和 API。
- 实现二次确认。
- 实现限流删除 Job。
- 实现执行结果展示和失败重试。

## 部署注意事项

本项目当前服务器部署位置记录为 `root@tank61213:/mnt/user/docker1/18xv2`。服务器操作必须先只读检查并反馈结果，得到用户批准后才能执行任何写入、拉取、重启、部署或重建。

本地代码修改后，优先推送 GitHub 仓库，再给出服务器侧拉取和更新流程。由于本设计涉及后端模型、Alembic migration、前端页面和可能的容器代码更新，最终实现后通常需要：

1. 在服务器只读确认当前 git 分支、容器编排文件和运行状态。
2. 经用户批准后拉取 GitHub 更新。
3. 执行数据库迁移。
4. 按实际 Docker 配置判断是否需要 rebuild 后端或前端镜像。
5. 重启服务并只读验证健康检查、页面和关键 API。
