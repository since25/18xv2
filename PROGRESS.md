# 18x_v2 工作进度快照

> 最近更新：2026-04-21（晚）

---

## 一、项目基本信息

- 项目根目录：`/Users/wangyichuan/Desktop/wangcodemac/18x_v2`
- 技术栈：Python 3.12、FastAPI、Uvicorn、115 客户端服务
- 应用入口：`app/main.py`
- 运行测试：`.venv/bin/python -m pytest tests/ -v`

---

## 二、已完成（2026-04-19）

### P0 全部完成

1. **P0-3 QR 登录下拉框修复** ✅
2. **P0-1 启动时 token 检查** ✅
3. **P0-2 Fake→Real 客户端** ✅
4. **P0-4 docker/ 目录** ✅

### P1-1 CLI 脚本完成（前 5 个）✅

| 脚本 | 说明 |
|---|---|
| `scripts/115_device_auth.py` | 设备码 QR 扫码授权（支持保存 PNG） |
| `scripts/115_auth_code.py` | 授权码换 token |
| `scripts/sync_strategy_rules.py` | rules.yaml → DB 同步 |
| `scripts/115_real_smoke.py` | API 冒烟测试（只读+可选写） |
| `scripts/keyword_extractor.py` | 关键词提取 CLI |

### P1-3 测试套件完成，40/40 全绿 ✅

### 真机联调完成（2026-04-19）✅

**完整链路已跑通：**

1. 设备码授权 → `data/tokens.json`
2. `fs_export_dir`（p115client + cookies）导出目录树 → 下载 → 上传 `/imports/tree`
3. `POST /keywords/hits/rebuild` → 85 条命中，58 关键词
4. `POST /organize-tasks/generate-from-import` → 11 个任务，31 个歧义跳过
5. `POST /plans/generate-from-tasks` → 9 个计划（7 个无冲突，2 个 duplicate_target）
6. `POST /plans/{id}/execute` → **7 个计划全部执行成功**

---

## 三、已修复问题 / 关键里程碑

### BUG-1：服务启动后首次执行必定 `blocked` ✅（已修复 2026-04-19）

**现象：** 服务刚启动，执行计划时 `api_status=blocked`，错误：`40140117 refresh frequently`。

**根因：**
- lifespan 里 `ensure_fresh_access_token()` 成功刷新了 token
- 执行计划时，`_call(auth_required=True)` 里某个 API 调用返回 `P115AccessTokenError`（40140123~40140126）
- `_is_invalid_access_token_error` 匹配到 → 尝试再次 refresh → 频控 40140117 → 原来直接抛出

**修复：** `_call` 里 `refresh_access_token_and_persist()` 遇频控时，静默更新 `_last_refresh_time` 并用当前 token 重试，不再抛出。

### BUG-2：`_find_child` 精确匹配文件名导致路径解析失败 ✅（已修复）

**现象：** 执行计划时 `blocked`，错误：`Path not found: 根目录/待整理/finish1217/❤️…特辑 绝顶…`

**根因：**
- 115 实际文件名含双空格（`特辑  绝顶`）
- `tree_parser.normalize_name` 把多余空格压缩为单空格（`特辑 绝顶`）
- `_find_child` 用精确字符串匹配 → 找不到

**修复：** `executor.py` 的 `_find_child` 两边都做 `re.sub(r"\s+", " ", s).strip()` 规范化后再比对（`_norm_name` 方法）。

### BUG-3：Docker 构建/启动链路不稳定、README/打包内容不完整 ✅（已修复 2026-04-20 ~ 2026-04-21）

**现象：**
- 服务端首次 `docker compose up -d --build` 时报 `README.md not found`
- 后续镜像内缺少 `scripts/`，导致迁移脚本无法在容器内执行
- Alembic / 构建 / entrypoint 链路多次暴露出部署文档与镜像内容不一致

**修复：**
- 补齐 Docker 构建上下文所需文件
- `docker/Dockerfile` 已纳入 `scripts/`
- `docker/README.md`、`.env.example` 已更新为当前实际部署方式

### BUG-4：登录系统上线后的若干反代/上传问题 ✅（已修复 2026-04-21）

**已修复项：**
- HTTPS 登录后上传目录树报 `413`
- HTTP / IP:端口 下会话不稳定，出现 `Authentication required`
- Lucky 反代下 Cookie `Secure` / 代理头行为不一致
- 首次密码生成、会话文件持久化、退出登录、未登录接口 `401` 均已跑通

### BUG-5：115 Open API 授权链路混乱、token 刷新策略过于粗暴 ✅（已修复 2026-04-21）

