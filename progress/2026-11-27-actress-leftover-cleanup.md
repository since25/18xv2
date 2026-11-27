# 2026-11-27 女优删片：清理残留配套文件（实施）

设计：`docs/superpowers/specs/2026-11-27-actress-delete-leftover-cleanup-design.md`；计划：`docs/superpowers/plans/2026-11-27-actress-delete-leftover-cleanup.md`。

## What was done

- 删片批次在删完番号目录后多了一步「清理配套文件」，115 和 `porn_tv1` 源目录各按目录处理：
  - 目录里只剩 nfo / 图片 / 字幕，并且没有子文件夹时，整个目录删掉（115 进回收站，删完再刷新上级 OpenList 缓存）；
  - 否则只删和被删视频同名的 `<名字>.nfo`、`<名字>-poster/-fanart/-thumb.<图片扩展名>`、`<名字>.<字幕扩展名>`；
  - 115 端靠 OpenList 列目录判断（115 列目录接口返回 405），所以必须先成功刷新 OpenList；按路径再确认类型（目录必须是文件夹、文件必须是文件）；115 根目录不删；
  - 结果记成新的文件行分组 `remote_leftover` / `source_leftover`，新增状态 `skipped`（未清理）；清理失败或出意外都不让片子失败。
- 新增补跑脚本 `scripts/actress_clean_leftovers.py --batch <ID> [--apply]`：只处理已删除的片子，默认只预览。
- 删除页的确认框、页面说明，以及历史批次里的分组和状态标签同步更新；接口类型已重新生成。
- `docs/actresses.md` 补了删除步骤第 8 步、补跑用法，上线清单加了「补跑首删批次」一条。
- 分工：代码和测试由外部工人 dsh（deepseek-v4.1-flash）按计划实施；主管审阅后补了两处：
  1. `_process_film` 外再包一层，清理步骤出现意料外的异常时只记在片子的 `reason` 上，不打断批次；
  2. 补跑脚本显式导入 `app.models.keywords`，否则单独运行时数据库映射配置失败（早上在容器里只读查询时遇到过同样的报错）。

## Testing

- Spark `scripts/remote-test.sh all`（2026-11-27 10:21，当前工作区代码）：后端 1035 passed；前端 test 164 passed，build 和 lint 都是 0。日志 `~/ci/18x_v2/actress-leftover-cleanup/.remote-test-logs/20261127-102122-all.log`。
- 接口类型生成 `scripts/gen-api-types.sh` 退出码 0。
- 本机验证补跑脚本导入后数据库映射能配置成功。
- 没有对真实 115 / OpenList 跑过清理；部署后用补跑脚本预览首删批次时验证。

## Notes

- Changed files：`app/services/actresses/leftovers.py`（新增）、`app/services/actresses/delete_batch_service.py`、`app/services/actresses/delete_guard.py`、`app/services/actresses/openlist.py`、`app/models/actresses.py`（只改注释）、`app/schemas/actresses.py`、`scripts/actress_clean_leftovers.py`（新增）、`frontend/src/pages/ActressDeletePage.tsx`、`frontend/src/pages/ActressDeletePage.test.tsx`、`frontend/openapi.json`、`frontend/src/api/schema.gen.ts`、`tests/actresses/test_leftovers.py`（新增）、`tests/actresses/test_delete_batch_service.py`、`tests/actresses/test_delete_guard.py`、`tests/actresses/test_openlist.py`、`docs/actresses.md`、设计和计划文档、本日志。没有数据库迁移。
- 未做：合并、部署、补清首删批次，都要用户批准。
- Rollback：回退本次提交，重建容器即可；没有迁移。已经清理掉的 115 文件可以从回收站还原。
