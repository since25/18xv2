# 2026-11-01 UI redesign 下载器总进度

## What was done

- 完成下载器双流页面、接口、迁移字段、前端 URL 参数和远程测试脚本的文档说明。
- README 改为“下载器”名称，并说明候选收件箱、5 秒撤销忽略、任务看板和侧边检查抽屉。
- DEVELOPMENT_GUIDE 补充接口清单、迁移与回滚、规范偏差和 Spark 远程测试说明。

## Testing

- Spark 远程测试：后端 pytest 380 passed；前端 vitest 77 passed；build 通过；lint 剩 3 个问题（2 errors、1 warning），均在 ReviewIntakePage 和 EmbyMediaActionsPage，是原有的 set-state-in-effect 和 exhaustive-deps，本轮没有处理。
- 浏览器使用虚构数据检查了浅色和深色主题下的收件箱、浮动操作条、任务看板和检查抽屉。
- 返工修复了 3 个问题：任务列表默认请求走了旧格式分支；浮动条被 transform 祖先困住，改为 portal；任务表复合列。

## Notes

### Changed files

- `README.md`：更新下载器双流说明。
- `docs/DEVELOPMENT_GUIDE.md`：补充下载器接口、迁移、URL 参数、规范偏差和 Spark 远程测试说明。
- `progress/2026-11-01-ui-redesign-downloader.md`：本轮总进度日志。

### Rollback

- 回退上述三个文档文件即可；未执行 Git 操作。
- 已知遗留：窄视口下任务表最右侧操作列需要横向滚动；收件箱和任务筛选在 Python 内存中过滤，数据量大时需要改成 SQL 查询。
- 生产风险：按 pyproject 全新安装时 p115client 0.0.9.3.6 会因 asynctools 漂移而导入失败，已单独提出修复任务，本轮未处理。
