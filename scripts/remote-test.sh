#!/usr/bin/env bash
# 把当前检出（含 worktree）同步到远程测试机，在那里跑测试，只把结果摘要带回本机。
#
# 用法：
#   scripts/remote-test.sh backend [pytest 参数...]   # 默认 tests -q -n 16（并行）
#   scripts/remote-test.sh frontend [vitest 参数...]  # npm run test + build + lint
#   scripts/remote-test.sh all
#
# 环境变量：
#   REMOTE_TEST_HOST  SSH 主机别名，默认 spark
#   REMOTE_TEST_ROOT  远程根目录，默认 ~/ci/18x_v2
#
# 说明：
# - 不同步 .git、.venv、node_modules、.env、数据目录和 cookies 文件；依赖在远程按本机架构单独安装。
# - 每个检出目录在远程有独立子目录，多个 worktree 互不覆盖。
# - 完整日志留在远程 <目录>/.remote-test-logs/，本机只显示摘要和日志路径。
set -euo pipefail

MODE="${1:-all}"
shift || true
HOST="${REMOTE_TEST_HOST:-spark}"
ROOT="${REMOTE_TEST_ROOT:-~/ci/18x_v2}"

LOCAL_DIR="$(git rev-parse --show-toplevel)"
NAME="$(basename "$LOCAL_DIR")"
REMOTE_DIR="$ROOT/$NAME"

case "$MODE" in
  backend|frontend|all) ;;
  *) echo "用法：$0 backend|frontend|all [额外参数]" >&2; exit 2 ;;
esac

ssh "$HOST" "mkdir -p $REMOTE_DIR"

# 只同步源码；--delete 保证远程与本地一致（排除项不受影响）
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude 'frontend/dist' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude 'data/*' \
  --exclude 'tmp/' \
  --exclude 'build/' \
  --exclude '*.egg-info' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '*cookies*' \
  --exclude '.claude/' \
  --exclude '.superpowers/' \
  --exclude '.remote-test-logs/' \
  --exclude '.deps-*' \
  --exclude '.remote-constraints.txt' \
  --exclude '.local-pkgs/' \
  "$LOCAL_DIR/" "$HOST:$REMOTE_DIR/"

# 远程后端环境复刻本机 venv：同一 Python 小版本 + 同一份冻结清单。
# 原因：直接按 pyproject 全新安装会拉到更新的间接依赖（如 asynctools），导致 p115client 导入失败，
# 测试结果与本机不一致。worktree 里的 .venv 可能是软链，pip 仍可正常读取。
PY_VER="3.12"
if [ -x "$LOCAL_DIR/.venv/bin/python" ]; then
  PY_VER="$("$LOCAL_DIR/.venv/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  "$LOCAL_DIR/.venv/bin/python" -m pip freeze --exclude-editable 2>/dev/null \
    | grep -vE '^-e |^#| @ |^p115client==' \
    | ssh "$HOST" "cat > $REMOTE_DIR/.remote-constraints.txt"
  # 本机的 p115client 版本已不在 PyPI 上，且为纯 Python 包，直接从本机 site-packages 复制过去
  SITE="$("$LOCAL_DIR/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  ssh "$HOST" "mkdir -p $REMOTE_DIR/.local-pkgs"
  rsync -az --delete "$SITE"/p115client "$SITE"/p115client-*.dist-info "$HOST:$REMOTE_DIR/.local-pkgs/"
fi

# 额外参数逐个转义后传给远程
EXTRA=""
for arg in "$@"; do EXTRA+=" $(printf '%q' "$arg")"; done

ssh "$HOST" "bash -s -- $MODE $REMOTE_DIR $PY_VER$EXTRA" <<'REMOTE'
set -uo pipefail
MODE="$1"; DIR="$2"; PY_VER="$3"; shift 3
cd "$DIR"
mkdir -p .remote-test-logs
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$DIR/.remote-test-logs/$TS-$MODE.log"
STATUS=0

# 依赖文件变化时才重装
deps_changed() { # $1=依赖文件 $2=标记文件
  local sum; sum="$(sha256sum "$1" | cut -d' ' -f1)"
  [ "$(cat "$2" 2>/dev/null)" != "$sum" ] && { echo "$sum" > "$2.new"; return 0; }
  return 1
}

