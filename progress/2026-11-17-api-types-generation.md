# 2026-11-17 前后端类型自动生成

## What was done

按设计 `docs/superpowers/specs/2026-11-17-api-types-generation-design.md` 和计划 `docs/superpowers/plans/2026-11-17-api-types-generation.md`（用户选定“做法二”：装生成工具和检查，并替换能生成的那部分手写类型）。实施由 Opus 子代理完成，主会话核对了改动范围并独立复跑了全量测试。

- 新增 `scripts/export_openapi.py`：导出后端接口定义到 `frontend/openapi.json`，并由其中的数据模型生成 `frontend/src/api/schema.gen.ts`。两个文件入库。
- 新增 `scripts/gen-api-types.sh`：一条命令在 Spark 上完成导出和生成并取回本机。实现方式是给 `scripts/remote-test.sh` 加了 `gen-api` 模式，并把“准备后端环境”拆成独立一段供复用。
- 新增后端测试：接口定义或生成的类型与入库文件不一致时失败，并提示运行 `scripts/gen-api-types.sh`；生成器自身有 40 个单元测试。
- 143 个手写类型中 65 个改为引用生成类型的同名别名（分布在 `types.ts`、`dedupe.ts`、`whitelistBatch.ts`、`embyMediaActions.ts`、`reviewIntake.ts`）。类型名不变，页面文件未改。
- 替换分三轮做：第一轮只换完全一致的（25 个）；第二轮让生成器把“只用于返回的模型里带默认值标记的字段”生成为必填（+3）；第三轮改为“只用于返回的模型所有字段都必填”（+41，同时撤回 4 个）。
- `frontend/eslint.config.js` 忽略生成文件；`docs/DEVELOPMENT_GUIDE.md` 新增 3.5 节。

没有改 `app/`、`frontend/src/pages/`、既有测试，没有新增依赖。

## Testing

- 全量（主会话独立复跑）：`scripts/remote-test.sh all`。后端 540 passed（改动前 499，新增 41）；前端 vitest 122 passed，build 通过，lint 0 问题。日志：Spark `~/ci/18x_v2/18x_v2/.remote-test-logs/20261117-220821-all.log`。
- 子代理验证过：连续运行两次 `scripts/gen-api-types.sh`，两个生成文件内容不变；手改 `schema.gen.ts` 或让 `openapi.json` 与后端不一致，检查都会失败并提示命令（在 Spark 副本上模拟，验证后已恢复）。
- 未做：
  - “真的在后端模型里加一个字段”这个场景没有实测（本轮不改 `app/`），只用改动入库文件的方式模拟。
  - 主会话没有逐行审读 `scripts/export_openapi.py`，依据是它的 40 个单元测试和前端构建通过。
  - “只用于返回的模型所有字段都必填”依赖两个前提：后端接口代码没有使用 `exclude_unset` / `exclude_none` / `exclude_defaults`（主会话 grep 过 `app/`）；对应路由经过模型序列化。后者子代理只对已替换的 41 个类型逐个核对了路由函数本身，没有追进辅助函数和中间件；生成文件里其余尚未被前端引用的模型没有核对。
  - 类型分类用的比对脚本是临时的，没有入库，下面的清单无法一键复核。
  - 没有在浏览器里打开页面，没有部署。本轮不改变线上行为。

## Notes

### 与原设计不一致

- 原定使用 `openapi-typescript`，它只支持 TypeScript 5，本项目是 TypeScript 6，不强装装不上。改为自写生成器，不新增依赖。设计和计划已同步修订。
- 一致性检查因此全部放在后端测试里，没有前端一侧的检查文件。

### 替换结果（143 个手写类型）

| 结果 | 数量 | 说明 |
|---|---|---|
| 已替换为别名 | 65 | |
| 保留手写：后端无对应定义 | 37 | 15 个是前端自用的取值和查询参数类型，22 个对应后端返回没写说明的字典（下载器为主） |
| 保留手写：两边不一致 | 23 | 见下 |
| 保留手写：生成的更宽松 | 16 | 请求参数里后端可选的字段 4 个；请求和返回共用的模型 4 个；固定取值在后端是普通字符串 8 个 |
| 完全一致但不替换 | 2 | `DedupeJobFrame`（进度推送的帧，不经过模型）、`TreeImport`（见“顺带发现的既有问题”） |

项目的 `tsconfig.app.json` 没有开严格模式（不检查空值），所以“构建通过”发现不了可空性差异；分类是在严格模式下逐个比对得出的。

### 两边不一致的 23 个类型

都保留手写，本轮没有改任何一边。

实质差异：

