"""
防漂移检查：入库的 frontend/openapi.json 和 frontend/src/api/schema.gen.ts
必须与当前后端接口定义一致。后端改了接口或数据模型却没重新生成前端类型时，这里会失败。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "frontend" / "openapi.json"
SCHEMA_TS = ROOT / "frontend" / "src" / "api" / "schema.gen.ts"

sys.path.insert(0, str(ROOT / "scripts"))

from export_openapi import render_typescript  # noqa: E402


def _current_spec() -> dict:
    # 经过一次 JSON 往返，消除元组/列表等 Python 侧表示差异
    return json.loads(json.dumps(app.openapi()))


def test_openapi_snapshot_is_up_to_date():
    assert SNAPSHOT.exists(), "缺少 frontend/openapi.json，请运行 scripts/gen-api-types.sh 生成"
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert saved == _current_spec(), (
        "后端接口定义与 frontend/openapi.json 不一致，"
        "请运行 scripts/gen-api-types.sh 重新生成前端类型并一起提交"
    )


def test_generated_types_are_up_to_date():
    assert SCHEMA_TS.exists(), "缺少 frontend/src/api/schema.gen.ts，请运行 scripts/gen-api-types.sh 生成"
    assert SCHEMA_TS.read_text(encoding="utf-8") == render_typescript(_current_spec()), (
        "frontend/src/api/schema.gen.ts 与后端接口定义不一致（可能被手工改过或没重新生成），"
        "请运行 scripts/gen-api-types.sh 重新生成并一起提交"
    )
