# Docker 全栈单镜像部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端（React+Vite+AntD）打包进单个 Docker 镜像，Nginx 托管静态文件并反代 FastAPI，Unraid 上 `docker compose up` 一键启动。

**Architecture:** 多阶段 Dockerfile，Stage 1 用 Node 构建前端 dist，Stage 2 用 Python slim 安装依赖 + nginx + supervisor，supervisord 同时管理 nginx（:80）和 uvicorn（127.0.0.1:8000）。Nginx 将 `/api/*` 反代至 uvicorn，其余路由返回 SPA index.html。

**Tech Stack:** Docker multi-stage, Node 20 Alpine, Python 3.12 slim, Nginx, Supervisor, FastAPI/Uvicorn

---

## 文件清单

| 文件 | 操作 |
|---|---|
| `docker/nginx.conf` | 新增 |
| `docker/supervisord.conf` | 新增 |
| `docker/Dockerfile` | 重写（多阶段） |
| `docker/entrypoint.sh` | 修改（启动 supervisord） |
| `docker/docker-compose.yml` | 修改（端口 80） |
| `docker/README.md` | 更新部署文档 |

---

### Task 1：新增 docker/nginx.conf

**Files:**
- Create: `docker/nginx.conf`

- [ ] **Step 1：创建 nginx.conf**

```nginx
server {
    listen 80;
    server_name _;

    root /app/static;
    index index.html;

    # 前端静态资源（Vite 构建产物，带 hash，长缓存）
    location /assets/ {
        expires max;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    # API 反代：去掉 /api 前缀后转发给 uvicorn
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # SPA fallback：其余路径返回 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2：验证 nginx 配置语法（本地有 nginx 时可选）**

```bash
# 可选：本地有 nginx 时验证
nginx -t -c $(pwd)/docker/nginx.conf 2>/dev/null || echo "跳过本地验证，构建时会验证"
```

- [ ] **Step 3：commit**

```bash
git add docker/nginx.conf
git commit -m "feat(docker): 新增 nginx 配置，反代 /api/* 至 uvicorn"
```

---

### Task 2：新增 docker/supervisord.conf

**Files:**
- Create: `docker/supervisord.conf`

- [ ] **Step 1：创建 supervisord.conf**

```ini
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/tmp/supervisord.pid

[program:nginx]
command=nginx -g "daemon off;"
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:uvicorn]
command=uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
```

- [ ] **Step 2：commit**

```bash
git add docker/supervisord.conf
git commit -m "feat(docker): 新增 supervisord 配置，管理 nginx + uvicorn"
```

---

### Task 3：重写 docker/Dockerfile 为多阶段构建

**Files:**
- Modify: `docker/Dockerfile`

- [ ] **Step 1：重写 Dockerfile**

```dockerfile
# ── Stage 1: 构建前端 ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ .
RUN npm run build

# ── Stage 2: 生产镜像 ──────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# 安装 nginx 和 supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# 复制应用代码
COPY . .

# 复制前端构建产物
COPY --from=frontend-builder /frontend/dist /app/static

# 复制 nginx 和 supervisord 配置
COPY docker/nginx.conf /etc/nginx/sites-enabled/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# data/ 通过 volume 挂载持久化
RUN mkdir -p data

# 复制并设置 entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2：commit**

```bash
git add docker/Dockerfile
git commit -m "feat(docker): 多阶段构建，Stage1 编译前端，Stage2 含 nginx+supervisor"
```

---

### Task 4：修改 docker/entrypoint.sh

**Files:**
- Modify: `docker/entrypoint.sh`

- [ ] **Step 1：更新 entrypoint.sh**

```sh
#!/bin/sh
set -e

# 启动前执行数据库迁移，确保 schema 是最新的
echo "[entrypoint] 执行 alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] 启动 supervisord（nginx + uvicorn）..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
```

- [ ] **Step 2：commit**

```bash
git add docker/entrypoint.sh
git commit -m "feat(docker): entrypoint 改为启动 supervisord"
```

---

### Task 5：更新 docker/docker-compose.yml

**Files:**
- Modify: `docker/docker-compose.yml`

- [ ] **Step 1：更新 docker-compose.yml**

```yaml
services:
  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "80:80"
    env_file:
      - ../.env
    volumes:
      # 持久化数据：token 刷新状态、QR cookies、SQLite DB
      - ../data:/app/data
    restart: unless-stopped
```

