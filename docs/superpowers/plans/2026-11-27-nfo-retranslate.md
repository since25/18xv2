# 115 番号库 NFO 重新翻译脚本 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 18x 里新增 `scripts/nfo_retranslate.py`：从 302porn_tv1 的 NFO 取日文原文，带上演员对照等参考信息并发调用翻译模型，先出对比报告，确认后只把标题和简介写回 NFO，并让 Jellyfin 重读。

**Architecture:** 逻辑放在新包 `app/services/nfo_retranslate/`，按职责分成 NFO 读写、范围判断、提示词与检查、模型调用、运行记录与报告、写回与还原六个模块；脚本只解析参数、串流程。Jellyfin 客户端加一个单条刷新方法。不改数据库结构、不加接口和页面。

**Tech Stack:** Python 3、httpx（同步，`MockTransport` 测试）、`concurrent.futures.ThreadPoolExecutor`、`xml.etree.ElementTree`（只用来读，不用来写）、sqlite3（读 MDC 库副本）、SQLAlchemy（查 `jellyfin_media_items`）、pytest。

**Spec:** `docs/superpowers/specs/2026-11-27-nfo-retranslate-design.md`（执行者先读它，本计划按它展开）

## Global Constraints

- 代码注释、docstring、文档、输出提示一律中文。
- 测试不在本机跑：`scripts/remote-test.sh backend tests/nfo_retranslate -q`（会同步含未提交改动的当前检出到 Spark）。全量：`scripts/remote-test.sh backend`。
- 不提交、不切分支、不建 worktree（用户全局约定）。全部做完后统一问用户是否提交，只 `git add` 本计划涉及的文件；`progress/2026-11-27-mdc-nfo-fix-trial.md` 属于另一个会话，不要带上。
- 只改 NFO 里的 `<title>`、`<outline>`、`<plot>` 三个标签，其余逐字节不变；不用 XML 库重新序列化文件。
- 中文站来源名单（精确值）：`airav_io`、`sehuatang`、`Madou`、`Madouqu`、`xiao_huang_shu`。
- 简介结尾格式（精确值）：`<br>  <br>由 {模型名} 提供翻译`（`<br>` 两个、中间两个空格）；`<outline>` 写和 `<plot>` 相同的内容。
- 新标题 = `<num>` 原样 + 一个空格 + 译文 + 原标题末尾的 ` cdN`（有才加）。
- MDC 任务路径前缀：`/302video/302porn_tv1`。
- 输出检查阈值（精确值）：去空白后少于 2 字失败；假名占比 > 15% 失败；标题 > 60 字失败；简介长度 < 原文 20% 或 > 原文 3 倍失败。
- 找不到 MDC 任务的 NFO 超过 100 个时，`translate` 不加 `--force` 就退出。
- Jellyfin 单条刷新参数（精确值）：`MetadataRefreshMode=FullRefresh`、`ImageRefreshMode=Default`、`ReplaceAllMetadata=true`、`ReplaceAllImages=false`。
- 运行目录：`data/nfo_retranslate/<运行编号>/`，运行编号 `%Y%m%d-%H%M%S`；跨运行的已写入记录：`data/nfo_retranslate/applied.jsonl`。
- 翻译接口地址和密钥不得出现在日志、报告、`translations.jsonl` 里。
- 新配置（`.env`）：`NFO_TRANSLATE_API_BASE`、`NFO_TRANSLATE_API_KEY`、`NFO_TRANSLATE_MODEL`、`NFO_TRANSLATE_ROOT`、`NFO_TRANSLATE_MDC_DB`（默认 `/app/mdc/mdc_ng.db`）、`NFO_TRANSLATE_NAME_MAP`（默认 `/app/mdc/mapping_actor.xml`）。只读路径沿用 `MEDIA_LIBRARY_STRM_ROOTS`。

## Review Focus

1. **自闭合的空标签**：MDC 会写出 `<plot />`、`<outline/>`（FC2 条目里见过）。替换时要能把它们换成带 CDATA 的完整标签，其他字节不变。→ Task 1 `test_replace_self_closing_tags`。
2. **原简介里的 XML 转义**：`<originalplot>` 不用 CDATA，`&amp;`、`&lt;` 是转义的。发给模型的必须是还原后的文本，写回时（CDATA 内）不能再出现 `&amp;amp;`。→ Task 1 `test_read_nfo_unescapes_original_plot`。
3. **模型输出里带 `]]>`**：直接写进 CDATA 会截断标签，导致 NFO 解析失败。→ Task 1 `test_replace_escapes_cdata_terminator`。
4. **翻译中途断掉**：`translations.jsonl` 最后一行可能只写了一半。`--resume` 读取时要跳过坏行，并重翻那一组，不能整次报错。→ Task 5 `test_load_translations_skips_truncated_line`。
5. **某个条目 Jellyfin 刷新失败**：不能中断其余条目，NFO 也不回滚，只记录。→ Task 6 `test_refresh_failure_is_recorded_not_raised`。

