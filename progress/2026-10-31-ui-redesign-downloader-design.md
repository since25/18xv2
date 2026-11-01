# 2026-10-31 整站 UI 重设计与下载器页重做（设计阶段）

## What was done

- 梳理下载器现状：前端直接显示原始字节；`published_at` 已保存但未展示；RN 状态 `outdated` 表示“已下载过但资源包追加了新媒体”；RN 任务详情里的 `created_at`/`updated_at` 和文件字节数此前只存在原始 JSON 中。
- 用 ui-ux-pro-max 生成整站设计方向，并与用户逐项确认：视觉基调选 A（中性灰 + 蓝色强调）；下载记录支持状态、时间、频道/关键词、只看失败文件四类筛选；候选可在资源包级别忽略和恢复；其余页面只换皮并统一骨架。
- 写出设计文档 `docs/superpowers/specs/2026-10-31-ui-redesign-downloader-design.md`。

## Testing

- 只写文档，未改代码，未运行测试。

## Notes

- Changed files：`docs/superpowers/specs/2026-10-31-ui-redesign-downloader-design.md`、本日志。
- Rollback：删除上述两个文件即可。
- 未提交 git（用户未要求）。实施阶段的数据库迁移需用户再次确认。
