# 2026-11-26 女优删片：删后刷新 OpenList，收紧 115「已不存在」判断

上线清单第 1～6 条的只读核对结论见本文 Notes。在主工作区 `main` 上修改，未部署。

## What was done

- **删后刷新 OpenList**：删除批次在「删 115 原文件」之后、「删 porn_tv1 STRM」之前，对这部片的 115 文件在 OpenList 里所在的目录（`/115_OPEN/<115 目录>`）调一次 `POST /api/fs/list`，并带上 `refresh: true`，写法照搬 strmallinone / strm_webhook。这样 alist-strm 就不会按 OpenList 的旧缓存把刚删的 STRM 生成回来。同一目录只刷一次；续跑时已刷新过的目录不再刷。刷新失败只在新增的文件行（分组 `openlist_dir`，状态 `refreshed` / `failed`）上记原因，不让这部片失败。
- 新配置 `OPENLIST_URL`、`OPENLIST_TOKEN`，两项都配了才刷新，没配齐时行为和以前一样。新增 `app/services/actresses/openlist.py`。
- **115「已不存在」判断**：不再认裸的「不存在」，只认两种情况：报错码 `430004`；按路径查询成功但返回空结果（目录还在、文件已没了时 115 不报错）。这两条都对真实 115 做过只读核实。
- 接口模型的文件行分组和状态加了新值，重新生成了前端接口类型；女优删除页的批次详情能显示「OpenList 目录刷新 / 已刷新」。
- `docs/actresses.md` 更新了删除顺序（新增第 5 步）、配置表、上线清单第 3 条和第 8 条；`.env.example` 加了两项配置。

## Testing

- 先补测试、确认失败（新模块不存在，收集即报错），再实现。
- 新增或改动的测试：`tests/actresses/test_openlist.py`（请求格式、各种失败、目录换算）；`test_remote_115.py`（430004、空结果、鉴权类「不存在」判失败、缺 file_id）；`test_delete_batch_service.py`（刷新发生在删本地之前、115 已不存在也刷新、刷新失败不影响删除、续跑时失败的会重刷、成功过的不重刷、不配置时没有这一行）；`test_job_runner.py`（只有地址和令牌都配了才传入客户端）。
- Spark 全量，依次各跑一次：
  - `scripts/remote-test.sh backend` → 退出码 0，958 passed，3 warnings，日志 `~/ci/18x_v2/18x_v2/.remote-test-logs/20261126-202028-backend.log`；
  - `scripts/remote-test.sh frontend` → test 0（161 passed），build 0，lint 0，日志 `~/ci/18x_v2/18x_v2/.remote-test-logs/20261126-202320-frontend.log`。
- 没对真实 OpenList 调过刷新接口；接口格式来自 strmallinone 现有代码，部署配置后在首删时验证。

## Notes

- Changed files：`app/services/actresses/openlist.py`（新增）、`app/services/actresses/delete_batch_service.py`、`app/services/actresses/remote_115.py`、`app/services/actresses/job_runner.py`、`app/core/config.py`、`app/models/actresses.py`（只改注释）、`app/schemas/actresses.py`、`frontend/src/pages/ActressDeletePage.tsx`、`frontend/openapi.json`、`frontend/src/api/schema.gen.ts`、`tests/actresses/test_openlist.py`（新增）、`tests/actresses/test_remote_115.py`、`tests/actresses/test_delete_batch_service.py`、`tests/actresses/test_job_runner.py`、`docs/actresses.md`、`.env.example`、本日志。没有数据库迁移：文件行的分组和状态列本来就是字符串。
- 上线清单只读核对（2026-11-26，生产）：
  1. 有效 115 STRM 条目 6895 个，共 5526 部片，其中多分段片 1013 部；不同演员 1570 人；多人片占 6.7%；NFO 都在，但 523 部片（9.5%）没有演员。启用中的关键词白名单（1570 条）是上传者 / 频道名，和 NFO 演员零重叠，所以「受保护」实际只靠档案白名单。旧 Emby 名单只有 1 条黑名单、0 条白名单。
  2. `docker1` 共享设成只放缓存盘，`/mnt/user/...` 和 `/mnt/cache/...` 两边 STRM 数量一致（302porn_tv1 6895、porn_tv1 7334），抽查内容相同。inode 编号不同是 unRAID 共享层的正常现象，删除代码不比 inode，所以 `ACTRESS_PATH_MAP` 可用。两个可写根在容器里都可写。核对可写性时用了 `touch -c`，刷新过生产 `302porn_tv1` 根目录的修改时间，目录里的文件没有变化。
  3. 见上：`430004` 和空结果。
  4. 按路径查询返回 `file_id`，文件的 `file_category` 是 `"1"`，目录是 `"0"`。
  5. 115 删除是否进回收站：读回收站接口返回 405，没能只读证实，留到首删时核对。
  6. Jellyfin `/Persons/{名字}` 不带 userId 能查到人物，但抽查的人都没有主图，头像会全部显示占位；扫库参数和界面上的「扫描新增和更新的文件」一致（看代码确认，没有触发）；能找到 115 番号库的 ID。
- Rollback：回退本次提交即可。生产上不配 `OPENLIST_*` 时不会刷新；115 判断回退后会退回只认「不存在」三个字。
