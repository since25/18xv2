# 待审核页候选词点选优化 实施计划

> 设计文档：`docs/superpowers/specs/2026-09-05-review-intake-candidate-picker-design.md`（v2，已过 Fable 评审）

**目标：** 待审核页关键词捕获失败时，用户点击候选标签 → 点批准两步完成，不再需要悬停-复制-粘贴。

**做法：** 新建一个纯函数模块负责「从路径切出候选词」，取材范围从「仅文件名」扩到「文件名 + 直接父目录」，规则从「仅括号」扩到「hashtag / 括号 / 分隔切片」三条；`ReviewIntakeService` 改调该模块；前端把候选标签改成可点选并补状态色图例与「×加忽略库」。

**技术栈：** FastAPI + SQLAlchemy + pytest（后端）；React + Vite + Ant Design（前端）。

## 全局约束

- **无数据库迁移、无接口变更**：来源标记复用现有 `ReviewKeywordCandidate.source` 字段。
- **不改 IINA 投递链路**：`scripts/review_intake_shortcut.py` 与 lua 插件一行不动。
- **不改 `extract_regex_keywords_from_path`**：它另有 `app/api/routes/extractor.py:223`、`:277` 两个调用方与三个单测。
- **测试夹具一律脱敏**：不得写入真实素材名、真实人名或露骨内容。
- **所有结构过滤在 `normalize_keyword_text(x).casefold()` 之后判断**（该函数会把 `_ - / ~ ( ) .` 替换为空格）。
- 代码注释与提交说明用中文。

---

### Task 1: 候选提取纯函数模块

**Files:**
- Create: `app/services/review_intake_candidates.py`
- Test: `tests/services/test_review_intake_candidates.py`

**Interfaces:**
- Produces:
  - `RawCandidate` dataclass：`text: str`、`source: str`（`hashtag`/`bracket`/`segment`）、`from_parent: bool`、`order: int`
  - `extract_raw_candidates(raw_path: str) -> list[RawCandidate]`：切片 + 结构过滤 + 去重 + 排序，**不查库**
  - `NOISE_TOKENS: frozenset[str]`：技术噪声表

- [ ] **Step 1: 写失败测试**（脱敏假路径，覆盖三条规则、结构过滤、排序、去重）
- [ ] **Step 2: 运行确认失败** —— `.venv/bin/pytest tests/services/test_review_intake_candidates.py -v`，预期 ImportError
- [ ] **Step 3: 实现模块**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**

关键实现要点（来自设计 §3.2–§3.3、§3.6）：
- 取材：`[父目录名, 文件名去扩展名]`
- hashtag：`#([^\s#]+)`，捕获后 `strip("._- ")`
- bracket：`[【「『［\[]([^】」』］\]]+)[】」』］\]]`
- segment：剥前缀 `^\d+\s*[-_.]?\s*` → 挖掉已命中区间 → 按 `[\s_,，:：\-/|~()（）\[\]【】]+` 切
- 过滤（归一化后）：长度 <2 或 >16；纯数字/纯空白；按空格切分后每段都是纯数字；命中 `NOISE_TOKENS`；纯 ASCII 且长度 <3
- 去重：同归一化文本保留排名最高一条
- 排序键：来源(hashtag>bracket>segment) → from_parent 优先 → 长度 2–10 优先 → 出现顺序

---

### Task 2: 接入 ReviewIntakeService

**Files:**
- Modify: `app/services/review_intake_service.py`（`_extract_and_resolve_keywords`）
- Modify: `tests/services/test_review_intake_service.py`（既有断言编码的是旧行为，需按新行为更新）

**Interfaces:**
- Consumes: Task 1 的 `extract_raw_candidates`
- Produces: `_extract_and_resolve_keywords` 签名不变，行为改变

- [ ] **Step 1: 更新既有测试到新预期**（`作品【姝姬娘娘】` 现在还会切出 `作品`、`finish`，断言改为「姝姬娘娘 排第一」而非「候选恰好等于一条」）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现** —— 改调新模块；忽略词一次性批量加载（参照 `app/api/routes/extractor.py:29-34`）；`examples=[]`；落库顺序 = 候选组→提示组；数量上限 12（候选组 ≤9 + 提示组 ≤3）；`pattern`/`flags`/`group_index` 参数保留但不再使用，`limit` 映射为落库上限
- [ ] **Step 4: 全套后端测试通过** —— `.venv/bin/pytest tests/services tests/api -q`
- [ ] **Step 5: 提交**

