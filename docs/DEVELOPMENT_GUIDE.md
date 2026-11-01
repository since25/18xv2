# 18x_v2 开发与部署指南

> 版本：v2（2026-04-21）
> 配套阅读：`PROGRESS.md`、`docs/GAP_ANALYSIS.md`、`docker/README.md`

这份文档用于回答三件事：

1. 当前项目已经做到什么程度。
2. 本地与 Docker/Unraid 应该怎么启动。
3. 后续继续开发时，哪些运行约束不能踩。

---

## 一、当前基线

- 主应用：FastAPI + React/Vite + Ant Design。
- 默认生产数据库：PostgreSQL。
- 历史 SQLite：保留在 `data/storage_organizer.db`，仅作为备份或迁移来源。
- 生产 Docker 路径：`root@tank61213:/mnt/user/docker1/18xv2`（SSH：`root@192.168.70.138`）。
- 反向代理：Lucky。
- 登录模型：单管理员账号，用户名来自 `.env`，首次启动自动生成密码并只在容器日志打印一次。
- 115 授权：
  - Cookie 扫码登录是独立功能，不能和 Open API 授权混用。
  - Open API 已改为扫码授权主流程。
  - 不再在启动时粗暴刷新 token，而是记录状态并按需处理。
- RN 下载器集成：
  - 通过下载器 Web API 同步资源包和任务进度，不共享下载器 SQLite。
  - 资源包按 `index_revision` 生成版本化候选；新版本提交使用 RN 的 `mode=incremental`，只下载此前完整成功版本中没有的媒体。
  - 18x 的任务同步会追加任务和文件历史快照，可通过 `/api/downloader/tasks/{task_id}/history` 查询。
  - 白名单/别名只生成待确认候选，黑名单负责排除；人工确认后才创建精确下载批次。
  - `DOWNLOADER_ENABLED` 未开启或地址为空时，不启动同步 sweeper。

---

## 二、硬约束

1. 不覆盖 `data/` 等运行时持久化目录，除非明确要求。
2. Cookie 扫码登录和 115 Open API 扫码授权必须保持两套独立流程。
3. Docker 相关配置统一放在 `docker/` 目录维护。
4. 后端涉及 115 真实操作的服务必须注入 `Real115Client`，不能偷偷回退到 `Fake115Client`。
5. 命中重建当前只按节点名匹配，不允许重新引入整条路径扩散命中的旧逻辑。
6. 服务器同步通过 Git 完成；部署前默认先确认本地改动是否已推送到远端仓库，再由服务器拉取。

---

## 三、本地开发

### 3.1 Python 环境

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
```

### 3.2 启动后端

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

常用入口：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/api/healthz`
- `http://127.0.0.1:8000/docs`