**现象：**
- 曾混入 cookies 扫码逻辑，导致 Open API QR 页面展示的并不是 Open API 授权二维码
- 启动时和执行前过度主动刷新 token，导致 `40140117 / 40140125 / 40140126` 相关问题难以定位

**修复：**
- Cookie 扫码登录与 Open API 扫码授权完全拆开
- 新增 `/auth-center/open-api-qr`
- token 状态改为被动缓存检查，不再启动即刷新
- 增加 `token_status / token_error / token_error_at / token_expires_at`
- 记录 `access_token_expires_at`，并支持 `ok / cooldown / reauth_required / missing / error` 状态分类

### BUG-6：SQLite 在大批量关键词命中重建时 `database is locked` ✅（已通过 PostgreSQL 迁移解决）

**现象：**
- 根目录大批量目录树上执行命中重建时，`/imports/data` 等接口报 `500`
- 后台错误为 `sqlite3.OperationalError: database is locked`

**根因：**
- SQLite 不适合当前这种大批量、长事务、同时有前台读请求的场景

**修复：**
- 已完成 SQLite → PostgreSQL 迁移
- Docker 默认数据库已切换到 PostgreSQL
- 迁移脚本已处理旧 SQLite 中的悬空外键数据

### BUG-7：命中重建对整条路径做 contains，导致祖先路径在所有子节点上重复命中，且全量重建极慢 ✅（已修复 2026-04-21 晚）

**现象：**
- 对根目录或大批次做命中重建时，前端看起来像“无响应”
- PostgreSQL 和 app 日志不一定报错，但请求长时间不返回
- 命中结果会被父目录路径扩散放大，例如 `/a/b/c` 的关键词会在 `/a/b/c/d1`、`/a/b/c/d2` 上继续命中

**根因：**
- 旧逻辑对每个节点同时匹配 `raw_name` 和 `raw_path`
- 在大目录树下，本质上形成了 O(节点数 × 关键词数) 的高重复匹配

**修复：**
- 命中重建主流程改为只匹配当前节点名 `raw_name`
- 不再使用整条 `raw_path` 扩散命中
- 使用预编译匹配器 + 批量写入 `keyword_hits`
- 新增重建进度日志
- 用户已验证：全量命中重建现已“非常迅速”

---

## 四、剩余待完成

| 优先级 | 内容 | 说明 |
|---|---|---|
| ~~P1（技术债）~~ | ~~修复 BUG-1~~ | 已修复（2026-04-19） |
| P1（冲突） | 处理 2 个 duplicate_target | BbwThaixxx / 风华正茂；已加 `/organize-tasks/duplicate-conflicts` + `PATCH /{id}` + workbench 审核区，待真机操作 |
| P1（执行稳定性） | 历史计划/任务的冻结 `source_path` 漂移处理 | 目前已确认一批旧 `blocked` 来自远端目录变化后的路径失效，不是 token 问题；需决定是提示更明确，还是引入重新解析 |
| P2 | docs/ 文档补全 | architecture.md / schema.md 等 |
| P2 | API 文档验证 | `/docs` response_model 齐全 |
| P3 | 前端 UI | ✅ 框架搭完（React+Vite+AntD），6 个页面已实现，`frontend/` 目录，`npm run dev` 启动 |

### 2026-04-20 前端联调问题修复排期

按“收益高且 token 消耗低”优先落地：

1. `整理计划` 页面默认筛选改为 `none`，避免首次进入看到全量历史计划。✅ 已完成
2. `整理计划` 页面补真实可用的每页数量控制；修掉当前固定 `30/page` 但 UI 上像可调的错觉。✅ 已完成
3. `整理计划` 页面把“最近任务状态”口径改成和当前后端同步执行模型一致，先去掉误导性的 `running/pending` 期待。✅ 已完成
4. React 前端补 `磁力下载台` 入口和最小页面壳，联通现有后端接口。✅ 已完成
5. `qr-login` 页面增加客户端下拉的服务端直出兜底，避免下拉为空时整页不可用。✅ 已完成
6. 新前端增加统一授权入口，把 `qr-login` 和 `auth-code` 至少串到同一处。✅ 已完成
7. `healthz` / 系统状态页重写说明，明确区分“服务活着”和“115 OpenAPI token 就绪”。✅ 已完成
8. 评估“refresh token 失效后扫码直接回写 token”的方案；此项成本高，放最后。⏳ 未开始

### 2026-04-21 登录系统上线完成 ✅

