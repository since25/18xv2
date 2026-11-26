# 2026-11-25 Jellyfin 显示名：新格式试跑与读取提速

## What was done

- 序号在前的新格式（提交 `5c0f9138`）已于北京时间 2026-11-26 12:24 部署（先单独构建镜像，再切换容器；部署后首页 200、接口未登录 401、`Application startup complete`）。
- 重跑 `--keyword 何娃娃`（12:26–12:36）：改名 14、失败 0。读回 Jellyfin：名字为 `01 · 何娃娃/6605-抖音-何娃娃` 等，均锁定；强制排序名为 `何娃娃/0000006605-抖音-何娃娃 · 0000000001` 等；合集按排序名仍是 6605 → 11935 → 29828、包内 01 起顺序排列。列表接口能读回强制排序名，重复执行可正确判断"已改好"。
- 按用户给的提速方案改代码：
  - 全量只读「本地已整理」这一个库：按 `MEDIA_LIBRARY_LOCAL_ROOTS` 对应的库位置找库 ID，找不到时退回读全部；
  - `--keyword` 只读该关键词的 18x 合集成员，没有合集时退回读本地库；按关键词执行时只按这个关键词的视频编号（一个资源包里的视频关联的关键词相同，结果与全量编号一致）；
  - 新增 `JELLYFIN_DISPLAY_NAMES_PAGE_SIZE`（默认 5000）、`JELLYFIN_DISPLAY_NAMES_TIMEOUT_SECONDS`（默认 30），与合集同步的 `JELLYFIN_PAGE_SIZE` 分开。
- 动手前只读测量（12:38 前后，生产 Jellyfin 10.10.7）：
  - 读全部条目，每页 500 条：5.1 秒，总数 53749（约 9 分钟，与之前一致）；
  - 只读本地库，每页 500 条：0.7 秒；每页 5000 条：3.6 秒和 3.3 秒，库内总数 46277（含封面图片等非视频条目）→ 全库约 10 页、约 35 秒；
  - 只读「何娃娃」合集成员：14 条，约 0 秒；
  - 管理员读单个条目：0.01–0.03 秒。
- 超时取 30 秒（设计方决定）：单页 3.6 秒，余量约 8 倍；不取更长是因为 Jellyfin 挂掉时连续 20 次失败才停，超时越长停得越晚（30 秒约 40 分钟，60 秒约 80 分钟）。
- 文档同步：设计文档第六节、`docker/jellyfin/README.md`、`.env.example`。

## Testing

- 新增测试先确认失败（不认识按库读取参数、没有找库方法、没有读合集详情方法、读取范围不对、没用新配置），再实现。
- Spark 后端全量：`scripts/remote-test.sh backend` → 765 passed（日志 `~/ci/18x_v2/jellyfin-display-names/.remote-test-logs/20261126-123712-backend.log`）。

## Notes

- Changed files：`app/services/jellyfin/client.py`、`app/services/jellyfin/display_name_sync_service.py`、`app/services/jellyfin/job_runner.py`、`app/core/config.py`、`tests/jellyfin/test_client.py`、`tests/jellyfin/test_display_name_sync.py`、`tests/jellyfin/test_job_runner.py`、`.env.example`、`docker/jellyfin/README.md`、`docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`、本日志。
- 单条写入耗时未测（写入无法只读测量）；部署后下一次按关键词执行时，读取几乎不花时间，总耗时即写入耗时，可据此估算全量。
- 未提交、未部署。
- Rollback：回退本次提交并重建 18x；新配置项不设置即用默认值，不影响合集同步。
