# 脚本中心

18x 的「脚本中心」页面（路由 `/script-runs`）负责三个定时脚本：调度、执行、停止、监控、看日志、调参数。

| 脚本 | 页面名称 | 默认时间 | 本阶段能否由 18x 执行 |
|---|---|---|---|
| `sehuatang` | 色花堂抓取 | 01:28 | 能 |
| `MOVE_SSD_CACHE_TO_DISK2` | 搬运脚本 | 01:01 | 还不能（第二段） |
| `DEL_SOMETHING` | 整理脚本 | 12:09 | 还不能（第三段） |

设计见 `docs/superpowers/specs/2026-11-25-scripts-into-18x-design.md`。

## 工作方式

- 每个脚本都有一个“执行方”：
  - `unraid`：仍由 Unraid User Scripts 定时运行。18x 只接收回报（MOVE、DEL 沿用 `docs/unraid-script-reports.md`），按运行时间提醒漏跑，并且只允许在页面上演练。
  - `18x`：由 18x 定时运行。
- 18x 每次运行都起一个独立子进程（自成进程组）。日志、输入和结果文件放在 `SCRIPT_JOBS_DIR/<脚本>/<运行 ID>/`，保留 30 天。
- 调度规则：
  - 到点运行；预定时间后 2 小时内，18x 恢复或任务被中断都会补跑；超过 2 小时不补跑。
  - 预定时间之后才改的配置（切换执行方、改运行时间、开关定时等）当天不补跑，第二天起按新配置运行，避免同一天 Unraid 和 18x 各跑一次。
  - 手动运行和演练不影响当天的定时运行。
  - 失败不自动重试。
- 互斥：同一个脚本同时只跑一次；MOVE 和 DEL 互斥，后到的排队。
- 停止：先发 SIGTERM，30 秒后仍在运行就 SIGKILL。
- 超时：sehuatang 60 分钟，MOVE 6 小时，DEL 3 小时。超时记为失败。
- 18x 重启：先结束上次留下的子进程，再把未完成的运行标为“已中断”。

## 环境变量

只写变量名，值放生产 `.env`，不要写进文档或仓库。

| 变量 | 说明 |
|---|---|
| `QB_URL` | sehuatang 提交种子用的 qB WebAPI 地址，含协议和端口 |
| `QB_USERNAME` / `QB_PASSWORD` | qB 账号；页面不显示 |
| `SCRIPT_JOBS_DIR` | 可选，默认 `data/script-jobs` |
| `SEHUATANG_SESSION_PATH` | 可选，默认 `data/sehuatang/site_session.json`；站点 cookie 和 User-Agent 存在这里（权限 0600） |

旧配置项 `SCRIPT_REPORT_SCHEDULES` 已不再使用，运行时间统一在页面设置里改。生产 `.env` 里留着它也没关系。

## qB 广告文件排除

国产BT 种子几乎每个都夹带同样的广告文件。2026-11-25 起，在 qB（qbittorrentbt，v4.6.7）的“设置 → 下载 → 排除文件名”里开启了以下规则，匹配的文件自动设为“不下载”，对所有分类的新种子生效（磁力在拿到文件列表后生效）：

```text
*台湾uu美少女直播*
*社 區 最 新 情 報*
*最 新 位 址 獲 取*
*聚 合 全 網 H 直 播*
```

出现新的广告文件名时，在这里补规则。DEL 的黑名单里仍保留这些广告词，用来清理其他来源的下载和旧文件。

## 页面操作

- **卡片**：显示执行方或每天的运行时间、上次结果和正在运行的情况。按钮有立即运行（仅执行方为 18x 时）、演练、停止、看日志、设置，每个操作都要再确认一次。
- **设置**：可以改执行方、定时开关、运行时间。sehuatang 另可改抓取页数（1–20）、版块地址（必须含 `{page}`）和 qB 分类。MOVE、DEL 的参数本阶段只能查看。
- **站点 cookie**（sehuatang 设置里）：
  - 在已登录站点的浏览器里复制整段 Cookie 和该浏览器的 User-Agent，一起粘贴保存。
  - 页面只显示“已设置 / 最后更新时间”，不回显内容。
- **红条**：sehuatang 最近一次结束的运行失败时（例如“站点 cookie 可能失效”），页面顶部显示原因，直到下一次成功。
- **运行记录**：展开一行可以看名单。18x 执行的运行另有「日志」页签。

## sehuatang 的处理流程

