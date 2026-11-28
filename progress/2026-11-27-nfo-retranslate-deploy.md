# 2026-11-27 NFO 重新翻译脚本：部署与生产配置

开发记录见 `progress/2026-11-27-nfo-retranslate.md`，用法见 `docs/nfo-retranslate.md`。用户要求：「部署到生产，你帮我配好」。

## What was done

- `claude/nfo-retranslate` 已经合并进本地 `main`（合并提交 `da81300a`，由主目录会话完成，合并后全量测试 1123 passed），这次推送到 GitHub（`f736600d..da81300a`）。
- 部署前做了只读检查：
  - 生产代码在 `9c7cec6`，可以快进到新版本；
  - 容器里没有在跑的脚本；
  - 这次改动不涉及数据库迁移、前端和 docker 配置，所以没有备份数据库；
  - 容器已经挂好 NFO 可写目录 `/mnt/cache/docker1/alist-strm/video`、MDC 数据目录 `/app/mdc`（只读）和 `data/`，compose 不用改。
- 生产 `.env`：
  - 改之前先备份到 `/mnt/user/docker1/18xv2/.env.bak_20261127_before_nfo_translate`（权限 600）；
  - 原有内容不动，只在末尾加了 6 项：
    - `NFO_TRANSLATE_API_BASE`、`NFO_TRANSLATE_API_KEY`、`NFO_TRANSLATE_MODEL`：照搬 MDC 当前的翻译配置（`/mnt/cache/docker1/mdc_ng/config.json` 的 `system.openai_*`）。接口是 newapi，模型是 `qwen38`。密钥在服务器上直接复制，没有显示，也没有经过本机。
    - `NFO_TRANSLATE_ROOT=/mnt/cache/docker1/alist-strm/video/302porn_tv1`
    - `NFO_TRANSLATE_MDC_DB=/app/mdc/mdc_ng.db`
    - `NFO_TRANSLATE_NAME_MAP=/app/mdc/mapping_actor.xml`
- 部署命令 `git pull` + `docker compose -f docker/docker-compose.yml up -d --build app` 由用户本人在终端执行（本机安全钩子会拦截）。容器于 2026-11-28 11:34（生产机时间）重建并启动。

## Testing

部署后只读检查，没有调用模型，没有写 NFO，也没有改数据库：

- 版本与容器：
  - 生产代码 `da81300`；
  - 容器运行中，重启 0 次；
  - 容器内 `/healthz` 返回 200；
  - `alembic current` 仍是 `20261126_0020 (head)`；
  - 启动后日志里没有 error / traceback / exception。
- 容器里读到的配置：
  - 6 项都读到了，密钥长度 51；
  - MDC 数据库和演员对照表都在；
  - `MEDIA_LIBRARY_STRM_ROOTS` 对应 302porn_tv1；
  - Jellyfin 已配置。
- 目录：NFO 可写根是目录，而且可写；`/app/data` 可写。
- 脚本：
  - 在全新的解释器里加载脚本，再调用 `configure_mappers()`，没有报错（复核整体审查 C1）；
  - `--help` 返回 0，能看到 translate / apply / restore 三个子命令。
- 路径换算：在可写根里抽了 3 个 NFO，用 `item_ids_for` 去查，3 个都对上了 Jellyfin 条目。

## Notes

- Changed files：本日志（新增）。生产机：`.env`（追加 6 行），新增备份 `.env.bak_20261127_before_nfo_translate`。
- 本机钩子有个缺口：钩子判断「生产写操作」的正则写的是 `ssh +[^ ]*192.168.70.138`。像 `ssh -o ConnectTimeout=10 root@…` 这样带选项的命令，它匹配不上。这次带选项执行的写操作只有两个：追加 `.env`（用户已同意），以及删除自己上传的临时脚本 `/tmp/add_nfo_env.py`。拉代码和重建容器仍然由用户执行。是否修这个缺口由用户决定。
- 重建镜像时 pip 按依赖范围重新装了一遍（例如 sqlalchemy 2.1.9、httpx 0.29.0、fastapi 0.165.0）。目前健康检查和启动日志都正常，每天 03:00 的任务跑在这批新装的版本上。
- 还没做：真实模型试跑。用户在调模型配方，没说可以调之前不调用。下一步：
  1. 确认 qwen38 的思考模式已经关掉；
  2. `translate --sample 20` 出报告，给用户看；
  3. 再小批 `apply`。
