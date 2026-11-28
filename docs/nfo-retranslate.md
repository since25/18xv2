# NFO 重新翻译使用说明

脚本：`scripts/nfo_retranslate.py`。设计说明见 `docs/superpowers/specs/2026-11-27-nfo-retranslate-design.md`。

## 用途和范围

把 302porn_tv1 里 MDC 生成的 NFO 的标题和简介，用新模型从日文原文重新翻译一遍。

- 只改 NFO 里的 `<title>`、`<outline>`、`<plot>` 三个标签，其余内容逐字节不变。
- 新标题 = `<num>` 原样 + 空格 + 译文 + 原标题末尾的 ` cdN`（有才加）。
- 新简介 = 译文 + `<br>  <br>由 {模型名} 提供翻译`，`<outline>` 写同样内容。
- 以「一部片」为单位：同一目录、同一番号的 NFO（多段、不同版本）只翻一次，写回组内每个 NFO。
- 每个字段单独判断，同时满足才翻：来源不是中文站（`airav_io`、`sehuatang`、`Madou`、`Madouqu`、`xiao_huang_shu`）；原文去掉番号后含日文假名。
- 找不到 MDC 任务的 NFO：标题不翻；简介末尾带「由 X 提供翻译」的才翻。
- 分两步：`translate` 只调模型、出报告，不碰 NFO；看过报告再 `apply` 写回。

## 配置项（`.env`）

| 变量 | 说明 |
|---|---|
| `NFO_TRANSLATE_API_BASE` | OpenAI 兼容接口地址，例如 `https://example.invalid/v1` |
| `NFO_TRANSLATE_API_KEY` | 接口密钥，只放生产 `.env` |
| `NFO_TRANSLATE_MODEL` | 模型名，同时写进简介结尾「由 X 提供翻译」 |
| `NFO_TRANSLATE_ROOT` | 302porn_tv1 的可写根目录 |
| `NFO_TRANSLATE_MDC_DB` | MDC 数据库，默认 `/app/mdc/mdc_ng.db`（只读，每次运行先复制一份） |
| `NFO_TRANSLATE_NAME_MAP` | MDC 演员对照表，默认 `/app/mdc/mapping_actor.xml`（只读） |

刷新 Jellyfin 另外用到现有的 `JELLYFIN_BASE_URL`、`JELLYFIN_API_KEY`，以及 `MEDIA_LIBRARY_STRM_ROOTS` 里含 `302porn_tv1` 的那一项（只读挂载路径，用来查 Jellyfin 条目）。

缺必要配置时脚本直接报错退出，提示缺哪一项。接口地址和密钥不会写进日志、报告和运行目录里的任何文件。

## 前提

- **要在旧版残留清理之后再跑。** `translate` 会统计找不到 MDC 任务的 NFO，超过 100 个就提示「旧版残留可能还没清」并退出；确认清理过后才加 `--force`。
- **MDC 重试会覆盖。** MDC 以后重新刮削某部片时，会用它自己的翻译覆盖这次写回的标题和简介。已接受；需要时对这些片子再跑一次。

## 用法

都在生产容器里执行。翻译耗时较长，放后台跑、输出写进日志：

```bash
# 第一步：翻译并出报告（不改 NFO）
docker exec -d docker-app-1 sh -c "python scripts/nfo_retranslate.py translate --sample 20 > data/nfo_retranslate/translate.log 2>&1"

# 看进度和结果（最后几行有运行编号、报告路径和汇总）
docker exec docker-app-1 tail -n 20 data/nfo_retranslate/translate.log

# 第二步：看过报告，把这次运行的译文写回 NFO，并逐条刷新 Jellyfin
docker exec docker-app-1 python scripts/nfo_retranslate.py apply --run 20261127-153000

# 还原：用这次写入时的备份还原 NFO，并刷新 Jellyfin
docker exec docker-app-1 python scripts/nfo_retranslate.py restore --run 20261127-153000
```

### translate 参数

| 参数 | 说明 |
|---|---|
| `--sample N` | 随机抽 N 部，试跑用 |
| `--limit N` | 取前 N 部，分批用（和 `--sample` 二选一） |
| `--fields title,plot` | 只翻哪些字段，默认两个都翻 |
| `--path-prefix 目录` | 只翻根目录下这个子目录（例如某个演员目录）；目录不存在会报错退出 |
| `--engine Google` | 只翻简介标记为「由 Google 提供翻译」的片子，先处理质量最差的旧译 |
| `--workers 8` | 并发请求数，默认 8 |
| `--resume 运行编号` | 续跑中断的那次运行：已有记录的字段不再翻；`--sample`/`--limit` 当初选中的片子不变 |
| `--redo` | 已写入记录里的 NFO 也重翻（默认跳过上次写入后没被改过的） |
| `--force` | 找不到 MDC 任务的 NFO 超过 100 个也继续 |

