# 冲突处理设计文档

> 创建日期：2026-04-21

## 背景

目前系统存在两类关键词命中冲突，均缺乏友好的处理界面：

1. **歧义冲突**：同一路径被多个白名单关键词命中（如 A、B 两位作者合作的文件夹），系统自动跳过，需要手动指定归属关键词
2. **重复目标冲突**：多个不同源路径的任务映射到同一目标路径，说明是重复文件，需要决定保留哪个并可选删除其余

---

## 一、歧义冲突（Ambiguous Conflict）

### 现状

- 生成任务时，命中多个关键词的路径被自动跳过（`skipped_ambiguous_count`）
- 用户通过 `GET /organize-tasks/ambiguous-conflicts/export` 导出 TSV，手动填写后再导入
- 无 UI 内联操作，流程繁琐

### 方案：UI 内联选择（替代 TSV 主流程）

#### 后端新增接口

**`GET /organize-tasks/ambiguous-conflicts?import_id=X`**

返回 JSON 格式的冲突列表。关键词需同时携带 `id` 和 `canonical_name`（现有 service 只返回 name，需补充 id）：

```json
[
  {
    "source_path": "/待整理/A&B合作专辑",
    "keywords": [
      {"id": 12, "name": "作者A"},
      {"id": 17, "name": "作者B"}
    ]
  }
]
```

**`POST /organize-tasks/ambiguous-conflicts/resolve`**

接收裁决列表，内部复用现有 `apply_ambiguous_resolutions_from_tsv` 的任务生成逻辑：

```json
{
  "import_id": 3,
  "resolutions": [
    {"source_path": "/待整理/A&B合作专辑", "keyword_entry_id": 12}
  ],
  "replace_existing": true
}
```

响应同现有 TSV 导入响应：`created_count / replaced_count / skipped_count / errors`。

TSV export/import 接口保留，降级为高级操作（折叠隐藏）。

#### 前端改动（OrganizeTasksPage 歧义冲突区）

- 页面加载时调 `GET /ambiguous-conflicts` 获取列表（不需要额外触发）
- 每条冲突展示 `source_path` + `Radio.Group`（选项为关键词名称，value 为 keyword_entry_id）
- 提供"全选第一个"批量预填按钮，减少逐条点击
- 底部"保存裁决"一次性 `POST /ambiguous-conflicts/resolve`
- 成功后刷新冲突列表；若列表清空则提示"歧义冲突已全部处理"

#### 受影响文件

| 文件 | 变更类型 |
|---|---|
| `app/services/tasks/organize_task_service.py` | 补充 `list_ambiguous_conflicts` 返回 keyword_entry_id |
| `app/schemas/tasks.py` | 新增 `AmbiguousConflictItem`（含 keywords id+name）、`AmbiguousResolveRequest` |
| `app/routers/organize_tasks.py` | 新增 `GET /ambiguous-conflicts` 和 `POST /ambiguous-conflicts/resolve` |
| `frontend/src/api/types.ts` | 新增对应 TypeScript 类型 |
| `frontend/src/pages/OrganizeTasksPage.tsx` | 替换歧义冲突 UI 区域 |

---

## 二、重复目标冲突 + 删除功能（Duplicate Target Conflict）

### 现状

- 计划生成时检测 `conflict_status=duplicate_target`
- `GET /organize-tasks/duplicate-conflicts` 返回冲突分组（source_path 列表）
- 前端可手动改路径或标记跳过，但无文件详情、无删除功能

### 方案：三层懒加载 + 按需删除

#### 数据层级

```
冲突组列表（DB，页面加载时）
  └── 点击"查看详情" → tree_nodes 本地 DB 查询（0 次 115 调用）
        └── 点击"从 115 刷新" → 115 API（按需，1 次批量调用）
```

#### 后端新增接口

**1. `POST /organize-tasks/node-details`**（第一层懒加载）

传入 task_id 列表，从本地 `tree_nodes` 返回节点基础信息：

```json
// 请求
{"task_ids": [124, 125]}

// 响应
{
  "124": {"raw_name": "专辑X", "raw_path": "/待整理/.../专辑X", "cid": "115_cid_xxx"},
  "125": {"raw_name": "专辑X", "raw_path": "/其他来源/.../专辑X", "cid": "115_cid_yyy"}
}
```

