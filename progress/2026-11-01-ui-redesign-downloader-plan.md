# 2026-11-01 整站 UI 重设计与下载器双流重做（实施计划）

## What was done

- 按用户修订后的设计规范（双流模型：候选收件箱 + 任务看板，侧边检查抽屉，5 秒撤销）写出实施计划 `docs/superpowers/plans/2026-11-01-ui-redesign-downloader.md`，共 16 个任务：A1–A3 设计系统，B1–B9 下载器前后端，C1–C3 其余页面迁移，D1 整体验收。
- 核对 RN 下载器源码后，在计划中记录了 4 处与规范的偏差：
  - RN 只能按任务重试（本来就只重试失败文件），没有单文件重试接口，所以抽屉里不放单项重试；
  - 「有更新 +N」需要新增 `completed_media_count` 字段；
  - 提交接口改为接受待确认候选；
  - 修复文件历史把格式化字符串当字节数解析、导致字节数总为 0 的已有缺陷。

## Testing

- 只写文档，未改代码，未运行测试。

## Notes

- Changed files：`docs/superpowers/plans/2026-11-01-ui-redesign-downloader.md`、本日志。
- Rollback：删除上述两个文件。
- 未提交 git。B1 数据库迁移开始前需用户再次确认。
