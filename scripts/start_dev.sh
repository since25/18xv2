#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[start_dev] 未找到 .venv/bin/python，请先创建虚拟环境并安装依赖。"
  exit 1
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
RELOAD_FLAG="${UVICORN_RELOAD:-1}"

echo "[start_dev] 执行 alembic upgrade head..."
alembic upgrade head

echo "[start_dev] 启动服务 http://${HOST}:${PORT}"
if [[ "$RELOAD_FLAG" == "0" || "$RELOAD_FLAG" == "false" ]]; then
  exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
fi

exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload "$@"