1. 按配置抓列表页。
2. 标题用 18x 黑名单过滤。词条的规范名和别名都参与；匹配时先全角转半角、去掉空格、不分大小写，至少 2 个字的词才算。
3. 以前已经成功提交过的帖子跳过，不再进帖子页。
4. 进帖子页取种子附件和磁力。
5. 有种子时，用黑名单检查种子名（多文件种子是顶层文件夹名）。种子里夹带的广告文件不拦整个种子：qB 开了“排除文件名”，广告文件不会下载；漏网的由 DEL 清理。
6. 通过 qB 接口提交到配置的分类。有种子就提交种子，没有才提交磁力，不再往 qB 监视目录放文件。
7. 判定站点 cookie 可能失效：列表页全部失败、遇到 Cloudflare 挑战，或者一个帖子都没抓到。
8. qB 登录失败或没配置 qB 时，本次记为失败，帖子不会被标成已提交，第二天会重试。

## 部署前检查

部署会重启 18x，正在运行的脚本会被中断（页面标“已中断”）。部署前先在页面上确认没有“运行中”或“排队中”的卡片。

## sehuatang 切换运行手册

每一步都要用户批准后再做。

1. **8 个 AI 词的只读预估**（只读，可直接做）

   在 DEL 的 3 个删除目录下，列出名字里含这 8 个词的目录和文件。匹配区分大小写，和 DEL 一致：

   ```bash
   find /mnt/cache/docker1/SSD_cache /mnt/disk2/qbbtdn/00000000000000000/scripts /mnt/disk2/qbbtdn/已整理 \
     \( -name '*AI增强*' -o -name '*AI增強*' -o -name '*AI強化*' -o -name '*AI强化*' \
        -o -name '*AI放大*' -o -name '*AI修复*' -o -name '*AI修復*' -o -name '*AI生成*' \) -print
   ```

   结果给用户看。
2. **加词**（需批准）：在 18x「关键词」页新增 8 个黑名单词条，备注写“来源：sehuatang 标题黑名单，2026-11 合并”。加完后，Unraid 上的 DEL 下一次运行（12:09）就会按这 8 个词删除。
3. **备份数据库并部署**（需批准）：迁移会自动升到 `20261125_0018`。
4. **配置 qB 凭证**（需批准）：在生产 `.env` 写入 `QB_URL`、`QB_USERNAME`、`QB_PASSWORD`，然后重启 app 容器。由用户本人填，或经用户同意从 Unraid 上原 `gc.py` 里复制。
5. **设置站点 cookie**：用户在页面「设置」里粘贴 cookie 和浏览器 User-Agent。
6. **导入最近 14 天已提交的帖子编号**：只读 CSV，可以重复运行。

   ```bash
   docker exec docker-app-1 mkdir -p /tmp/sehuatang-csv
   ls -t /mnt/user/docker1/python/scripts/PYTHON_SEHUATANG/shuhuatang_*.csv | head -15 \
     | xargs -I{} docker cp {} docker-app-1:/tmp/sehuatang-csv/
   docker exec docker-app-1 python scripts/seed_sehuatang_posts.py --csv-dir /tmp/sehuatang-csv --days 14
   docker exec docker-app-1 rm -rf /tmp/sehuatang-csv
   ```

7. **演练对比**：在 18x 里演练 sehuatang，和 Unraid 当天的 `log.txt` 对比。把“标题被拦”的名单给用户检查有没有误拦。
8. **切换执行方**（需批准）：先在 Unraid User Scripts 把 `sehuatang` 的定时改成 disabled，再在 18x 设置里把执行方改成 18x 并启用定时。如果在当天预定时间之后切换，18x 当天不会补跑，第二天起才运行。
9. **次日核对**：01:28 后在页面上看运行记录和名单，并在 qB 的「国产BT」分类里确认任务已加入。

## 回滚

- **单个脚本**：在 18x 设置里把执行方改回 Unraid（或者关掉定时开关），再在 Unraid 上恢复定时。`/boot` 下的原脚本没有改动。
- **8 个 AI 词**：在关键词页停用这些词条。
- **18x 整体**：顺序不能反，否则旧版容器启动时找不到 0018 迁移，会反复重启。
  1. 先用**新版本**的容器降级：`docker exec docker-app-1 alembic downgrade 20261102_0017`。这会删除脚本中心的三张新表和运行记录的新字段，同时删除 18x 自己执行产生的运行记录和名单（旧版本只认识 Unraid 回报），Unraid 回报的记录保留。
  2. 再回退代码版本并重建容器。
