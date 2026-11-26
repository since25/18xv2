# 2026-11-25 Jellyfin 本地视频显示名：合并与部署

## What was done

- 用户批准后，把分支 `worktree-jellyfin-display-names` 快进合并进本地 `main`（`dcc2931f..a21b8a20`），推送 GitHub。
- 主工作区里其他会话留下的未提交文件（8 份 `progress/*.md`、`visuals/`）按用户决定原样保留，未带入本次合并。
- 生产（北京时间 2026-11-26）：
  - 11:49 服务器 `git pull --ff-only` 到 `a21b8a2`；
  - 11:49–11:52 先单独构建新镜像（旧容器照常运行），避开 12:09 的 DEL 定时任务；
  - 11:53 确认没有运行中的后台任务后切换容器（`docker compose -f docker/docker-compose.yml up -d app`）。
- 每日开关 `JELLYFIN_DISPLAY_NAMES_ENABLED` 未设置，保持关闭；本次部署不会自动改任何名字。

## Testing

- 部署前 Spark 后端全量：752 passed。
- 部署后：首页 HTTP 200；`/api/jellyfin/status` 未登录返回 401（符合预期）；日志 `Application startup complete`，无报错；容器内读取配置确认显示名开关为 False。
- 只预览（`docker exec docker-app-1 python scripts/jellyfin_display_names.py --dry-run`，11:53–12:02，约 9 分钟，主要耗在读取 Jellyfin 列表）：退出码 0；待改 41074、未入库 22、跳过 0、失败 0；没有写入。示例名字符合规则（同包按文件名自然排序编号）。
- 观察：资源包目录名普遍很长，显示名可能在客户端被截断，末尾序号看不到；留到单关键词试跑时由用户在 SenPlayer 里判断。
- 单关键词试跑（用户选「何娃娃」，`--keyword 何娃娃`，12:03–12:12，8 分 38 秒）：
  - 试跑前复核：「本地已整理」库 `MetadataSavers: []`、`SaveLocalMetadata: false`；3 个资源包目录共 17 个文件、0 个 `.nfo`。
  - 结果：改名 14、合集排序 1、失败 0。耗时与只预览相当，写入本身很快，时间主要在读取列表。
  - 复核：3 个目录文件清单前后完全一致（17/17，无新增 `.nfo`）；14 个条目名字为 `何娃娃/<资源包> · 序号` 且 `LockedFields: ['Name']`；合集 `DisplayOrder: SortName`，成员按 6605 → 11935 → 29828 排列（数字按数值排序）。
  - 旁注：6605 与 11935 两个资源包里是同一组 `IMG_8741–8743`，疑似重复下载，本次不处理。
  - 幂等复核（12:12–12:21，再跑一次 `--keyword 何娃娃`）：待改 0、已正确 14、合集排序 0、失败 0（设计第八节第 3 条通过）。

---

# 续：用户验收反馈后改为序号在前（同日）

## What was done

- 用户在 SenPlayer 看「何娃娃」合集：名字被截断，看不到末尾序号，要求序号放前面。
- 显示名改为 `序号 · 关键词/资源包`。同时写入 Jellyfin 强制排序名 `关键词/资源包 · 序号`（数字补零到 10 位），避免合集按名字排序时各包的 01 排在一起交错播放（设计方决定，已写入设计文档第五节）。
- 比对规则补充：排序名不对也要写回；旧格式名字会被改成新格式；回滚时清掉强制排序名。
- 动手前只读核对（10.10.7）：列表接口 `Fields=SortName` 时返回排序名，`ForcedSortName` 未设置时不返回该键；Jellyfin 自动排序名会把中文转拼音、数字补零到 10 位。
- 文档同步：设计文档第五节、第九节，`docker/jellyfin/README.md`，`.env.example`，脚本说明。

## Testing

- 新增或修改测试均先确认失败（旧格式、缺排序名、客户端不认识新参数），再实现。
- Spark：`scripts/remote-test.sh backend tests/jellyfin -q -n 16` → 103 passed。

## Notes

- Changed files：`app/services/jellyfin/display_names.py`、`app/services/jellyfin/client.py`、`app/services/jellyfin/display_name_sync_service.py`、`tests/jellyfin/test_display_names.py`、`tests/jellyfin/test_client.py`、`tests/jellyfin/test_display_name_sync.py`、`docs/superpowers/specs/2026-11-25-jellyfin-display-names-design.md`、`docker/jellyfin/README.md`、`.env.example`、`scripts/jellyfin_display_names.py`、本日志。
- 生产上「何娃娃」的 14 条目前仍是旧格式 `何娃娃/<包> · 序号`；新版本部署后重跑 `--keyword 何娃娃` 会改成新格式。
- Rollback：回退本次提交并重建 18x；名字层面用 `--restore` 回滚。

## Notes

- Changed files：本日志（新增）。代码改动见提交 `a21b8a20`。
- 本次没有数据库迁移。
- Rollback：服务器 `git reset --hard dcc2931`（或 `git revert a21b8a20` 后推送再拉取），然后 `docker compose -f docker/docker-compose.yml up -d --build app`。生产 Jellyfin 里的名字尚未改动，无需回滚名字。
- 后续（每步需用户批准）：单关键词试跑 → SenPlayer 验收 → 普通重扫后名字保持 → 夜里全量 → 打开每日开关。
