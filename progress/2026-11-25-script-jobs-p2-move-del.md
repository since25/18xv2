# 2026-11-25 脚本中心第二、三段：MOVE + DEL 搬进 18x（代码）

## What was done

- 计划：`docs/superpowers/plans/2026-11-25-script-jobs-p2-move-del.md`，用户批准后在独立工作区 `worktree-script-jobs-p2-move-del` 按 Native 执行，7 个任务。
- **原脚本入库**：从 Unraid 只读拷贝，先原样提交，再提交改动，方便逐行核对。
  - MOVE：`scripts/jobs/move_ssd_cache_to_disk2.sh`。
  - DEL：`scripts/jobs/del_something/` 下的 `delete_files.py`、`local_organize_from_whitelist.py`。两个 Python 文件的 md5 与生产一致；telegram 版整理脚本只差默认扫描目录，没有单独入库。
- **MOVE**：
  - 只改三处：目录改由环境变量传入、去掉日报回报片段、`chown -R 99:100`。
  - 18x 用 bash 运行它，演练时加 `--dry-run`。
- **DEL**：
  - `app/services/script_jobs/del_main.py` 按原 bash 外壳的顺序编排：先删除，再逐条整理，最后修正权限 `99:100`。
  - 任一脚本失败就以相同退出码结束；保留 `umask 077`。
- **关键词**：18x 每次运行前把启用的黑名单、白名单按 `/api/keywords` 的格式导出成文件。脚本只把“取一页数据”的来源换成这个文件，过滤和匹配代码没有改。子进程不再拿到关键词接口的账号。
- **解析**：
  - 阶段 6 的解析器搬进 `app/services/script_jobs/media_output.py`。
  - 新增 DEL 演练名单解析，列出“将删除 / 将移动”。
  - 修了一个旧问题：DEL 每条整理任务结束都打印一次 `[SUMMARY]`，旧解析器读到第一段就不再计数，导致后面 6 条整理任务的移动和错误没进名单。
- **执行框架**：MOVE、DEL 设为可在 18x 执行，并接上启动、收尾和打断后找回已完成部分的处理。
- **容器挂载**：`docker/docker-compose.yml` 改为挂载 `/mnt/cache/docker1/SSD_cache` 和 `/mnt/disk2/qbbtdn`。原来单独挂的 `已整理` 已被包含，Jellyfin 用的路径不变。
- **页面**：设置抽屉里可以改 MOVE 的源目录和目标目录；DEL 可以改删除目录、整理任务、同名合并、修正权限。
- **文档**：`docs/script-jobs.md` 补了处理流程、MOVE / DEL 切换手册和回滚；`docs/unraid-script-reports.md` 写明仓库里的回报脚本不能再单独复制到 Unraid。

## Testing

- 新增真实子进程测试，在临时目录上运行，`chown` 用 PATH 里的假命令代替：
  - MOVE 的移动、合并、去重、`_新版本`、类型冲突、演练不改动，以及权限参数是 `99:100`；
  - DEL 的删除、整理、扫描目录不存在时跳过、黑名单为空时中止、演练不改动、关闭修正权限；
  - 路径里带空格、引号、`$` 的情况。
- 关键词导出和接口逐页拼接的结果完全一致；两个脚本读文件时不发网络请求。
- 每项新测试都先确认失败、再改到通过。
- 整体审查：另起审查员通读了整条分支，没有 Critical；确认原脚本的判定规则没被改动。
- 修了 3 个 Important 和 1 个会让手册跑不通的问题，每个都先写测试、确认失败，再改到通过：
  - 删除目录名里有英文逗号时会被 csv 拆开，可能删到别的目录。改为用 `csv.writer` 写入。
  - MOVE 被停止或超时后，已移动的数量找不回来。改为按日志逐行计数。
  - `[MERGED]`、`[AMBIGUOUS]` 会被计成未识别行。现在分别计为移动和歧义。
  - 手册里的演练对比缺了载入 `.env` 账号那一步，已补上。
- 修完后全量（`scripts/remote-test.sh all`）：后端 718、前端 143 全部通过，build、lint 也通过。
- 暂缓的两个小问题：
  - 关掉“修正权限”后，新建的分类目录是 0700（照搬原外壳的 `umask 077`），共享和 Jellyfin 读不到；
  - 路径首尾的空格会被去掉，与生产行为一致。

## Notes

- 待用户批准后再做：合并回 main、推送、部署（含挂载变更），以及按 `docs/script-jobs.md` 的 MOVE / DEL 切换手册逐步切换。本日志只记录代码。
- 我替用户做的决定：
  - 演练不修正权限。Unraid 原外壳在演练时也会 `chown`，所以两边演练日志会差几行“修正权限”。
  - 修正权限失败时继续处理其他目录，最后返回 1。原外壳遇到失败会立即退出。
  - 关键词由 18x 导出成文件，不让脚本登录接口取。
- Changed files：
  - `scripts/jobs/**`
  - `app/services/script_jobs/{media_output,media_task,del_main,definitions}.py`
  - `scripts/unraid/report_script_run.py`
  - `docker/docker-compose.yml`
  - `frontend/src/pages/scriptCenter/JobSettingsDrawer.tsx`
  - `docs/script-jobs.md`、`docs/unraid-script-reports.md`
  - `tests/script_jobs/*`
- Rollback：代码回退这条分支上的提交即可。没有数据库迁移。挂载的回滚见 `docs/script-jobs.md` 的“回滚”。