---

### Task 3: 回归验证脚本（主要成功标准）

**Files:**
- Create: `scripts/verify_review_intake_candidates.py`

- [ ] **Step 1: 实现脚本**
  - 连 `DATABASE_URL`（可 `--database-url` 覆盖），**只读**
  - 只跑纯提取链路（Task 1 模块 + 忽略库过滤），**不跑注册表状态标注**（规避数据泄漏，见设计 §6.1）
  - 指标一：67 条零候选集，答案是否在前 5 → 目标 ≥80%
  - 指标二：205 条旧命中集，答案是否仍在前 5 → 目标不低于旧规则
  - 命中口径：归一化后精确相等；另报「候选任意位置包含答案」的宽口径
  - 默认只输出汇总数字，明细需 `--show-details`
  - `--apply-pending`：用新规则重算所有 `pending` 项候选并落库（唯一的写操作）
- [ ] **Step 2: 连生产库只读运行，拿到两个指标**
- [ ] **Step 3: 未达标则回到 Task 1 调规则，达标才继续**
- [ ] **Step 4: 提交**

---

### Task 4: 前端候选可点选

**Files:**
- Modify: `frontend/src/pages/ReviewIntakePage.tsx`

- [ ] **Step 1: 候选标签改为可点击** —— 点击写入 `keywordDrafts[item.id]`
- [ ] **Step 2: 平铺前 5 + 「更多」折叠**（纯前端渲染，不请求接口）
- [ ] **Step 3: 提示组（existing/conflict）置顶单独一行**，前缀「库里已有」/「冲突」
- [ ] **Step 4: 面板标题栏加颜色图例**
- [ ] **Step 5: 预填策略** —— `defaultKeyword` 只采纳 `source` 为 `hashtag`/`bracket` 的候选；`segment` 来源不预填（设计 §3.7）
- [ ] **Step 6: `npm run build` 通过**
- [ ] **Step 7: 提交**

---

### Task 5: 前端「×」加入忽略库

**Files:**
- Modify: `frontend/src/api/reviewIntake.ts`（新增 `createIgnoreKeyword`）
- Modify: `frontend/src/pages/ReviewIntakePage.tsx`

- [ ] **Step 1: 加 `createIgnoreKeyword(word)`** —— POST `/keywords`，`keyword_type='ignore'`
- [ ] **Step 2: 候选标签加 ×**，仅在 `new`/`similar` 状态显示（`existing`/`conflict` 上会静默无效，见设计 §4.5）
- [ ] **Step 3: Popconfirm 二次确认**
- [ ] **Step 4: 成功后本地移除所有已加载行中同归一化文本的标签**（状态是投递时刻快照，重拉列表不会变灰）
- [ ] **Step 5: `npm run build` 通过**
- [ ] **Step 6: 提交**

---

### Task 6: 上线部署与生产确认

- [ ] **Step 1: 推送到 GitHub**
- [ ] **Step 2: 服务器 `git pull` + `docker compose -f docker/docker-compose.yml up -d --build app`**
- [ ] **Step 3: 健康检查**（首页 200、`/api/*` 401 鉴权正常、容器 healthy）
- [ ] **Step 4: 生产上跑一次 `--apply-pending`**，回填当前 12 条待审的候选
- [ ] **Step 5: 追加 `PROGRESS.md`**

---

## 自检

- 设计文档 §3.1–§3.8 → Task 1、Task 2 覆盖
- 设计文档 §4（七项交互）→ Task 4、Task 5 覆盖
- 设计文档 §5（接口零变更、复用 `POST /keywords`）→ Task 5 Step 1
- 设计文档 §6.1（双指标、纯提取口径、隐私输出）→ Task 3
- 设计文档 §6.2（脱敏夹具）→ Task 1 全局约束
- 设计文档 §6.3（生产人工确认）→ Task 6
