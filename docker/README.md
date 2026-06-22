# Docker 部署指南

## 目录结构

```
docker/
├── Dockerfile              # 前端构建 + Python/nginx/supervisor 生产镜像
├── Dockerfile.dev          # 开发镜像（热重载）
├── docker-compose.yml      # 生产编排（app + PostgreSQL，对外 8010）
├── docker-compose.dev.yml  # 开发编排
├── entrypoint.sh           # 迁移后启动 supervisord
├── nginx.conf              # 静态托管 + /api 反代
├── supervisord.conf        # 管理 nginx + uvicorn
└── README.md
```

## 本地开发

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
cp .env.example .env   # 填写 115 凭据（如有）

# 开发模式（热重载，源码挂载）
docker compose -f docker/docker-compose.dev.yml up --build

# 验证
curl http://127.0.0.1:8000/healthz
# 期望：{"status":"ok","client_115":true/false,...}
```

## 生产运行架构

- Nginx 监听容器内 `80`，宿主机通过 `8010` 暴露服务
- `/api/*` 反代到 `uvicorn 127.0.0.1:8000`，并去掉 `/api` 前缀
- 其余路径走 SPA fallback，返回 `/app/static/index.html`
- `entrypoint.sh` 启动前先执行 `alembic upgrade head`
- `supervisord` 同时管理 `nginx` 与 `uvicorn`
- 单管理员登录启用后，前端通过 `/api/auth/*` 走服务端会话 Cookie
- PostgreSQL 作为默认业务数据库，数据目录持久化到 `data/postgres/`

## 数据库切换说明

- 现在 Docker 默认走 PostgreSQL，不再建议继续把业务数据长期放在 SQLite
- 现有 `data/storage_organizer.db` 不会被自动删除或覆盖
- 如果你已有 SQLite 历史数据，先完成一次 PostgreSQL 初始化和 Alembic 建表，再执行迁移脚本：

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-url sqlite:///./data/storage_organizer.db \
  --postgres-url postgresql+psycopg://postgres:postgres@127.0.0.1:5432/organizer
```

- 默认要求目标 PostgreSQL 是空库；如确认要覆盖已有目标库，可追加 `--truncate-target`
- 迁移完成后保留 SQLite 文件作为回滚备份，不需要立即删除

## Lucky 反向代理

- Lucky 反代目标保持为 `http://<server-ip>:8010`
- 域名必须启用 HTTPS，否则 `Secure` Cookie 不会被浏览器回传
- Lucky 需要保留原始 `Host`
- Lucky 需要透传 `X-Forwarded-Proto=https`
- 应用已信任代理头，登录 Cookie 会按 HTTPS 域名场景工作

## 首次启动密码

- 首次 Docker 启动时，如果 `data/auth.json` 不存在，容器会自动生成管理员密码
- 首次生成后只会在容器日志打印一次：

```text
[auth-init] admin username: wang
[auth-init] initial password (shown only once): <generated-password>
```

- 记录后请自行保管，后续重启不会再次显示
- 如果需要重置初始密码，删除 `data/auth.json` 和 `data/auth_sessions.json` 后重建容器

## Unraid 生产部署

```bash
# 1. 本地推送代码
git push

# 2. SSH 到 Unraid
ssh root@192.168.70.138
cd /mnt/user/docker1/18xv2

# 3. 服务器通过 Git 同步
git pull --ff-only

# 4. 构建并启动（首次会同时启动 PostgreSQL）
docker compose -f docker/docker-compose.yml up -d --build

# 5. 查看容器日志
docker logs -f docker-app-1

# 6. 验证服务
curl http://127.0.0.1:8010/api/healthz
curl -i http://127.0.0.1:8010/api/auth/me
```

看到 `api/healthz` 返回 `client_115: true/false`，且未登录访问 `api/auth/me` 返回 `401`，即表示容器已成功启动且登录保护已生效。

## 持久化数据

| 路径 | 内容 |
|---|---|
| `data/tokens.json` | 115 OAuth token，刷新后自动写回 |
| `data/cookies/` | QR 登录 Cookie 文件 |
| `data/postgres/` | PostgreSQL 数据目录（Docker 默认数据库） |
| `data/storage_organizer.db` | 历史 SQLite 数据库 / 迁移回滚备份 |
| `data/auth.json` | 单管理员账号与密码哈希 |
| `data/auth_sessions.json` | 服务端登录会话 |

volume 挂载为 `../data:/app/data`，PostgreSQL 另持久化到 `../data/postgres`，重建容器不会丢失数据。

## 回滚

```bash
# 保留 data/ 不动，回滚代码后重建镜像
docker compose -f docker/docker-compose.yml up -d --build

# 如需恢复 SQLite 到备份
sqlite3 data/storage_organizer.db ".restore data/backup-YYYYMMDD.sql"
```

如需回退到 SQLite：
1. 将 `.env` 中 `DATABASE_URL` 改回 `sqlite:///./data/storage_organizer.db`
2. `docker compose -f docker/docker-compose.yml up -d --build --force-recreate`

## 授权问题排查

启动后若 `/api/healthz` 返回 `client_115: false`：
1. 先使用域名访问系统并登录
2. 访问 `https://<your-domain>/auth-center` 进入授权中心
3. 从授权中心进入扫码登录或授权码换 token
4. 授权成功后 `http://<host>:8010/api/healthz` 应返回 `client_115: true`（无需重启）
