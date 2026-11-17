#!/usr/bin/env bash
# 由后端接口定义重新生成前端类型。
#
# 用法：
#   scripts/gen-api-types.sh
#
# 做了什么：
# - 把当前检出同步到测试机（同 scripts/remote-test.sh 的同步规则和后端环境准备），
#   在那里运行 scripts/export_openapi.py；
# - 把生成的 frontend/openapi.json 和 frontend/src/api/schema.gen.ts 取回本机，两个文件都要入库。
#
# 什么时候运行：后端改了接口或数据模型之后。忘了运行时，
# 后端测试 tests/api/test_openapi_snapshot.py 会失败并提示运行本脚本。
set -euo pipefail

exec "$(dirname "$0")/remote-test.sh" gen-api