另：标题里保留的日文素人昵称会推高假名占比。计算假名占比前，先去掉本片演员名（NFO 演员名和对照表里的所有写法）。这是本计划对设计第 5.4 节的细化，Task 3 有测试。

---

### Task 1: 配置项与 NFO 读写

**Files:**
- Modify: `app/core/config.py`（在女优配置块之后加一组 `nfo_translate_*` 字段）
- Modify: `.env.example`（加同名空配置并写中文注释）
- Create: `app/services/nfo_retranslate/__init__.py`
- Create: `app/services/nfo_retranslate/nfo_file.py`
- Test: `tests/nfo_retranslate/__init__.py`、`tests/nfo_retranslate/test_nfo_file.py`
- 样例：`tests/nfo_retranslate/fixtures/sample.nfo`：照生产 `MIAA-759.nfo` 的结构脱敏改写，含 CDATA 标题和简介、转义的原简介、两个 `<actor>`；`sample_selfclosing.nfo`：`<plot />` 和 `<outline/>` 都是自闭合

**Interfaces:**
- Produces:
  - `Settings.nfo_translate_api_base: str | None`、`nfo_translate_api_key: str | None`、`nfo_translate_model: str | None`、`nfo_translate_root: str | None`、`nfo_translate_mdc_db: str = "/app/mdc/mdc_ng.db"`、`nfo_translate_name_map: str = "/app/mdc/mapping_actor.xml"`
  - `class NfoError(Exception)`
  - `@dataclass(frozen=True) class NfoDoc: path: str; raw: str; sha256: str; num: str; title: str; original_title: str; plot: str; original_plot: str; actors: tuple[str, ...]; studio: str; series: str`
  - `read_nfo(path: str) -> NfoDoc`：读不了或解析失败抛 `NfoError`
  - `split_title(title: str, num: str) -> tuple[str, str] | None`：返回 `(正文, 分段后缀)`，例如 `("刚订婚的我…", " cd2")`；`title` 不以 `num + " "` 开头时返回 `None`
  - `strip_num(text: str, num: str) -> str`：去掉开头的 `num` 和空白；不以 `num` 开头就原样 strip
  - `translator_marker(plot: str) -> str | None`：取「由 X 提供翻译」里的 X
  - `plot_body(plot: str) -> str`：去掉翻译标记那段，`<br>` 各种写法换成 `\n`，再 strip
  - `build_title(num: str, translated: str, part_suffix: str) -> str`
  - `build_plot(translated: str, model: str) -> str`：`\n` 换成 `<br>`，再接上结尾标记
  - `replace_fields(raw: str, *, title: str | None, plot: str | None) -> str`：`None` 表示这个字段不动；`plot` 同时写 `<outline>` 和 `<plot>`
  - `sha256_text(text: str) -> str`
  - `atomic_write(path: str, content: str) -> None`：硬链接数 > 1 时抛 `NfoError("NFO 有硬链接")`；`content` 不能被 XML 解析时抛 `NfoError`，原文件不动

