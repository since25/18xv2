# 前后端类型自动生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 由后端接口定义生成前端类型文件，加上“忘了重新生成就测试失败”的检查，并把能生成的手写类型换成对生成类型的引用。

**Architecture:** `scripts/export_openapi.py` 把 `app.openapi()` 写成 `frontend/openapi.json`；`openapi-typescript` 由它生成 `frontend/src/api/schema.gen.ts`；两个文件入库。后端一个快照测试、前端一个一致性测试负责防漂移。手写类型改为同名别名。

**Tech Stack:** FastAPI、pytest；TypeScript ~6.0、vitest、openapi-typescript（新增 devDependency）。

**Spec:** `docs/superpowers/specs/2026-11-17-api-types-generation-design.md`（执行前必须先读）

## Global Constraints

- 不改 `app/` 下任何文件；不改 `frontend/src/pages/` 下任何文件；不改现有测试文件。
- 不得添加 `any`、`as unknown as`、`@ts-ignore`、`@ts-expect-error`、`eslint-disable` 来让类型通过。
- 生成类型比手写宽松、或两边不一致时：**不替换，保留手写，记入汇报**。不要自行判断以哪边为准。
- 导出的类型名字不变；各 `api/*.ts` 里的请求函数不改写（只允许改其类型引用）。
- 只新增一个依赖：`openapi-typescript`（devDependencies）。若它与 TypeScript ~6.0 有 peer 冲突且不用 `--force` / `--legacy-peer-deps` 无法安装，**停下并汇报**，不要强装、不要降级 TypeScript。
- **不做任何 git 操作。** 不连生产服务器。不读取或输出 `.env`、`data/` 下的内容。
- 测试、npm、Python 都只在 Spark 上跑（`ssh spark`，远程目录 `~/ci/18x_v2/18x_v2`）。全量验证用 `scripts/remote-test.sh backend|frontend|all`，每次只启动一次并前台等待，不轮询。本机不跑 npm / pytest。
- 代码注释和文档用中文，保持各文件现有风格。

## Review Focus

1. 后端模型加了一个字段但没重新生成 → 后端快照测试失败，报错里有 `scripts/gen-api-types.sh`。（Task 1 测试）
2. 有人手改了 `schema.gen.ts` → 前端一致性测试失败。（Task 2 测试）
3. 连续两次生成 → 两个生成文件内容逐字节相同（键顺序稳定）。（Task 2 验证步骤）
4. 手写类型是固定取值联合、后端是 `str` → 该类型保持手写。（Task 3 逐个判断）
5. 导出脚本在没有 `.env`、没有数据库的环境（Spark）能跑。（Task 1 验证步骤）

---

### Task 1: 导出接口定义 + 后端快照测试

**Files:**
- Create: `scripts/export_openapi.py`、`tests/api/test_openapi_snapshot.py`、`frontend/openapi.json`（生成）

- [ ] **Step 1: 写失败测试** `test_openapi_snapshot_is_up_to_date`：读取 `frontend/openapi.json` 并 `json.loads`，断言等于 `app.main.app.openapi()`；断言失败信息包含 `scripts/gen-api-types.sh`。应用的导入方式沿用 `tests/` 里现有路由测试的做法。
- [ ] **Step 2: 实现** `scripts/export_openapi.py`：把 `app.openapi()` 以 `json.dumps(..., sort_keys=True, indent=2, ensure_ascii=False)` 加结尾换行写入 `frontend/openapi.json`。不启动 lifespan。
- [ ] **Step 3: 在 Spark 上运行导出**并取回 `frontend/openapi.json`；跑 `scripts/remote-test.sh backend tests/api/test_openapi_snapshot.py -q`，预期通过。

### Task 2（修订版，取代下方原 Task 2）: 自写生成器 + 一致性测试 + 一条命令

原 Task 2 因 `openapi-typescript` 与 TypeScript 6 的 peer 冲突作废。**不新增任何依赖，不改 `package.json`、`package-lock.json`。**

**Files:**
- Modify: `scripts/export_openapi.py`、`tests/api/test_openapi_snapshot.py`（本轮新建的文件，可改）、`frontend/eslint.config.js`（忽略 `src/api/schema.gen.ts`）
- Create: `tests/api/test_openapi_typescript.py`、`frontend/src/api/schema.gen.ts`（生成）、`scripts/gen-api-types.sh`

