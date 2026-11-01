# RN 下载器增量版本与长期历史设计

## 目标

当 RN 已下载的资源包出现新的 `index_revision` 时，18x 为该版本重新生成白名单候选；人工确认后，RN 只下载该版本中从未完整成功过的媒体。18x 同时保留任务状态变化和文件级进度历史，便于追踪重试、部分成功和最终结果。

## 约束

- 仍使用 HTTP 控制面，不共享 RN SQLite，不直接操作 RN 文件系统。
- 保留 A 模式：白名单命中只生成候选，人工确认后提交。
- 黑名单命中、非 `stable` 资源包不生成候选。
- 18x 的候选按资源包版本保存，历史版本不能被新版本覆盖。
- 增量模式只排除 RN 既往“完整成功”的资源包版本中已经下载成功的消息；部分成功或失败版本中的消息仍允许重试。
- 旧 RN 客户端和旧 Web API 调用继续使用完整下载模式。

## 数据流

1. RN 扫描发布新的 `index_revision`，资源包 API 返回 `index_revision`、`completed_revision` 和当前下载状态。
2. 18x 以 `package_id + package_revision + keyword_entry_id` 创建候选。旧版本待确认候选标记为 `dismissed`，旧版本已提交/已完成记录保留。
3. 18x 提交时使用带版本和模式的幂等键，并向 RN `/api/packages/{id}/download-batch` 发送 `{ "mode": "incremental" }`。
4. RN 根据当前包的媒体消息 ID，排除旧版本完整成功批次的消息，只把新增消息写入新批次；没有新增消息时返回可识别的 `no_new_items`，不创建空任务。
5. 18x 同步 RN 任务详情，将最新状态写入现有快照表；当详情内容发生变化时追加任务历史和文件历史。

## 18x 数据模型

- `downloader_packages.completed_revision`：RN 最后一次完整成功的资源包版本。
- `downloader_package_candidates.package_revision`：候选对应的资源包版本；唯一键改为 `(package_id, keyword_entry_id, package_revision)`。
- `downloader_submissions.package_revision`、`download_mode`：记录实际提交版本和完整/增量模式。
- `downloader_task_histories`：每次任务详情发生变化的不可变快照。
- `downloader_task_file_histories`：任务历史快照中的文件状态和进度，按历史快照关联。

## RN API 与存储

- 下载批次 API 新增可选 JSON 字段 `mode`，取值 `full` 或 `incremental`；缺省仍为 `full`。
- `channel_download_batches.download_mode` 保存批次模式，旧行默认 `full`。
- 增量模式允许已成功资源包的新版本提交，并按同一资源包的历史批次包状态为 `completed` 的记录排除旧消息。
- 既有 `/api/tasks`、`/api/tasks/{id}` 响应保持兼容；18x 从详情中的 `files` 保存文件级历史。

## 查询与界面

- `/downloader` 候选表显示版本和增量媒体数；确认下载仍是显式二次操作。
- `/api/downloader/tasks/{task_id}/history` 返回任务状态历史及文件快照。
- `/api/downloader/packages` 支持按候选状态和关键词查询，历史候选可以查看但不默认进入待确认列表。

## 失败与恢复

- RN 无新增媒体时不创建空批次，18x 将该候选标记为 `no_new_items`。
- 任务 `completed_with_errors` 保留为部分成功状态，不再压缩成普通 `failed`；文件历史保留成功与失败明细。
- 同步重复收到相同任务详情时不追加重复历史行；远端不可达不影响已有快照和历史。

## 验收标准

- 资源包版本从 2 个媒体变为 20 个媒体时，18x 生成新版本候选，提交后 RN 批次只包含新增 18 个媒体。
- 同一候选重复提交不会创建第二个 RN 批次。
- 部分成功任务显示 `completed_with_errors`、成功数、失败数和文件级状态。
- 两次相同任务详情同步只产生一条历史快照；状态或文件变化后产生新快照。
- 旧完整下载接口、现有 RN Web 下载流程和现有 18x 全量测试继续通过。
