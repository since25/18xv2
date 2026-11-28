# 2026-11-27 NFO 重新翻译脚本（开发完成，未部署）

用户要求：不走 MDC「重试」（会重抓全部站点），在 18x 里写脚本，直接从选定范围的 NFO 里取日文原文交给新模型翻译、带并发，再写回 NFO；只管非中文站抓取（机器翻译）的字段。设计说明 `docs/superpowers/specs/2026-11-27-nfo-retranslate-design.md`，实施计划 `docs/superpowers/plans/2026-11-27-nfo-retranslate.md`，使用说明 `docs/nfo-retranslate.md`。

## What was done

- 分支 `claude/nfo-retranslate`（从本地 main `f736600d` 切出，独立工作区），按 7 个任务逐个实现、逐个审查，最后整支分支审查并修复一批问题。没有合并、没有推送、没有部署。
- 新增命令行 `scripts/nfo_retranslate.py`，三个子命令：
  - `translate`：快照 MDC 库（临时目录，读完即删）→ 按字段来源判断范围（中文站 `airav_io`、`sehuatang`、`Madou`、`Madouqu`、`xiao_huang_shu` 不翻）→ 同番号多份 NFO 共用一份译文 → 并发调用 OpenAI 兼容接口（失败重试、可中断）→ 输出检查（字数、假名占比、标题长度、简介长度比例、拒答、思考标签、重复番号、标题换行）→ 写 `translations.jsonl` 和对比报告 `report.html`。不碰 NFO。支持 `--sample/--limit/--fields/--path-prefix/--engine/--workers/--resume/--redo/--force`；翻译时的模型名和参数记进 `run.json`，续跑沿用原参数。
  - `apply --run`：只写报告覆盖过的那份记录（指纹核对），只替换 `<title>`、`<outline>`、`<plot>`，其余字节不变；写前备份、原子写入、记 `apply.jsonl` 和跨运行的 `applied.jsonl`；然后逐条刷新 Jellyfin（`FullRefresh + ReplaceAllMetadata`，不换图）。`--skip` 文件可写 NFO 路径或番号。
  - `restore --run`：文件写入后没被改过才用备份还原，并刷新。
- 模块在 `app/services/nfo_retranslate/`：`nfo_file.py`、`scope.py`、`prompts.py`（系统提示词、演员对照表、输出检查）、`translator.py`、`runs.py`、`report.py`、`apply_service.py`；`JellyfinClient.refresh_item`；配置项 `NFO_TRANSLATE_API_BASE/API_KEY/MODEL/ROOT/MDC_DB/NAME_MAP`（`.env.example` 已加，生产 `.env` 未配）。
- 开发过程没有调用过真实翻译接口、没有连 Jellyfin、没有碰生产机（用户在调模型配方、并发和权重格式）。

## Testing

- 每个任务只跑本任务测试（Spark，`scripts/remote-test.sh`），全部通过；任务 7 时跑过一次全量。
- 最终版本 `31ea68a0`：`tests/nfo_retranslate` 87 passed；全量 `scripts/remote-test.sh backend` → **1123 passed, 18 warnings**（warning 数与开工前基线相同），日志 Spark `~/ci/18x_v2/nfo-retranslate/.remote-test-logs/20261128-105540-backend.log`。
- 审查：7 个任务各有规格 + 质量审查（任务 3、4、7 各返工 1 轮，任务 6 送审前修 1 处），整支分支审查发现 1 个严重问题（脚本单独运行时缺模型导入、刷新必崩）和 5 个重要问题，已一次修完并复审通过。
- 未验证：真实模型输出、真实 MDC 库与生产 NFO、真实 Jellyfin 刷新（测试中都用假对象）。这些要在试跑时看。

## Notes

- Changed files（28 个，全部新增或追加）：`.env.example`、`app/core/config.py`、`app/services/jellyfin/client.py`、`app/services/nfo_retranslate/`（8 个文件）、`scripts/nfo_retranslate.py`、`scripts/README.md`、`docs/nfo-retranslate.md`、设计说明与计划各 1、`tests/jellyfin/test_client.py`、`tests/nfo_retranslate/`（10 个文件含 2 个样例 NFO）、本日志。
- 上线前要做（每步需用户同意）：合并进 main → 部署 → 生产 `.env` 配 6 个配置项（密钥由用户填或同意后填）→ 确认模型思考模式已关闭 → `translate --sample 20` 试跑看报告 → `apply` 小批 → 再按 `--engine Google`、全量分批。
- 试跑时专门看：多段 `cdN` 片子标题（`originaltitle` 若也带 `cdN` 会出现「cd1 cd2」）、`<num>` 含空格和日文的片子、FC2 自闭合简介、演员对照表命中（按 `zh_cn` 查）、失败原因里「假名占比」的数量（系列名/栏目名保留日文可能误判短标题，可改为同时去掉系列和片商名）。
- 留待以后的小问题：续跑时命令行给的 `--force` 不生效（只取原运行的）；`--fields` 等价写法会被判冲突；模型输出小写或带括号的番号不会被去掉；restore 会连带删掉更早运行的已写入记录（只会多翻，不丢数据）；失败字段续跑不重翻（先 apply 再开新运行即可）。
- MDC 里点「重试」会覆盖这次写回的结果；要在旧版残留清理之后再跑（文档已写）。
- Rollback：代码未合并，丢弃分支即可；合并后可 `git revert`。NFO 层面：`restore --run <编号>` 按备份还原（文件写入后又被改过的会跳过），备份在 `data/nfo_retranslate/<编号>/backup/`。
