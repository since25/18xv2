# Docker 全栈单镜像部署设计

日期：2026-04-20

## 目标

将前端（React+Vite+AntD）打包进后端 Docker 镜像，在 Unraid 上用单个 `docker compose up` 启动，对外只暴露一个端口。

## 方案：单镜像 + supervisord（方案 A）

### 构建流程

多阶段 Dockerfile：

1. **Stage 1（node:20-alpine）**：在 `frontend/` 目录执行 `npm ci && npm run build`，产物输出到 `/dist`
2. **Stage 2（python:3.12-slim）**：安装 Python 依赖 + nginx + supervisor，将 Stage 1 的 `/dist` 复制到 `/app/static`

### 运行时架构

```
外部请求 → Nginx:80
              ├── /api/* → rewrite 去掉 /api 前缀 → proxy_pass http://127.0.0.1:8000 (uvicorn)
              └── /* → /app/static/index.html (SPA fallback)
```

supervisord 同时管理两个进程：
- `nginx -g 'daemon off;'`
- `uvicorn app.main:app --host 127.0.0.1 --port 8000`

uvicorn 只监听 127.0.0.1，不对外暴露。

### Nginx 路由规则

- `/api/*` → proxy_pass，rewrite 去掉 `/api` 前缀后转发给 uvicorn
- `/assets/*` → 静态资源，`Cache-Control: max-age=31536000, immutable`
- `/*` → `try_files $uri /index.html`（SPA fallback）

### entrypoint 启动顺序

1. `alembic upgrade head`（数据库迁移）
2. `exec supervisord -c /etc/supervisor/conf.d/supervisord.conf`

### 文件变更清单

| 文件 | 操作 |
|---|---|
| `docker/Dockerfile` | 重写为多阶段构建 |
| `docker/nginx.conf` | 新增 Nginx 配置 |
| `docker/supervisord.conf` | 新增 supervisord 配置 |
| `docker/docker-compose.yml` | 端口改为 80:80 |
| `docker/entrypoint.sh` | 改为启动 supervisord |
| `docker/README.md` | 更新 Unraid 部署步骤 |

### docker-compose.yml

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
      - ../data:/app/data
    restart: unless-stopped
```

Unraid 用户可将 `80:80` 改为 `18080:80` 等自定义端口。

## 不在范围内

- dev 模式（`docker-compose.dev.yml`）保持不变，仍然只跑后端
- 前端 `npm run dev` 开发流程不受影响