- [ ] **Step 1: 写失败的测试**（`tests/nfo_retranslate/test_nfo_file.py`）
  - `test_read_nfo_fields`：读样例，`num == "MIAA-759"`，`actors == ("西田那津", "森泽佳奈")`，`studio == "MOODYZ"`，`translator_marker(doc.plot) == "OpenAI"`。
  - `test_read_nfo_unescapes_original_plot`：样例原简介含 `&amp;` 和 `&lt;br&gt;`，`doc.original_plot` 里是 `&` 和 `<br>`。
  - `test_split_title_variants`：
    - `split_title("MIAA-759 刚订婚 cd2", "MIAA-759") == ("刚订婚", " cd2")`；
    - `split_title("2017-11-18 MIDE-488 新人！ 新人出道", "2017-11-18 MIDE-488 新人！") == ("新人出道", "")`；
    - `split_title("别的开头", "MIAA-759") is None`。
  - `test_strip_num_and_plot_body`：`strip_num("MIAA-759 婚約 森沢かな", "MIAA-759") == "婚約 森沢かな"`；`plot_body("第一段<br>第二段<br>  <br>由 Google 提供翻译") == "第一段\n第二段"`。
  - `test_build_title_and_plot`：`build_title("ABC-001", "新标题", " cd1") == "ABC-001 新标题 cd1"`；`build_plot("甲\n乙", "qwen38") == "甲<br>乙<br>  <br>由 qwen38 提供翻译"`。
  - `test_replace_fields_only_touches_three_tags`：替换后去掉这三个标签所在的行，剩下的内容和原文逐字节相同；`<title>` 内容是 `<![CDATA[新标题]]>`；`<outline>`、`<plot>` 两个标签内容相同；结果能被 `ET.fromstring` 解析。
  - `test_replace_fields_none_keeps_field`：`title=None` 时 `<title>` 行和原文相同。
  - `test_replace_self_closing_tags`（Review Focus 1）：自闭合样例替换后，`<plot>`、`<outline>` 都有内容，能解析，其余行不变。
  - `test_replace_escapes_cdata_terminator`（Review Focus 3）：`plot` 里含 `a]]>b`，结果能解析，读回的 plot 文本仍含 `a]]>b`。
  - `test_atomic_write_keeps_mode_and_rejects_bad_xml`：在 `tmp_path` 里建一个权限 `0o666` 的文件，写入合法内容后权限还是 `0o666`、属主不变；写入不合法 XML 抛 `NfoError`，原内容不变。
  - `test_atomic_write_refuses_hardlink`：`os.link` 出第二个链接后写入，抛 `NfoError`。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_nfo_file.py -q`
  Expected: 失败，原因是 `ModuleNotFoundError: app.services.nfo_retranslate`

- [ ] **Step 3: 实现**
  - 配置字段照 `actress_*` 的写法用 `Field(alias=...)`，每个加一行中文注释；`.env.example` 加同名项。
  - `read_nfo` 用 `ET.fromstring` 读值（这样转义能还原），`raw`、`sha256` 取文件原文。
  - `replace_fields` 用正则定位：带内容的 `<tag>…</tag>`（非贪婪，可跨行）、自闭合 `<tag\s*/>` 两种写法，`tag ∈ {title, outline, plot}`，各替换第一个出现的位置。新内容写成 `<tag><![CDATA[…]]></tag>`；内容里的 `]]>` 拆成 `]]]]><![CDATA[>`。
  - `atomic_write`：
    1. 检查 `st_nlink`；
    2. 先 `ET.fromstring` 校验内容；
    3. 在同目录用 `tempfile.mkstemp` 写临时文件；
    4. `os.chmod` 和 `os.chown` 成原文件的权限和属主；
    5. `os.replace` 替换原文件。
    中途出错时删掉临时文件。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_nfo_file.py -q`
  Expected: 全部 PASS

---

### Task 2: 范围判断（MDC 库副本、分组、字段是否要翻）

**Files:**
- Create: `app/services/nfo_retranslate/scope.py`
- Test: `tests/nfo_retranslate/test_scope.py`（测试里用 sqlite3 现建一个只有 `task` 表（`id`, `primary_task_id`, `target_path`, `metadata_provider_info`）的小库）

**Interfaces:**
- Consumes: `NfoDoc`、`read_nfo`、`strip_num`、`translator_marker`、`plot_body`（Task 1）
- Produces:
  - `CN_SOURCES: frozenset[str]`
  - `@dataclass(frozen=True) class FieldSources: title: str | None; outline: str | None`
  - `snapshot_mdc_db(db_path: str, workdir: str) -> str`：把库和存在的 `-wal` 复制到 `workdir`，返回副本路径；源库不存在抛 `FileNotFoundError`
  - `load_task_sources(db_copy: str, root: str) -> dict[str, FieldSources]`：键是 NFO 绝对路径（`target_path` 的前缀 `/302video/302porn_tv1` 换成 `root`，`.strm` 换成 `.nfo`）；子任务用主任务的 `Title`、`Outline` 来源
  - `@dataclass class FilmGroup: key: str; docs: list[NfoDoc]`（`key = "<相对目录>|<num>"`）
  - `group_films(root: str, *, path_prefix: str | None = None) -> tuple[list[FilmGroup], list[tuple[str, str]]]`：返回分组和 `(读不了的 NFO 路径, 原因)`；组和组内 NFO 都按路径排序
  - `has_kana(text: str) -> bool`
  - `field_in_scope(field: Literal["title", "plot"], doc: NfoDoc, sources: FieldSources | None) -> bool`
  - `count_orphans(groups: list[FilmGroup], sources: dict[str, FieldSources]) -> int`
  - `group_matches_engine(group: FilmGroup, engine: str) -> bool`

- [ ] **Step 1: 写失败的测试**
  - `test_load_task_sources_maps_paths_and_children`：主任务 `Title=dmm`、`Outline=airav_io`，子任务（cd2）的 NFO 路径得到同样的来源。
  - `test_field_in_scope_title`：来源 `dmm` 且原标题含假名 → True；来源 `airav_io` → False；`sources=None` → False；原标题去番号后没有假名 → False。
  - `test_field_in_scope_plot_without_task_uses_marker`：`sources=None`、简介带「由 Google 提供翻译」、原简介含假名 → True；不带标记 → False。
  - `test_group_films_groups_parts_and_versions`：同目录 `ABC-001-cd1.nfo`、`ABC-001-cd2.nfo`、`ABC-001-C.nfo`（`<num>` 都是 `ABC-001`）归为一组；另一目录单独成组；坏 XML 进第二个返回值。
  - `test_count_orphans_and_engine_filter`：3 个 NFO 里 1 个不在 `sources` → `count_orphans == 1`；`group_matches_engine(group, "Google")` 只在组内有 Google 标记时为 True。
  - `test_snapshot_copies_wal`：建库、写入后不 checkpoint，复制出的副本能读到刚写的行。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_scope.py -q`
  Expected: 失败（模块不存在）

- [ ] **Step 3: 实现上述函数**
  - 读副本用 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`；`metadata_provider_info` 是 JSON 字符串，解析失败当作空。
  - 假名范围：`぀-ヿ`。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_scope.py -q`
  Expected: 全部 PASS

---

### Task 3: 演员对照、提示词、输出检查

**Files:**
- Create: `app/services/nfo_retranslate/prompts.py`
- Test: `tests/nfo_retranslate/test_prompts.py`（用测试里现写的小 `mapping_actor.xml`）

**Interfaces:**
- Produces:
  - `load_actor_glossary(path: str) -> dict[str, tuple[str, ...]]`：`zh_cn` 映射到其他写法（`jp`、`zh_tw`、`keyword` 拆开），去重、去空、不含 `zh_cn` 本身；文件读不了或不是 XML 时抛 `ValueError`
  - `SYSTEM_PROMPT: str`（文本见 Step 3）
  - `build_user_message(field: Literal["title", "plot"], *, num: str, actors: Sequence[str], glossary: Mapping[str, tuple[str, ...]], studio: str, series: str, text: str) -> str`
  - `known_names(actors: Sequence[str], glossary: Mapping[str, tuple[str, ...]]) -> list[str]`：本片演员的所有写法
  - `validate_output(field: Literal["title", "plot"], source: str, output: str, *, names: Sequence[str]) -> tuple[str | None, str | None]`：返回 `(清理后的译文, None)` 或 `(None, 失败原因)`

- [ ] **Step 1: 写失败的测试**
  - `test_load_actor_glossary`：一条 `<a zh_cn="麻仓忧" zh_tw="麻倉憂" jp="麻倉憂" keyword=",麻倉憂,松山真琴,麻仓忧,"/>` → `{"麻仓忧": ("麻倉憂", "松山真琴")}`；文件不存在抛 `ValueError`。
  - `test_build_user_message_lines`：标题消息依次含 `类型：标题`、`番号：ABC-001`、`演员对照：麻倉憂、松山真琴 → 麻仓忧`、`片商：MOODYZ`、`原文：` 加下一行原文；`series=""` 时不出现 `系列：` 行；对照表里没有的演员不出现在 `演员对照` 行；本片没有一个演员在对照表里时，整行省略。
  - `test_validate_output_rules`，每条一个断言，原因文字由实现决定、非空即可：
    - 空串或 1 个字 → 失败；
    - 以 `标题：` 或 `Title:` 开头 → 失败；
    - 含 `<think>` → 失败；
    - 以 `抱歉` 开头 → 失败；
    - 假名占比 16% → 失败；
    - 标题 61 字 → 失败；
    - 简介短于原文 20% 或长于 3 倍 → 失败；
    - 正常译文 → 通过，并且首尾的中文引号「」或 `"` 被去掉。
  - `test_validate_output_ignores_known_names_for_kana`：标题 `りかたん的初次体验` 在 `names=["りかたん"]` 时通过，`names=[]` 时失败。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_prompts.py -q`
  Expected: 失败（模块不存在）

- [ ] **Step 3: 实现**
  `SYSTEM_PROMPT` 一字不差用下面这段：
  ```
  你是一位专业的日本成人影片翻译专员，擅长把影片的日文标题或简介翻译成简体中文，也熟悉行业专有名词的译法。
  翻译规则如下：
  1. 人名：用户消息里的「演员对照」列出了本片演员的日文写法和对应的中文写法，译文里出现这些人时一律用给出的中文写法；对照里没有的人名（素人昵称等）保留日文原文，不要翻译或音译。
  2. 栏目名、系列名、厂牌名、番号和英文专名保留原文（如「ラグジュTV」「S1 NO.1 STYLE」「SSIS-951」），其中的期数照原样保留，不要换算或解释（如「56in渋谷」中的「56in」）。
  3. 如果是标题：翻译成简体中文，超过30个汉字时精简到30字以内，优先保留剧情关键词。
  4. 如果是简介：先去掉与影片无关的内容（优惠价格、促销期限、活动公告、购买说明、官网链接、特典说明等），保留全部与剧情、人物、场景相关的句子，不要概括或删减剧情，再翻译成流畅的简体中文，不限字数；原文的换行照样保留。
  5. 确保语法流畅，符合中文阅读习惯，不要故意隐去敏感词。
  输出要求：
  绝对禁止添加任何形式的标签（如「标题」「中文翻译」等）、解释或说明。你的回答必须有且仅有翻译后的中文文本本身，不包含任何其他字符。
  ```
  演员对照的写法：`其他写法用「、」连接 → 中文写法`，多位演员之间用 `；` 分隔。拒绝话术名单至少包含 `抱歉`、`对不起`、`无法翻译`、`我不能`、`I cannot`、`I'm sorry`。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_prompts.py -q`
  Expected: 全部 PASS

---

### Task 4: 翻译接口调用与并发

**Files:**
- Create: `app/services/nfo_retranslate/translator.py`
- Test: `tests/nfo_retranslate/test_translator.py`（全部用 `httpx.MockTransport`，`sleep_fn` 用空函数）

**Interfaces:**
- Consumes: `SYSTEM_PROMPT`（Task 3）
- Produces:
  - `class TranslateError(Exception)`
  - `class TranslatorClient: __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 60.0, retries: int = 3, transport: httpx.BaseTransport | None = None, sleep_fn: Callable[[float], None] = time.sleep)`；`translate(self, user_message: str) -> str`
  - `@dataclass(frozen=True) class TranslateJob: key: str; field: str; user_message: str`
  - `translate_all(client: TranslatorClient, jobs: Sequence[TranslateJob], *, workers: int, on_result: Callable[[TranslateJob, str | None, str | None], None]) -> None`：`on_result(job, 译文, 错误原因)`，同一时刻只在一个线程里调用它（用锁），保证写记录不交错

- [ ] **Step 1: 写失败的测试**
  - `test_translate_posts_chat_completion`：请求发到 `{base}/chat/completions`，带 `Authorization: Bearer test-key`，正文的 `model == "qwen38"`，`messages[0]` 是 `{"role": "system", "content": SYSTEM_PROMPT}`；返回 `choices[0].message.content` 去掉首尾空白后的文本。
  - `test_translate_retries_429_and_5xx_then_succeeds`：前两次返回 429 和 502，第三次 200 → 成功，共 3 次请求。
  - `test_translate_gives_up_after_retries`：一直返回 500 → 抛 `TranslateError`，共 `retries + 1` 次请求；错误信息里不含密钥。
  - `test_translate_all_respects_worker_limit`：10 个任务、`workers=3`，处理函数里记录同时在跑的最大数，不超过 3；每个任务都回调一次；某个任务抛 `TranslateError` 时，回调收到 `(job, None, 原因)`，其余照常完成。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_translator.py -q`
  Expected: 失败（模块不存在）

- [ ] **Step 3: 实现**
  - 重试照 `JellyfinClient._request` 的写法：连接错误、429、5xx 重试，退避 `2**attempt` 秒；4xx 的其他状态直接失败。
  - `temperature` 固定 `0.3`（本计划的决定：要稳定，不要发挥）。
  - 每个线程复用自己的 `httpx.Client`（`threading.local`）。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_translator.py -q`
  Expected: 全部 PASS

---

### Task 5: 运行记录、已写入记录与报告

**Files:**
- Create: `app/services/nfo_retranslate/runs.py`
- Create: `app/services/nfo_retranslate/report.py`
- Test: `tests/nfo_retranslate/test_runs.py`、`tests/nfo_retranslate/test_report.py`

**Interfaces:**
- Produces（`runs.py`）：
  - `@dataclass class TranslationRecord: group_key: str; field: str; num: str; actors: list[str]; source_text: str; old_text: str; new_text: str | None; error: str | None; targets: dict[str, str]`（`targets`：要写的 NFO 路径对应它在 translate 时的 sha256）
  - `class RunDir`：
    - `create(base_dir: str) -> RunDir`、`open(base_dir: str, run_id: str) -> RunDir`（类方法；运行目录不存在时抛 `FileNotFoundError`）；
    - 属性 `run_id`、`path`、`backup_dir`、`report_path`；
    - `append_translation(rec: TranslationRecord) -> None`、`load_translations() -> list[TranslationRecord]`、`done_group_keys() -> set[str]`；
    - `append_apply(entry: dict) -> None`、`load_apply() -> list[dict]`
  - `@dataclass(frozen=True) class LedgerEntry: sha256_after: str; fields: frozenset[str]; model: str`
  - `load_ledger(base_dir: str) -> dict[str, LedgerEntry]`：同一路径以最后一行为准
  - `append_ledger(base_dir: str, path: str, entry: LedgerEntry) -> None`
  - `drop_ledger(base_dir: str, paths: Iterable[str]) -> None`
- Produces（`report.py`）：`write_report(path: str, records: Sequence[TranslationRecord], *, model: str, run_id: str) -> None`

- [ ] **Step 1: 写失败的测试**
  - `test_translation_roundtrip_and_done_keys`：写入两条记录后读回，内容相等；`done_group_keys()` 是这两条的组键。
  - `test_load_translations_skips_truncated_line`（Review Focus 4）：手动在文件末尾追加半行 JSON，读取不报错，返回前面的完整记录。
  - `test_ledger_last_entry_wins_and_drop`：同一路径写两次，读回第二次的；`drop_ledger` 之后这条不在了，其他路径还在。
  - `test_report_contains_rows_and_no_secrets`：报告是能打开的 HTML，含番号、原文、旧译、新译；失败行带 `class="failed"` 和失败原因；顶部汇总含总数和失败数。报告内容里不含传给 `write_report` 以外的任何配置值（测试里把密钥放进环境变量，断言报告里没有它）。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_runs.py tests/nfo_retranslate/test_report.py -q`
  Expected: 失败（模块不存在）

- [ ] **Step 3: 实现**
  - 用 JSONL，一条记录一行，`ensure_ascii=False`。
  - 报告是单文件 HTML，内联 CSS，所有文本用 `html.escape`。
  - 文件位置：运行目录下的 `translations.jsonl`、`apply.jsonl`、`report.html`、`backup/`。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_runs.py tests/nfo_retranslate/test_report.py -q`
  Expected: 全部 PASS

---

### Task 6: 写回、还原与 Jellyfin 刷新

**Files:**
- Create: `app/services/nfo_retranslate/apply_service.py`
- Modify: `app/services/jellyfin/client.py`（在 `refresh_library` 之后加 `refresh_item`）
- Test: `tests/nfo_retranslate/test_apply_service.py`、`tests/jellyfin/test_client.py`（加一个测试）

**Interfaces:**
- Consumes：`read_nfo`、`split_title`、`build_title`、`build_plot`、`replace_fields`、`atomic_write`、`sha256_text`、`NfoError`（Task 1）；`RunDir`、`TranslationRecord`、`LedgerEntry`、`append_ledger`、`drop_ledger`（Task 5）
- Produces:
  - `JellyfinClient.refresh_item(self, item_id: str) -> None`
  - `@dataclass class ApplyResult: written: list[str]; skipped: list[tuple[str, str]]; refreshed: int; refresh_failed: list[tuple[str, str]]; missing_items: list[str]`
  - `apply_run(run: RunDir, *, base_dir: str, model: str, skip_paths: set[str], refresher: Callable[[list[str]], tuple[int, list[tuple[str, str]], list[str]]] | None) -> ApplyResult`
  - `restore_run(run: RunDir, *, base_dir: str, refresher: 同上 | None) -> ApplyResult`
  - `item_ids_for(db: Session, nfo_paths: Iterable[str], *, root: str, strm_root: str) -> tuple[dict[str, str], list[str]]`：返回 NFO 路径对应的 Jellyfin 条目 ID，以及找不到条目的 NFO 路径。换算方法：路径换成 `strm_root` 下同名的 `.strm`，查 `JellyfinMediaItem(source="strm_115", path=…, active=True).jellyfin_item_id`
  - `make_refresher(db: Session, client_factory: Callable[[], JellyfinClient], *, root: str, strm_root: str, workers: int = 2) -> Callable[[list[str]], tuple[int, list[tuple[str, str]], list[str]]]`：输入写过的 NFO 路径，返回 `(刷新成功数, [(条目ID, 原因)], 找不到条目的 NFO 路径)`；条目 ID 去重后刷新

- [ ] **Step 1: 写失败的测试**
  - `test_refresh_item_params`（放 `tests/jellyfin/test_client.py`）：请求是 `POST /Items/abc/Refresh`，参数恰好等于 Global Constraints 里的四个值。
  - `test_apply_writes_title_and_plot_and_ledger`：样例 NFO 有一条标题记录、一条简介记录。apply 后：
    - `<title>` 是 `build_title` 的结果，`<plot>` 和 `<outline>` 都是 `build_plot` 的结果；
    - `backup/<相对路径>` 和原文件逐字节相同；
    - `applied.jsonl` 里有这一条，`fields == {"title", "plot"}`，`sha256_after` 等于新文件的哈希。
  - `test_apply_skips_changed_file`：translate 之后改动 NFO，apply 跳过它，原因含「已被改动」，文件不变。
  - `test_apply_skips_failed_and_listed`：`new_text=None` 的记录不写；`skip_paths` 里的路径不写。
  - `test_apply_title_skipped_when_title_not_prefixed_by_num`：这个 NFO 只写简介，标题跳过并记录原因。
  - `test_restore_puts_backup_back_and_drops_ledger`：apply 后 restore，文件和 apply 前逐字节相同，`applied.jsonl` 里没有这条了；restore 前文件又被改过时跳过。
  - `test_refresh_failure_is_recorded_not_raised`（Review Focus 5）：refresher 里一个 ID 的刷新抛 `JellyfinError`，其余照样刷新，`refresh_failed` 记下这一条，NFO 不回滚。
  - `test_item_ids_for_maps_paths`：用 `db_session` 插入一条 `JellyfinMediaItem(source="strm_115", path=<strm 根>/甲/ABC-001/ABC-001.strm, jellyfin_item_id="j1")`，可写根下的 `甲/ABC-001/ABC-001.nfo` 能找到 `j1`；另一个 NFO 进「找不到」列表。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_apply_service.py tests/jellyfin/test_client.py -q`
  Expected: 新测试失败（模块和方法不存在），原有测试仍通过

- [ ] **Step 3: 实现**
  - `apply_run`：
    1. 按 NFO 路径把记录汇总成「这个文件要写哪些字段」；
    2. 逐个文件处理：核对 sha256 → `read_nfo` → 算新标题和新简介 → `replace_fields` → 写备份 → `atomic_write` → `append_apply` → `append_ledger`；
    3. 全部写完后，对写成功的路径调用 `refresher`。
    单个文件的 `NfoError` 只记进 `skipped`，不中断。
  - `restore_run` 以 `apply.jsonl` 里写成功的条目为准，核对当前 sha256 等于当时写入后的哈希，再用备份覆盖。

- [ ] **Step 4: 跑测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_apply_service.py tests/jellyfin/test_client.py -q`
  Expected: 全部 PASS

---

### Task 7: 命令行脚本、使用文档、全量测试

**Files:**
- Create: `scripts/nfo_retranslate.py`
- Create: `docs/nfo-retranslate.md`
- Modify: `scripts/README.md`（加一节）
- Test: `tests/nfo_retranslate/test_cli.py`（照 `tests/jellyfin/test_display_names_cli.py` 的写法按路径加载脚本；翻译客户端和 refresher 用 monkeypatch 换成假的）

**Interfaces:**
- Consumes：前面各任务的全部 Produces
- Produces：`main() -> int`。子命令 `translate`、`apply`、`restore`。退出码：`0` 成功；`1` 缺配置、没过前提检查，或运行编号不存在。

`translate` 的参数：`--limit N`、`--sample N`、`--fields title,plot`（默认两个都要）、`--path-prefix`、`--engine`、`--workers`（默认 8）、`--resume RUN_ID`、`--redo`、`--force`。
`apply` 的参数：`--run RUN_ID`、`--skip FILE`（每行一个 NFO 路径）、`--no-refresh`。
`restore` 的参数：`--run RUN_ID`、`--no-refresh`。

- [ ] **Step 1: 写失败的测试**
  - `test_translate_requires_config`：缺 `NFO_TRANSLATE_API_KEY` 时返回 1，输出写明缺哪一项。
  - `test_translate_stops_on_many_orphans`：造 101 个找不到任务的 NFO，不加 `--force` 返回 1，输出含「旧版残留」；加 `--force` 继续执行。
  - `test_translate_end_to_end_with_fake_model`：两组片子（一组标题和简介都要翻，一组只要翻简介），假模型回固定译文。返回 0；`translations.jsonl` 有 3 条记录；`report.html` 存在；所有 NFO 都没被改。
  - `test_translate_skips_ledger_unless_redo`：`applied.jsonl` 里有某个 NFO、哈希和当前一致时，这个 NFO 不在任何记录的 `targets` 里；加 `--redo` 后在。
  - `test_resume_skips_done_groups`：先写一条组记录，再 `--resume` 同一个运行，这一组不再调用模型。
  - `test_sample_and_limit`：5 组时 `--limit 2` 只翻前两组；`--sample 2` 翻其中两组（固定随机种子做测试）。
  - `test_apply_then_restore_cli`：先 `translate`，再 `apply --run`、`restore --run`，各返回 0，最终文件和最初逐字节相同。

- [ ] **Step 2: 跑测试，确认失败**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate/test_cli.py -q`
  Expected: 失败（脚本不存在）

- [ ] **Step 3: 实现**
  `translate` 的流程：
  1. 检查配置；
  2. 建运行目录（或用 `--resume` 打开已有的）；
  3. `snapshot_mdc_db` 复制到运行目录下的 `mdc/`；
  4. 读字段来源，再分组；
  5. 找不到任务的 NFO 超过 100 个且没加 `--force`，就退出；
  6. 按 `--path-prefix`、`--engine` 筛选；
  7. 去掉「已写入」记录里哈希没变的 NFO（加了 `--redo` 就不去）；
  8. 去掉已完成的组；
  9. 按 `--sample` 或 `--limit` 选组；
  10. 每组每个字段：以第一个在范围内的 NFO 为原文来源，`targets` 是组内这个字段在范围内、而且没被已写入记录跳过的 NFO。原文的取法：标题用 `strip_num(original_title, num)`；简介用 `plot_body(original_plot)`（原简介里也可能有 `<br>`，要先换成换行）。旧译文的取法：标题用 `split_title` 取出的正文，简介用 `plot_body(plot)`；
  11. 调用 `translate_all`，结果过 `validate_output(field, 原文, 译文, names=known_names(本片演员, 对照表))` 后写记录；
  12. 写报告；
  13. 打印运行编号、报告的宿主机路径和汇总。

  `apply` 和 `restore` 的 refresher 用 `make_refresher(SessionLocal(), lambda: JellyfinClient(...), root=..., strm_root=MEDIA_LIBRARY_STRM_ROOTS 里含 302porn_tv1 的那一项)`。`--no-refresh` 时传 `None`，并提示要手动扫描 Jellyfin 库。

  `docs/nfo-retranslate.md` 写这几块：用途和范围、配置项、两阶段用法和示例命令（在容器里后台跑：`docker exec -d docker-app-1 sh -c "python scripts/nfo_retranslate.py translate ... > data/nfo_retranslate/translate.log 2>&1"`）、看报告的方法、还原方法；再说明「MDC 重试会覆盖」和「要在旧版残留清理之后再跑」。

- [ ] **Step 4: 跑这一组测试，确认通过**
  Run: `scripts/remote-test.sh backend tests/nfo_retranslate -q`
  Expected: 全部 PASS

- [ ] **Step 5: 跑全量后端测试，确认没有破坏原有功能**
  Run: `scripts/remote-test.sh backend`
  Expected: 全部 PASS；如有与本改动无关的既有失败，记录用例名和原因，不能说全套通过

- [ ] **Step 6: 写进度日志，交用户决定是否提交**
  - 新建 `progress/2026-11-27-nfo-retranslate.md`，含 `What was done`、`Testing`、`Notes`（Changed files / Rollback）。
  - 不提交。列出本次改动的文件清单，问用户是否提交。
  - 部署和生产 `.env` 配置（含密钥）另行征得用户同意后再做。