### 3.3 启动前端

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2/frontend
npm install
npm run dev
```

---

## 四、配置与数据

| 类型 | 位置 | 说明 |
|---|---|---|
| 环境变量 | `.env` | 本地私有，不入库 |
| Open API token | `data/tokens.json` | 运行中刷新后写回这里 |
| PostgreSQL 数据 | `data/postgres/` | Docker 默认生产数据库 |
| SQLite 备份 | `data/storage_organizer.db` | 历史库，不再作为默认生产库 |
| 管理员账号 | `data/auth.json` | 首次启动自动创建 |
| 会话文件 | `data/auth_sessions.json` | 登录态持久化 |
| Cookie 文件 | `data/cookies/` | 供 Cookie 扫码/目录树导出使用 |

RN 下载器相关配置只放在 `.env`：`DOWNLOADER_BASE_URL`、`DOWNLOADER_PASSWORD`、`DOWNLOADER_NODE_KEY`、`DOWNLOADER_TIMEOUT_SECONDS`、`DOWNLOADER_SYNC_INTERVAL_SECONDS`（资源包同步间隔）、`DOWNLOADER_TASK_SYNC_INTERVAL_SECONDS`（任务进度同步间隔，默认 15 秒）。密码不写入数据库、日志或前端响应。

后台同步分成两个独立循环：资源包同步和任务同步互不等待。每轮同步在一个已登录会话内完成（`with DownloaderClient(...)`），不再每个请求重新登录。任务同步对「已结束且 RN 更新时间未变」的任务不再拉详情；RN 任务载荷只带 `chat_id`，频道名按资源包的 `source_chat_id` 补齐。

页面入口为 `/downloader`，后端控制面为 `/downloader/*`。下载器页面采用候选收件箱和任务看板双流模型：收件箱处理候选确认、忽略和 5 秒撤销，任务看板处理任务筛选与历史，点击任务后通过侧边检查抽屉查看文件详情。候选携带资源包版本号；确认新版本后由 RN 增量批次跳过旧版本完整成功的消息。现场验收时先用“同步资源包”检查连接，再人工选择一条候选提交；测试环境只使用 mock HTTP 客户端。

### 4.1 下载器接口与页面参数

下载器控制面新增或调整以下接口：

- `GET /downloader/packages?view=candidates|ignored`：收件箱候选/已忽略视图，支持下载状态、白名单词、标题搜索和分页参数。
- `POST /downloader/packages/ignore`、`POST /downloader/packages/unignore`：按候选或资源包忽略、恢复候选。`ignore` 也可传 `channel_title`，忽略该频道当前在收件箱里的全部资源包，响应返回 `package_ids` 供撤销。
- 收件箱条目带 `last_download_error`（本包最近一次下载失败原因码）和 `channel_error`（频道级错误码，如 `channel_unavailable`），来自 RN 资源包载荷；前端在 `utils/statusText.ts` 的 `downloaderErrorText` 中翻译为中文。
- `GET /downloader/tasks`：支持 `status`、`since`、`until`、`channel`、`keyword_entry_id`、`search`、`page`、`page_size` 筛选；只显式传 `limit` 时保持旧任务列表格式和行为。
- `GET /downloader/tasks/{id}/detail`：返回任务摘要、文件列表和失败文件信息。
- `GET /downloader/summary`、`GET /downloader/channels`：返回任务统计和频道筛选项。
- `POST /downloader/tasks/{id}/retry`：请求体可带 `only_failed`；RN 当前按任务重试且本来只重试失败文件，参数为兼容保留，对 RN 行为没有额外影响。

数据库迁移 `20261101_0015` 为资源包增加 `ignored_at`、`ignored_reason`、`completed_media_count`；为任务快照增加 `remote_created_at`、`remote_updated_at`、`finished_at`、`total_bytes`、`downloaded_bytes`、`channel_title`，并增加按节点和远端创建时间、按节点和状态的索引。需要回滚时执行 `alembic downgrade 20261031_0014`。

前端支持以下 URL 参数：`/downloader?view=inbox|tasks` 切换双流视图；任务看板可用 `task=<id>` 直接打开检查抽屉；任务筛选使用 `status`、`range`、`channel`、`kw`、`q`、`page`。

与规范的偏差：

1. 单文件重试不可行：RN 只有按任务重试接口，因此抽屉提供“重试全部失败文件”，不提供单项重试。
2. “有更新 +N”依赖 `completed_media_count`；历史上没有该字段的已完成资源包只能显示“有更新”，不能计算 N。
3. 提交接受 `pending` 候选；新页面的勾选是前端状态，保留 `/select` 以兼容旧调用。
4. 文件历史读取 `total_size_bytes`、`downloaded_size_bytes`、`download_speed_bytes`，修复把格式化字符串误当整数导致字节数为 0 的问题。

### 4.2 远程测试（Spark）

使用 `scripts/remote-test.sh` 在远程测试机运行检查：

```bash
scripts/remote-test.sh backend
scripts/remote-test.sh frontend
scripts/remote-test.sh all
```

可通过 `REMOTE_TEST_HOST` 指定 SSH 主机别名（默认 `spark`），通过 `REMOTE_TEST_ROOT` 指定远程根目录（默认 `~/ci/18x_v2`）。脚本不同步 `.git`、`.venv`、`node_modules`、前端构建产物、`.env`、数据目录、cookies 文件及测试缓存；每个 worktree 使用远程独立子目录。后端环境复刻本机 venv：由 micromamba 提供相同 Python 小版本，按本机 `pip freeze` 冻结清单安装依赖，并从本机复制 `p115client` 包，避免间接依赖漂移。后端默认运行 `pytest tests -q -n 16`，前端测试使用 `--maxWorkers=6`，随后执行 build 和 lint。完整日志保存在远程检出目录的 `.remote-test-logs/`，本机只显示摘要和日志路径。

---

## 五、115 授权与状态模型

### 5.1 Open API 当前策略

- 启动时只初始化客户端，不再主动强刷 token。
- token 状态通过以下字段对外暴露：
  - `token_status`
  - `token_error`
  - `token_error_at`
  - `token_expires_at`
- 当前状态重点区分：
  - `ok`
  - `missing`
  - `cooldown`
  - `reauth_required`
  - `error`

### 5.2 什么时候刷新 token

- access token 接近过期且存在 refresh token 时，才尝试刷新。
- 如果返回 `40140117`，视为刷新过于频繁，进入冷却状态。
- 如果 refresh token 本身失效，则进入 `reauth_required`，需要重新扫码授权。

### 5.3 当前推荐操作

- 正常使用时，从 Web 端授权中心进入 Open API 扫码授权。
- Cookie 扫码仅用于 cookies 相关独立功能，不参与 Open API token 流程。

---

## 六、Docker 与 Unraid

### 6.1 本地 Docker 开发

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
docker compose -f docker/docker-compose.dev.yml up --build
```

### 6.2 生产部署路径

服务器信息：

- 主机：`root@192.168.70.138`
- 主机名：`tank61213`
- 项目目录：`/mnt/user/docker1/18xv2`
- 同步方式：Git（远端仓库由服务器目录中的 `.git/config` 决定）

### 6.3 推荐部署流程

1. 本地确认改动可用。
2. 将本地改动推送到 Git 远端。
3. 在服务器目录执行 `git pull --ff-only`。
4. 在服务器目录执行 Docker 重建。
5. 查看 `docker-app-1` 和 `docker-postgres-1` 状态。
6. 用 `curl http://127.0.0.1:8010/api/healthz` 验证服务。

参考命令：

```bash
git push

ssh root@192.168.70.138
cd /mnt/user/docker1/18xv2
git pull --ff-only
docker compose -f docker/docker-compose.yml up -d --build
docker compose ps
docker logs --tail 200 docker-app-1
```

---

## 七、Lucky 反代要求

- Lucky 反代目标保持为 `http://<server-ip>:8010`。
- 域名访问必须启用 HTTPS。
- 需要透传 `Host`。
- 需要透传 `X-Forwarded-Proto=https`。
- 登录 Cookie 依赖 HTTPS 场景，HTTP/IP:端口方式只适合临时排查，不适合作为正式入口。

---

## 八、数据库说明

- 当前默认生产环境必须使用 PostgreSQL。
- SQLite 之前暴露出长事务和并发读取下的 `database is locked` 问题。
- 已提供迁移脚本：

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-url sqlite:///./data/storage_organizer.db \
  --postgres-url postgresql+psycopg://postgres:postgres@127.0.0.1:5432/organizer
```

---

## 九、关键词命中重建说明

- 当前逻辑只匹配节点名，不匹配整条路径。
- 已使用预编译匹配器和批量写入。
- 根目录级全量命中重建已经验证可快速完成。
- 后续如果要恢复路径语义，必须设计成不产生祖先路径扩散重复命中。

---

## 十、常用命令

```bash
# 后端测试
.venv/bin/python -m pytest tests/ -v

# Open API 授权脚本
.venv/bin/python scripts/115_device_auth.py

# 冒烟测试
.venv/bin/python scripts/115_real_smoke.py

# 迁移 SQLite 到 PostgreSQL
.venv/bin/python scripts/migrate_sqlite_to_postgres.py --help
```

---

## 十一、下一步主要工作

1. 继续补全 `docs/` 下架构、运维与 API 说明。
2. 持续整理 `docs/115开放平台/` 的导出格式，减少语雀 HTML 噪音。
3. 继续观察历史任务与历史命中记录在 PostgreSQL 下的语义一致性。