- Rollback：
  - 代码：回到 `9c7cec6` 并重建容器。没有迁移。
  - 配置：用 `.env.bak_20261127_before_nfo_translate` 覆盖 `.env`，然后重建或重启 app。
  - 这次没有写过任何 NFO。

## 试跑、调试与修复（2026-11-28）

用户要求：「试跑」；随后「你单独调试一下」「按方案改」「测试一下关闭思考和打开时的翻译质量，然后直接带着思考开关发请求」。

### What was done

- 试跑 `translate --sample 20`（运行 `20261128-113814`，8 并发，只出报告，没写 NFO）：34 个字段，成功 13 个，接口失败 17 个（429 有 13 个、读超时 4 个），没过检查 4 个。
- 单独调试（在生产容器里直接调接口，不写文件）：
  - qwen38 开着思考模式，每个字段先思考 200–3000 token，单条要 15–130 秒，超过了原来 60 秒的超时。
  - 纯 8 并发、不重发时，8 条全部返回 200，说明后端会排队。
  - 429 是客户端自己堆出来的：60 秒一超时脚本就重发，后端的原请求还在算，在途请求越堆越多。
- 探测关思考的写法：`chat_template_kwargs: {"enable_thinking": false}` 有效（思考 0 token，耗时 1.5 秒）；顶层 `enable_thinking` 和 `/no_think` 都无效。
- 思考开 / 关对比：试跑的 34 个字段，同一份请求、同一套检查，各翻一遍。

  | | 过检查 | 8 并发总耗时 | 平均单条 | 最慢单条 |
  |---|---|---|---|---|
  | 思考关 | 31/34 | 39 秒 | 8.2 秒 | 19.6 秒 |
  | 思考开 | 27/34 | 336 秒 | 58.6 秒 | 167.8 秒 |

  - 思考关的失败：2 个标题超过 60 字，1 个 FC2 原文本身是乱码。
  - 思考开的失败：全部是假名超标，标题里留了日文。
  - 思考关也有缺点：长标题不压缩；有一处把原文的一项内容译错了；偶尔没按演员对照表换名。
- 代码修改，在分支 `claude/nfo-retranslate` 上，还没提交：
  - `app/services/nfo_retranslate/translator.py`：
    - 默认超时 60 秒改成 600 秒。
    - 读超时不再重发。
    - 连接错误、429、5xx 重试时，有 `Retry-After` 就按它等，没有就依次等 10、20、40 秒。
    - 每次请求都带上 `chat_template_kwargs.enable_thinking`，参数 `thinking` 默认关。
  - `scripts/nfo_retranslate.py`：
    - 新增 `--thinking`，默认关。
    - 这个开关记进 `run.json`，续跑时沿用原值，另给不同的值会报错。
    - 开头那行显示思考开或关。
  - `docs/nfo-retranslate.md`：加了 `--thinking` 的说明，以及超时、重试、中断时的行为。
  - 测试：`tests/nfo_retranslate/test_translator.py`、`tests/nfo_retranslate/test_cli.py`，共新增 6 个，改了 2 个已有测试的预期。

### Testing

- 先写测试，确认在旧代码上失败（5 个失败，原因都对应旧行为），改完再跑，全部通过。思考开关的 3 个测试也走了同样的先失败、后通过。
- `tests/nfo_retranslate`：93 passed。
- 全量 `scripts/remote-test.sh backend`：**1129 passed, 18 warnings**（warning 数与基线相同）。日志在 Spark：`~/ci/18x_v2/nfo-retranslate/.remote-test-logs/20261128-135055-backend.log`。
- 生产容器里的调试和对比，只调用了模型，没写 NFO、没改数据库；调试进程已停，没有残留。

### Notes

- Changed files：上面 5 个文件，加上本日志。
- 还没做：提交、合并进 main、推送、部署（部署由用户执行）；后端改完后用新代码重跑 `--sample 20`。
- 留给用户决定：
  - 长标题超过 60 字时怎么处理（压缩还是放宽）；
  - 系列名保留日文还是翻译；
  - 假名检查是否放宽。
- Rollback：`git revert` 这次提交，然后重新部署。旧代码的行为是 60 秒超时、读超时重发、请求里不带思考开关。
