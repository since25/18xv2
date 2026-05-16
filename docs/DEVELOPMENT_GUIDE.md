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
- 生产 Docker 路径：`/mnt/user/docker1/18x_v2`。
- 反向代理：Lucky。
- 登录模型：单管理员账号，用户名来自 `.env`，首次启动自动生成密码并只在容器日志打印一次。
- 115 授权：
  - Cookie 扫码登录是独立功能，不能和 Open API 授权混用。
  - Open API 已改为扫码授权主流程。
  - 不再在启动时粗暴刷新 token，而是记录状态并按需处理。

---

## 二、硬约束

1. 不覆盖 `data/` 等运行时持久化目录，除非明确要求。
2. Cookie 扫码登录和 115 Open API 扫码授权必须保持两套独立流程。
3. Docker 相关配置统一放在 `docker/` 目录维护。
4. 后端涉及 115 真实操作的服务必须注入 `Real115Client`，不能偷偷回退到 `Fake115Client`。
5. 命中重建当前只按节点名匹配，不允许重新引入整条路径扩散命中的旧逻辑。
6. 服务器同步前，默认先确认是否需要把本地改动推到 `192.168.70.138`。

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
- 项目目录：`/mnt/user/docker1/18x_v2`

### 6.3 推荐部署流程

1. 本地确认改动可用。
2. 同步代码到服务器，但不覆盖 `data/`。
3. 在服务器目录执行 Docker 重建。
4. 查看 `docker-app-1` 和 `docker-postgres-1` 状态。
5. 用 `curl http://127.0.0.1:8010/api/healthz` 验证服务。

参考命令：

```bash
rsync -avz --exclude .git --exclude .venv --exclude data \
  /Users/wangyichuan/Desktop/wangcodemac/18x_v2/ \
  root@192.168.70.138:/mnt/user/docker1/18x_v2/

ssh root@192.168.70.138
cd /mnt/user/docker1/18x_v2/docker
docker compose up -d --build
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