**Interfaces:**
- `scripts/export_openapi.py` 提供 `render_typescript(spec: dict) -> str`，把 `spec["components"]["schemas"]` 写成：文件头注释（中文，说明自动生成、勿手改、用 `scripts/gen-api-types.sh` 重新生成）+ `export interface components { schemas: { 'Name': ...; ... } }`。模型名按字典序输出；字段顺序按 `properties` 原顺序。脚本默认同时写 `frontend/openapi.json` 和 `frontend/src/api/schema.gen.ts`。
- 映射规则：`string`/`integer`/`number`/`boolean`/`null` → 对应 TS 基本类型；`enum`、`const` → 字面量联合；`array` + `items` → `T[]`（联合类型加括号）；`$ref` → `components['schemas']['X']`；`anyOf`/`oneOf` → 联合；`object` + `properties` → 对象字面量，`required` 之外的字段带 `?`；`additionalProperties` → `Record<string, T>`（`true` 或空对象时为 `unknown`）；没有 `type` 的空定义 → `unknown`；`prefixItems` → 元组。`format`、`title`、`description`、`default`、长度和范围等校验关键字忽略。**出现以上未列出的、会影响类型形状的关键字（如 `allOf`、`not`、`discriminator` 之外的未知组合）时抛出异常并指明模型名和字段**；若当前 `openapi.json` 里确实用到了，按语义补上映射并加测试，在汇报里列出。

- [ ] **Step 1: 写生成器单元测试** `tests/api/test_openapi_typescript.py`：对上述每条映射规则各一个小输入并断言输出片段；可选字段带 `?`；`X | None` 输出 `X | null`；未知关键字抛异常；同一输入生成两次结果相同。
- [ ] **Step 2: 实现 `render_typescript`。**
- [ ] **Step 3: 一致性测试**：在 `tests/api/test_openapi_snapshot.py` 加 `test_generated_types_are_up_to_date`，断言 `render_typescript(app.openapi())` 等于入库的 `frontend/src/api/schema.gen.ts`，失败信息包含 `scripts/gen-api-types.sh`。
- [ ] **Step 4: 写 `scripts/gen-api-types.sh`**：同步当前检出到 Spark、在那里用后端 venv 运行导出脚本、把两个生成文件取回本机。同步规则和远程环境复用 `scripts/remote-test.sh` 的做法，不要整段复制粘贴；允许给 `remote-test.sh` 加一个模式来承载。脚本头部用中文注释说明用法。
- [ ] **Step 5: 验证**：运行 `scripts/gen-api-types.sh` 两次，第二次后本机两个生成文件无变化；`scripts/remote-test.sh all` 退出码 0（`schema.gen.ts` 能通过 `tsc` 和 lint）。

### （已作废）原 Task 2: 生成类型 + 前端一致性测试 + 一条命令

**Files:**
- Modify: `frontend/package.json`、`frontend/package-lock.json`（在 Spark 上 `npm install -D openapi-typescript` 后取回）、`frontend/eslint.config.js`（忽略 `src/api/schema.gen.ts`）
- Create: `frontend/src/api/schema.gen.ts`（生成）、`frontend/src/api/schema.gen.test.ts`、`scripts/gen-api-types.sh`

**Interfaces:**
- Produces: `frontend/src/api/schema.gen.ts` 导出 `paths`、`components`；`package.json` 脚本 `gen:api`（`openapi-typescript openapi.json -o src/api/schema.gen.ts`，其余选项由实施者定，但测试必须用同一组选项）。

- [ ] **Step 1: 安装依赖并加 `gen:api` 脚本。**
- [ ] **Step 2: 写一致性测试** `schema.gen.test.ts`（`// @vitest-environment node`）：用 openapi-typescript 的程序接口由 `openapi.json` 重新生成，断言与入库的 `schema.gen.ts` 内容相同；失败信息包含 `scripts/gen-api-types.sh`。
- [ ] **Step 3: 写 `scripts/gen-api-types.sh`**：同步当前检出到 Spark、在那里依次执行导出和 `npm run gen:api`、把 `frontend/openapi.json` 和 `frontend/src/api/schema.gen.ts` 取回本机。同步和远程环境准备尽量复用 `scripts/remote-test.sh` 已有的做法，不要整段复制粘贴；允许给 `remote-test.sh` 加一个模式来承载。脚本头部用中文注释说明用法。
- [ ] **Step 4: 验证**：运行 `scripts/gen-api-types.sh` 两次，第二次后本机两个生成文件无变化；`scripts/remote-test.sh frontend` 退出码 0。

### Task 3: 替换手写类型

**Files:** `frontend/src/api/types.ts`、`dedupe.ts`、`downloader.ts`、`embyMediaActions.ts`、`jellyfin.ts`、`scriptRuns.ts`、`whitelistBatch.ts`、`reviewIntake.ts`