**2. `POST /115/file-info`**（第二层懒加载，按需刷新）

传入 cid 列表，调用 115 API 返回文件大小和修改时间：

```json
// 请求
{"cids": ["115_cid_xxx", "115_cid_yyy"]}

// 响应
{
  "115_cid_xxx": {"size": 1048576, "modified_at": "2024-03-01T12:00:00+08:00"},
  "115_cid_yyy": {"size": 1048576, "modified_at": "2023-11-15T08:30:00+08:00"}
}
```

**3. `POST /organize-tasks/resolve-duplicate-conflicts`**（确认时一次提交）

```json
{
  "resolutions": [
    {
      "target_path": "/整理后/作者A/专辑X",
      "keep_task_id": 124,
      "skip_task_ids": [125],
      "delete_from_115": true
    }
  ]
}
```

后端处理顺序：
1. 将 `skip_task_ids` 的 `status` 改为 `skipped`
2. 若 `delete_from_115=true`，根据对应 node 的 cid 调用 115 删除 API
3. 一次 `db.commit()`

响应：`{resolved_count, deleted_from_115_count, errors: []}`

#### 前端改动（OrganizeTasksPage 重复目标冲突区）

每个冲突组（按 target_path 折叠）的交互层级：

```
┌─ /整理后/作者A/专辑X  [2 条冲突] ──────────────────────┐
│  source_path A: /待整理/finish1217/专辑X               │
│  source_path B: /其他来源/专辑X           [查看详情]   │
│                                                        │
│  展开后（查 DB）：                                      │
│  ○ 保留 A │ 专辑X │ /待整理/...           [从115刷新]  │
│  ● 保留 B │ 专辑X │ /其他来源/...                      │
│                                                        │
│  刷新后补充：1.0 MB │ 修改时间 2024-03-01              │
│                                                        │
│  ☑ 删除未保留的文件（从 115 删除）                      │
│                              [确认处理]                │
└────────────────────────────────────────────────────────┘
```

状态管理：
- `detailLoaded: boolean` — 是否已查过 node-details
- `refreshLoaded: boolean` — 是否已从 115 刷新
- `keepTaskId: number | null` — 选中保留的任务
- `deleteFrom115: boolean` — 是否删除其余

所有组处理完后显示汇总 Toast：`X 个已跳过，Y 个已从 115 删除`。

#### 受影响文件

| 文件 | 变更类型 |
|---|---|
| `app/services/tasks/organize_task_service.py` | 新增 `get_node_details`、`resolve_duplicate_conflicts` 方法 |
| `app/services/client_service.py` | 新增 `get_file_info(cids)`、`delete_files(cids)` 封装 |
| `app/schemas/tasks.py` | 新增 `NodeDetailResponse`、`DuplicateResolveRequest/Response` |
| `app/routers/organize_tasks.py` | 新增 `POST /node-details`、`POST /resolve-duplicate-conflicts` |
| `app/routers/` | 新增 `POST /115/file-info` 路由（或挂到现有 115 路由下） |
| `frontend/src/api/types.ts` | 新增对应 TypeScript 类型 |
| `frontend/src/pages/OrganizeTasksPage.tsx` | 重写重复目标冲突 UI 区域 |

---

## 三、不在本次范围内

- 歧义冲突的 TSV 导出/导入接口（保留，不删除）
- 115 删除操作的回滚（删除是不可逆的，UI 需有明确二次确认）
- 历史 `source_path` 漂移处理（单独议题）
- P2 文档补全

---

## 四、验收标准

| 场景 | 期望结果 |
|---|---|
| 歧义冲突列表加载 | 页面进入后自动展示冲突路径和关键词选项，无需操作 |
| 歧义冲突保存裁决 | 选择关键词后点保存，任务生成成功，冲突列表刷新 |
| 重复冲突默认视图 | 只展示 source_path，不调用任何外部 API |
| 查看详情 | 点击后展示 raw_name / raw_path，来自本地 DB |
| 从 115 刷新 | 点击后补充 size / modified_at，仅调用一次 115 批量接口 |
| 确认处理（不删除）| skip_task_ids 状态变为 skipped，不调用 115 |
| 确认处理（删除）| skip_task_ids 状态变为 skipped + 115 文件删除成功 |
| 115 删除失败 | 返回 errors 列表，UI 提示哪些文件删除失败，任务状态仍为 skipped |