1. 已增加单管理员登录系统，用户名来自 `.env` 中的 `AUTH_USERNAME`
2. 首次 Docker 启动会生成一次随机密码，写入 `data/auth.json`，并仅在容器日志打印一次
3. 已增加服务端会话文件 `data/auth_sessions.json`
4. 前端已增加 `/login` 登录页、会话检查与退出登录
5. 后端已对管理接口增加登录保护；未登录时敏感接口返回 `401`
6. 已补 `tests/auth/*`，当前认证相关测试 `8/8` 全绿
7. Lucky 反代部署文档已补充 HTTPS / `X-Forwarded-Proto` / 首次密码说明

### 2026-04-21 PostgreSQL 迁移完成 ✅

1. Docker 默认业务数据库已切换为 PostgreSQL（`postgres:16-alpine`）
2. 现有 SQLite 数据已迁移至 PostgreSQL，原 `data/storage_organizer.db` 仍保留作为回滚备份
3. 新增 `scripts/migrate_sqlite_to_postgres.py`
4. 迁移过程中已自动清理旧 SQLite 历史脏数据中的悬空外键（可空外键置为 `NULL`）
5. 服务端当前已确认基于 PostgreSQL 正常启动、登录、读取 `imports/data` 与 `system-status`

### 2026-04-21 命中重建性能与规则收敛完成 ✅

1. 命中重建不再基于整条路径扩散命中，只匹配当前节点名
2. 已加入批量写入与进度日志
3. 本地测试已更新并全绿（当前 `64 passed`）
4. 用户已确认线上全量命中重建速度显著提升，当前主问题已解决

### 当前待观察项

1. 迁移后数据库主问题已解决，但历史任务/历史命中记录中的语义完整性仍需持续观察
2. 若未来需要重新引入“路径语义”匹配，必须避免回到祖先路径扩散命中的旧设计

---

## 五、cookies 文件位置

真机联调依赖 cookies（用于 `fs_export_dir` 导出目录树）：

```
/Users/wangyichuan/Desktop/wangcodemac/p115client/cookies/
115-cookies-wechatmini-e612967902aa092dbbf5d5f4d60c7f08e090869b-20260417-154257.txt
```

---

## 六、关键命令

```bash
# 启动服务
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 重新授权（token 失效时）
.venv/bin/python scripts/115_device_auth.py

# 导出目录树（需要 cookies）
# 见 scripts/ 目录，或直接 Web UI /imports

# 冒烟测试
.venv/bin/python scripts/115_real_smoke.py
.venv/bin/python scripts/115_real_smoke.py --no-dry-run

# 测试套件
.venv/bin/python -m pytest tests/ -v
```

---

## 七、前端开发需求（P3）

**技术选型：** React + Vite + Ant Design，`frontend/` 目录，开发时 proxy 到 `:8000`，生产 Nginx 代理。

**核心痛点（驱动原因）：**
- 分页/筛选逻辑写在 HTML 里每次都要改
- 页面一次性展示太多数据，缺少折叠/懒加载
- 命中日志、执行日志分散在不同页面，上下文割裂
- 日志内容不够详细，看不出整个操作链路
- 后续加功能时改 HTML 非常吃力

**页面清单：**

| 页面 | 说明 |
|---|---|
| `/imports` | 导入批次列表（分页表格）+ 上传目录树入口 |
| `/nodes` | 节点列表（按批次/关键词/层级筛选，Table 带分页） |
| `/keywords` | 关键词管理（列表、别名、操作日志合并展示） |
| `/plans` | 整理计划列表（状态筛选、冲突标红、一键执行） |
| `/plans/:id` | 计划详情（每条 item 的来源路径 → 目标路径 + 冲突原因） |
| `/executor` | 执行日志（Timeline 组件，命中 → 任务生成 → 计划执行 全链路） |
| `/organize-tasks` | 待整理任务（歧义冲突审核、手动指定目标） |
| `/settings` | token 状态、规则文件路径、限流参数等 |

**关键 UI 需求：**
- 执行日志用 Timeline 组件，一条记录包含：关键词命中 → 任务生成 → 计划 item → 执行结果
- 冲突任务（duplicate_target / ambiguous）有专门的审核视图，可选择保留哪一个
- 计划列表支持按关键词分组展示（和当前 `generate-from-tasks` 返回结构对应）
- 所有表格支持前端分页 + 关键词搜索，不依赖后端分页逻辑
- 操作结果（执行成功/失败）有 Toast 通知

## 八、下次接手引导语

```
我在继续 /Users/wangyichuan/Desktop/wangcodemac/18x_v2 项目。
请先 Read PROGRESS.md 恢复上下文。
当前状态：登录系统、Open API 扫码授权、Docker 部署、PostgreSQL 迁移、关键词命中重建性能问题均已完成并上线验证。
重点待办：历史计划 `source_path` 漂移处理、2 个 duplicate_target 冲突任务、P2 文档补全、P3 前端细化。
```