- [ ] **Step 1: 建对照表**：143 个手写类型逐个找后端对应的 `components['schemas'][...]`，按设计文档“替换规则”分成三类：可替换 / 保留手写（更宽松或后端无定义）/ 两边不一致。
- [ ] **Step 2: 替换“可替换”类**为别名（`export type X = components['schemas']['Y']`），一次改一个文件，每改完一个文件跑一次 `scripts/remote-test.sh frontend`。某个类型替换后需要改页面文件才能编译通过 → 撤回该类型的替换，归入“两边不一致”。
- [ ] **Step 3: 全量验证** `scripts/remote-test.sh all` 退出码 0。

### Task 5（第二轮追加）: 返回模型的默认值字段按必填生成，再替换一轮

Global Constraints 全部继续适用（`app/` 仍然不改）。

**Files:** `scripts/export_openapi.py`、`tests/api/test_openapi_typescript.py`、`frontend/src/api/schema.gen.ts`（重新生成）、`frontend/src/api/*.ts`（类型别名）、`docs/DEVELOPMENT_GUIDE.md` 3.5 节

- [ ] **Step 1: 写失败测试**（`render_typescript` 签名不变，输入为完整 spec）：
  - 模型只被某接口的 `responses` 引用，字段带 `default` → 输出不带 `?`。
  - 模型只被 `requestBody` 引用，字段带 `default` → 仍带 `?`。
  - 模型同时被请求和返回引用 → 仍带 `?`。
  - 模型 A 只在返回里，A 引用 B（经 `$ref`、数组 `items`、`anyOf`、`additionalProperties` 任一途径）→ B 的默认值字段也不带 `?`；若 B 同时被某请求引用 → B 仍带 `?`。
  - 模型没有被任何接口引用 → 维持原样（带 `?`）。
  - 不带 `default` 且不在 `required` 里的字段（如 `default_factory`）→ 仍带 `?`。
  - 接口参数（`parameters`）里引用的模型算“请求”。
- [ ] **Step 2: 实现**：遍历 `spec["paths"]` 求“返回可达”和“请求可达”两个模型集合（沿引用传递闭包），只对“返回可达且非请求可达”的模型把带 `default` 的字段视为必填。
- [ ] **Step 3: 重新生成**（`scripts/gen-api-types.sh`）并跑 `scripts/remote-test.sh backend`。
- [ ] **Step 4: 再替换一轮**：对仍然手写的类型按与 Task 3 相同的严格比对方法重新分类，新变成“完全一致”的换成别名。其余规则不变（更宽松或不一致的保留手写）。
- [ ] **Step 5: 全量验证** `scripts/remote-test.sh all` 退出码 0；更新 `docs/DEVELOPMENT_GUIDE.md` 3.5 节里关于“带默认值的字段”的说明。
- [ ] **Step 6: 汇报**：新增替换的数量和清单；仍保留手写的各类数量及主要原因；原“两边不一致”20 个里是否有变化；全量测试结果和日志路径。

### Task 6（第三轮追加）: 仅返回模型的全部字段按必填生成

Task 5 的规则只多替换了 3 个，因为 `X | None = None` 和 `default_factory` 字段在 `openapi.json` 里没有 `default`。返回数据时模型的所有字段都会输出（全仓未使用 `exclude_*`），所以规则改为：**“返回可达且非请求可达”的模型，所有字段都不带 `?`，不再看 `default`**。可空性（`| null`）照常保留。

- [ ] **Step 1:** 调整 `tests/api/test_openapi_typescript.py` 中 Task 5 的用例：仅返回模型里不带 `default` 的非必填字段（含 `default_factory`、`X | None = None`）现在不带 `?`；请求可达、两边都用、未被引用的模型仍维持原样。删掉实现里不再需要的 `default` 判断。
- [ ] **Step 2:** 重新生成，按同样的严格比对方法再分类、再替换一轮。新替换的类型逐个确认对应路由设了 `response_model` 或返回模型实例；`StreamingResponse` 推送的帧（如 `JobFrame`、`DedupeJobFrame`）不经过模型序列化，若被判为“仅返回”也不要替换，记入汇报。
- [ ] **Step 3:** `scripts/remote-test.sh all` 退出码 0；更新 `docs/DEVELOPMENT_GUIDE.md` 3.5 节。
- [ ] **Step 4: 汇报**，同 Task 5 Step 6，另列出最终四类的数量。

### Task 4: 文档与汇报

- [ ] **Step 1:** `docs/DEVELOPMENT_GUIDE.md` 增加一小节（接在 3.4 之后）：后端改接口或模型后运行 `scripts/gen-api-types.sh`；新写前端类型优先引用生成的类型。
- [ ] **Step 2: 汇报**：三类类型各自的数量和清单；“两边不一致”类逐条写明类型名、字段、前端写的是什么、后端实际是什么；改动文件清单；最后一次全量测试的退出码、通过数和日志路径；与计划不一致的地方。