- [ ] **Step 2：commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(docker): compose 端口改为 80，对外只暴露单端口"
```

---

### Task 6：更新 docker/README.md

**Files:**
- Modify: `docker/README.md`

- [ ] **Step 1：更新 README.md**

```markdown
# Docker 部署指南

## 目录结构

```
docker/
├── Dockerfile          # 生产镜像（多阶段：前端构建 + nginx + uvicorn）
├── Dockerfile.dev      # 开发镜像（仅后端热重载）
├── docker-compose.yml  # 生产编排（单端口 80）
├── docker-compose.dev.yml  # 开发编排
├── nginx.conf          # Nginx：/api/* 反代，其余 SPA fallback
├── supervisord.conf    # 管理 nginx + uvicorn 两个进程
├── entrypoint.sh       # 启动前自动运行 alembic upgrade head，然后启动 supervisord
└── README.md
```

## 本地开发

开发模式只跑后端，前端用 `npm run dev` 单独启动：

```bash
# 后端（端口 8000）
docker compose -f docker/docker-compose.dev.yml up --build

# 前端（另开终端，端口 5173，自动代理 /api → 8000）
cd frontend && npm run dev
```

## 生产构建（本地验证）

```bash
cd /path/to/18x_v2
cp .env.example .env   # 填写 115 凭据

# 构建并启动（单镜像，端口 80）
docker compose -f docker/docker-compose.yml up --build

# 验证
curl http://127.0.0.1/api/healthz
# 期望：{"status":"ok","client_115":true/false,...}

# 访问前端
open http://127.0.0.1
```

## Unraid 部署

```bash
# 1. 本地推送代码
git push

# 2. SSH 到 Unraid
ssh root@192.168.70.138
cd /mnt/user/docker1/18xv2

# 3. 服务器通过 Git 同步
git pull --ff-only

# 4. 复制并填写 .env
cp .env.example .env
# 编辑 .env，填入 APP_ID / APP_SECRET 等

# 5. 构建并启动
docker compose -f docker/docker-compose.yml up -d --build

# 6. 查看日志
docker compose -f docker/docker-compose.yml logs -f

# 7. 访问
# 前端：http://<unraid-ip>/
# API：http://<unraid-ip>/api/healthz
```

> 如需自定义端口（如 18080），修改 docker-compose.yml 中 `"80:80"` 为 `"18080:80"`

## 持久化数据

| 路径 | 内容 |
|---|---|
| `data/tokens.json` | 115 OAuth token，刷新后自动写回 |
| `data/cookies/` | QR 登录 Cookie 文件 |
| `data/storage_organizer.db` | SQLite 数据库（DATABASE_URL 为默认值时） |

volume 挂载为 `../data:/app/data`，重建容器不会丢失数据。

## 授权问题排查

启动后若 `/api/healthz` 返回 `client_115: false`：
1. 访问 `http://<host>/tools/qr-login` 扫码授权
2. 或访问 `http://<host>/tools/auth-code` 粘贴授权码
3. 授权成功后 `/api/healthz` 应返回 `client_115: true`（无需重启）

## 回滚

```bash
# 保留 data/ 不动，回滚代码后重建镜像
docker compose -f docker/docker-compose.yml up -d --build
```
```

- [ ] **Step 2：commit**

```bash
git add docker/README.md
git commit -m "docs(docker): 更新部署文档，说明单端口 80 和 Unraid 部署步骤"
```

---

### Task 7：本地构建验证

- [ ] **Step 1：构建镜像，确认无报错**

```bash
cd /path/to/18x_v2
docker compose -f docker/docker-compose.yml build
```

期望：构建成功，无 ERROR。

- [ ] **Step 2：启动容器**

```bash
docker compose -f docker/docker-compose.yml up -d
```

- [ ] **Step 3：验证后端可达**

```bash
curl -s http://127.0.0.1/api/healthz
```

期望：返回 JSON，包含 `"status":"ok"`。

- [ ] **Step 4：验证前端可达**

```bash
curl -s http://127.0.0.1/ | head -5
```

期望：返回 HTML，包含 `<div id="root">`。

- [ ] **Step 5：停止并清理**

```bash
docker compose -f docker/docker-compose.yml down
```