1. `JobDetail`（及连带的 `BatchPlanOperationResponse`）：后端多返回 `confirmation_validated`、`rollback_records` 两个字段，前端类型里没有。
2. `ReviewIntakeCreatePayload`：后端还接受 `pattern`、`flags`、`group_index`、`limit` 四个可选参数，前端类型里没有；`keyword` 后端允许为空。
3. `JobFrame`（及连带的 `ActiveJobs`，白名单批处理）：`summary` 前端写成“任意名字的数字”，后端是两种固定形状之一。
4. `JellyfinStatus`：`counts`、`collections` 前端是固定字段的对象，后端是“任意名字的数字”。
5. `TreeHitSummaryItem`、`JellyfinUnmatchedItem`（及各自的列表类型）：前端是普通字符串，后端是固定取值。

只是“能不能为空 / 是否一定有”不同：

6. `PlanItem`、`PlanDetail`、`PlanBatchResponse`、`ExecutionLog`：`node_id`、`created_at`、`started_at` 前端允许为空，后端声明不为空。
7. `JellyfinJob`、`JellyfinConflictItem`：若干字段前端允许为空，后端声明不为空。
8. `KeywordEntryUpdatePayload`、`ScanJobRequest`、`MagnetDuplicateCheckItem`（及其列表类型）：后端允许显式传空或返回空，前端没写。
9. `DedupeGroup`、`DedupeGroupListResponse`、`DedupeGroupDetailResponse`：`created_at`、`updated_at` 前端写的是可选，后端一定返回。第一轮曾替换，第三轮规则变化后不再完全一致，已撤回为原手写。

### 顺带发现的既有问题（已修，见文末）

磁力任务页“拉取 115 目录树”：`frontend/src/pages/MagnetTasksPage.tsx` 读取返回里的 `id`，但后端 `POST /imports/remote-fetch`（`app/api/routes/imports.py`）返回的是 `{"import_id", "status"}`，没有 `id`。读代码的结论是成功提示会显示“批次 #undefined”，且不会自动选中新批次；没有在页面上实测。前端这样写始于 2026-05-16，不是今天的改动引入的。类型 `TreeImport` 因此不替换。

### 后续可做（未做，需用户发话）

- `TreeImport` 类型现在可以换成生成的别名（原先只因磁力任务页误用而保留），未做。
- 把后端的固定取值字段（`entry_type`、`kind`、`status` 等）声明成固定取值，可再替换 8 个类型。
- 给约 50 个返回字典的接口补返回说明（原“做法三”）。
- `scripts/README.md` 没有加新脚本说明。

### 追加：修磁力任务页字段名（用户确认后做）

- `frontend/src/pages/MagnetTasksPage.tsx`：拉取目录树成功后改读 `import_id`，返回类型改为 `{ import_id, status }`。成功提示现在显示正确的批次号，并自动选中新批次。
- 新增 `frontend/src/pages/MagnetTasksPage.test.tsx`（1 个用例）。修复前先跑过一次，失败在找不到“批次 #42”；修复后通过。
- 验证：`scripts/remote-test.sh frontend` 退出码 0，vitest 123 passed，build 通过，lint 0 问题。日志：`20261117-221201-frontend.log`。后端代码在上一次全量测试（540 passed）之后没有改动。
- 未做：没有在浏览器里对真实 115 目录实际拉取一次。
- 回滚时额外执行：`git checkout -- frontend/src/pages/MagnetTasksPage.tsx`，并删除 `frontend/src/pages/MagnetTasksPage.test.tsx`。

### Changed files

新建：

- `scripts/export_openapi.py`、`scripts/gen-api-types.sh`
- `tests/api/test_openapi_snapshot.py`、`tests/api/test_openapi_typescript.py`
- `frontend/openapi.json`、`frontend/src/api/schema.gen.ts`（生成）
- `docs/superpowers/specs/2026-11-17-api-types-generation-design.md`
- `docs/superpowers/plans/2026-11-17-api-types-generation.md`

修改：

- `scripts/remote-test.sh`
- `frontend/eslint.config.js`
- `frontend/src/api/types.ts`、`dedupe.ts`、`embyMediaActions.ts`、`whitelistBatch.ts`、`reviewIntake.ts`
- `docs/DEVELOPMENT_GUIDE.md`
- `frontend/src/pages/MagnetTasksPage.tsx`（追加修复）；新建 `frontend/src/pages/MagnetTasksPage.test.tsx`

### Rollback

改动尚未提交。恢复已修改文件并删除新建文件即可：

```bash
git checkout -- scripts/remote-test.sh frontend/eslint.config.js frontend/src/api docs/DEVELOPMENT_GUIDE.md
```

```bash
rm scripts/export_openapi.py scripts/gen-api-types.sh tests/api/test_openapi_snapshot.py tests/api/test_openapi_typescript.py frontend/openapi.json frontend/src/api/schema.gen.ts
```