run_backend() {
  mkdir -p data
  # 找与本机同小版本的 Python：系统自带优先，否则用 micromamba 在共享目录建一次
  local py; py="$(command -v "python$PY_VER" || true)"
  if [ -z "$py" ]; then
    local env_dir="$DIR/../.python-$PY_VER"
    if [ ! -x "$env_dir/bin/python" ]; then
      echo "[远程] 用 micromamba 准备 Python $PY_VER…"
      local mm; mm="$(command -v micromamba || echo "$HOME/.local/bin/micromamba")"
      "$mm" create -y -q -p "$env_dir" -c conda-forge "python=$PY_VER" >>"$LOG" 2>&1 \
        || { echo "[远程] 无法准备 Python $PY_VER，见日志"; return 1; }
    fi
    py="$env_dir/bin/python"
  fi
  # Python 小版本变化时重建 venv
  if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import sys; assert f'{sys.version_info[0]}.{sys.version_info[1]}'=='$PY_VER'" 2>/dev/null; then
    rm -rf .venv .deps-py.sha
    "$py" -m venv .venv >>"$LOG" 2>&1 || { echo "[远程] 创建 venv 失败"; return 1; }
  fi
  touch .remote-constraints.txt
  cat pyproject.toml .remote-constraints.txt > .deps-py.input
  if deps_changed .deps-py.input .deps-py.sha; then
    echo "[远程] 安装后端依赖…"
    if [ -s .remote-constraints.txt ]; then
      # 按本机冻结清单原样安装，再以 --no-deps 装项目本身
      .venv/bin/pip install -q -r .remote-constraints.txt >>"$LOG" 2>&1 \
        && .venv/bin/pip install -q --no-deps -e . >>"$LOG" 2>&1
    else
      .venv/bin/pip install -q -e '.[dev]' >>"$LOG" 2>&1
    fi && mv .deps-py.sha.new .deps-py.sha \
      || { echo "[远程] 后端依赖安装失败，见日志"; return 1; }
  fi
  # 覆盖本机复制来的纯 Python 包（每次都同步，成本很低）
  if [ -d .local-pkgs ] && [ -n "$(ls -A .local-pkgs)" ]; then
    local site; site="$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    rm -rf "$site"/p115client "$site"/p115client-*.dist-info
    cp -R .local-pkgs/. "$site"/
  fi
  # 远程串行跑主要耗在磁盘等待上（约 7 分半），并行后约 1 分钟；pytest-xdist 只装在远程测试环境，不进项目依赖
  .venv/bin/python -c "import xdist" 2>/dev/null || .venv/bin/pip install -q pytest-xdist >>"$LOG" 2>&1
  local args=("$@"); [ ${#args[@]} -eq 0 ] && args=(tests -q -n 16)
  echo "=== backend: pytest ${args[*]}" >>"$LOG"
  .venv/bin/python -m pytest -p no:cacheprovider "${args[@]}" >>"$LOG" 2>&1
  local rc=$?
  echo "后端 pytest 退出码=$rc：$(grep -E '^(=+ )?[0-9]+ (passed|failed|error)' "$LOG" | tail -1)"
  return $rc
}

run_frontend() {
  cd frontend
  [ -d node_modules ] || rm -f ../.deps-npm.sha
  if deps_changed package-lock.json ../.deps-npm.sha; then
    echo "[远程] 安装前端依赖…"
    npm ci --no-audit --no-fund >>"$LOG" 2>&1 && mv ../.deps-npm.sha.new ../.deps-npm.sha \
      || { echo "[远程] 前端依赖安装失败"; cd ..; return 1; }
  fi
  local rc=0 t b l
  # vitest 默认开「核数-1」个 worker，在 20 核机器上 jsdom 互相抢占会让 ReviewIntakePage 等慢测试超时，限制为 6
  echo "=== frontend: test" >>"$LOG"; npm run test -- --maxWorkers=6 "$@" >>"$LOG" 2>&1; t=$?
  echo "=== frontend: build" >>"$LOG"; npm run build >>"$LOG" 2>&1; b=$?
  echo "=== frontend: lint" >>"$LOG"; npm run lint >>"$LOG" 2>&1; l=$?
  echo "前端 test 退出码=$t：$(sed 's/\x1b\[[0-9;]*m//g' "$LOG" | grep -E '^ *Tests +[0-9]' | tail -1 | sed 's/^ *//')"
  echo "前端 build 退出码=$b，lint 退出码=$l$( [ $l -ne 0 ] && echo "：$(grep -E '✖' "$LOG" | tail -1)")"
  cd ..
  [ $t -eq 0 ] && [ $b -eq 0 ] && [ $l -eq 0 ] || rc=1
  return $rc
}

case "$MODE" in
  backend) run_backend "$@" || STATUS=1 ;;
  frontend) run_frontend "$@" || STATUS=1 ;;
  all) run_backend || STATUS=1; run_frontend || STATUS=1 ;;
esac
echo "完整日志：$(hostname):$LOG"
exit $STATUS
REMOTE
