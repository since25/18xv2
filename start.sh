#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> 执行数据库迁移..."
"$ROOT/.venv/bin/alembic" -c "$ROOT/alembic.ini" upgrade head

echo "==> 启动后端 (port 8000)..."
"$ROOT/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "==> 启动前端 (port 5173)..."
cd "$ROOT/frontend" && npm run dev -- --port 5173 &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "==> 正在停止服务..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "==> 已退出。"
}
trap cleanup INT TERM

echo ""
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "  Ctrl+C 停止所有服务"
echo ""

wait
