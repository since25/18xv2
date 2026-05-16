#!/bin/sh
set -e

# 启动前执行数据库迁移，确保 schema 是最新的
echo "[entrypoint] 执行 alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] 启动 supervisord（nginx + uvicorn）..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