中断后用同样的命令加 `--resume <运行编号>` 继续。续跑时当前配置的模型必须和这次运行记下的一致，否则报错退出。

### apply 参数

| 参数 | 说明 |
|---|---|
| `--run 运行编号` | 必填，格式 `年月日-时分秒` |
| `--skip 文件` | 跳过名单：每行一个 NFO 路径或一个番号；番号跳过这次运行里这部片的全部 NFO；空行和 `#` 开头的行忽略 |
| `--no-refresh` | 不刷新 Jellyfin，写完后在 18x 里手动扫描 Jellyfin 库 |

`apply` 只写这次运行里通过检查的译文，不再调用模型。写之前核对文件和 `translate` 时的哈希，不一致（期间被 MDC 或别人改过）就跳过。汇总会分开列出：写入数、跳过名单、翻译失败不写、文件被改动或读写出错。

### restore 参数

| 参数 | 说明 |
|---|---|
| `--run 运行编号` | 必填 |
| `--no-refresh` | 不刷新 Jellyfin |

## 看报告

每次 `translate` 在运行目录生成 `report.html`，自包含单文件，用浏览器打开：

- 容器内：`data/nfo_retranslate/<运行编号>/report.html`（脚本结束时打印）
- 宿主机：`/mnt/user/docker1/18xv2/data/nfo_retranslate/<运行编号>/report.html`，可以 scp 到本机看

顶部是汇总（部数、字段数、成功、失败）和各种失败原因的数量；下面每部片每个字段一行：番号、演员、字段、日文原文、旧译文、新译文、检查结果。失败的标红并写明原因，`apply` 不写失败的字段。

## 运行目录

`data/nfo_retranslate/<运行编号>/`：

| 文件 | 内容 |
|---|---|
| `run.json` | 模型名、运行编号、命令参数、`--sample`/`--limit` 选中的片子 |
| `translations.jsonl` | 每部片每个字段一行：原文、旧译、新译、检查结果、要写的 NFO 和它们的哈希 |
| `report.html` | 报告 |
| `mdc/` | 这次运行用的 MDC 库副本 |
| `apply.jsonl` | 每次 `apply` 的写入结果、跳过原因、Jellyfin 刷新结果 |
| `backup/` | `apply` 写之前的原文件，按相对路径存放 |

跨运行的已写入记录在 `data/nfo_retranslate/applied.jsonl`：之后再 `translate` 时，上次写入后没被改过的 NFO 自动跳过已写过的字段。所以可以先 `--engine Google` 跑一批、`apply`，再不加筛选跑剩下的。

## 模型名

翻译时用的模型名记在运行目录的 `run.json` 里。`apply` 写进简介结尾的就是这个模型名，也就是报告顶部看到的那个，不看 `.env` 当前的配置。换模型要重新 `translate`，不能拿旧运行去 `apply`。

## 还原

`restore --run <运行编号>` 用这次运行的备份覆盖回去，删掉对应的已写入记录，再刷新 Jellyfin。写入后又被改过的 NFO（哈希对不上）不还原，在汇总里列出原因。

## 常见情况

- **同一次运行重复 `apply`**：前一次写过的文件会提示「translate 之后已被改动，不写」而跳过，这是正常的。重复 `restore` 也类似，已还原的文件会提示「写入后已被改动，不还原」。
- **写回中途中断，或某些条目 Jellyfin 刷新失败**：已写入的 NFO 不会因为刷新失败回滚。在 18x 里扫描 Jellyfin 库兜底即可；找不到 Jellyfin 条目的 NFO 也是同样处理。
- **`--no-refresh`**：写完后在 18x 里手动扫描 Jellyfin 库。

## 真实模型试跑

本次开发没有调用过真实翻译接口，测试全用假模型。第一次上线：

1. 先 `translate --sample 20`，看报告再决定是否 `apply`、是否调提示词或换模型。
2. 人工抽查一份真实 NFO 的演员对照表命中情况：NFO 里的演员名是 MDC 换好的 `zh_cn` 写法，脚本按 `zh_cn` 查对照表，把日文写法和别名带给模型。抽一部演员有日文名的片子，确认报告里的新译文用了中文写法。
3. 满意后对这 20 部 `apply`，在 Jellyfin 里抽查；再按 `--engine Google`、全量的顺序分批跑，每批都先看报告。
