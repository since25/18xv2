"""
把后端接口定义（OpenAPI）导出到 frontend/openapi.json，并由其中的数据模型生成
frontend/src/api/schema.gen.ts（前端类型）。
只导入应用对象并调用 app.openapi()，不启动服务、不执行 lifespan、不连数据库。
键按字母排序、固定缩进，保证重复导出结果逐字节相同。
用法：python scripts/export_openapi.py
一般不直接调用，统一用 scripts/gen-api-types.sh。

类型生成只处理 components.schemas，遇到不认识的、会影响类型形状的写法直接报错，
不输出宽松类型糊过去。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = ROOT / "frontend" / "openapi.json"
SCHEMA_TS_PATH = ROOT / "frontend" / "src" / "api" / "schema.gen.ts"

_REF_PREFIX = "#/components/schemas/"
# 只是说明或校验、不影响类型形状的关键字，生成时忽略
_IGNORED_KEYS = {
    "title",
    "description",
    "default",
    "examples",
    "example",
    "format",
    "contentMediaType",
    "contentEncoding",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "deprecated",
    "readOnly",
    "writeOnly",
}
# 本生成器认识的、决定类型形状的关键字
_SHAPE_KEYS = {
    "type",
    "enum",
    "const",
    "items",
    "prefixItems",
    "$ref",
    "anyOf",
    "oneOf",
    "properties",
    "required",
    "additionalProperties",
}
_PRIMITIVES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}
_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_SCHEMA_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

HEADER = (
    "// 本文件由 scripts/export_openapi.py 根据后端接口定义自动生成，请勿手工修改。\n"
    "// 后端接口或数据模型变化后，运行 scripts/gen-api-types.sh 重新生成。\n"
)


class UnsupportedSchemaError(ValueError):
    """遇到生成器不认识的定义写法。"""


def _literal(value) -> str:
    if value is None or isinstance(value, (bool, int, float, str)):
        return json.dumps(value, ensure_ascii=False)
    raise UnsupportedSchemaError(f"不支持的字面量：{value!r}")


def _prop_key(name: str) -> str:
    return name if _IDENT.match(name) else json.dumps(name, ensure_ascii=False)


def _schema_name(name: str, where: str) -> str:
    if not _SCHEMA_NAME.match(name):
        raise UnsupportedSchemaError(f"{where}：模型名含不支持的字符 {name!r}")
    return name


def _union(parts: list[str]) -> tuple[str, bool]:
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " | ".join(seen), len(seen) > 1


def _render(schema, where: str, indent: int, response_only: bool) -> tuple[str, bool]:
    """返回 (TS 类型文本, 是否为顶层联合)。where 用于报错时指明模型名和字段；
    response_only 为真时全部字段按必填输出（见 _response_only_models）。"""
    if not isinstance(schema, dict):
        raise UnsupportedSchemaError(f"{where}：定义不是对象：{schema!r}")
    unknown = set(schema) - _IGNORED_KEYS - _SHAPE_KEYS
    if unknown:
        raise UnsupportedSchemaError(f"{where}：不支持的关键字 {sorted(unknown)}")
    shape = set(schema) & _SHAPE_KEYS

    if "$ref" in schema:
        if shape != {"$ref"}:
            raise UnsupportedSchemaError(f"{where}：$ref 不能与 {sorted(shape - {'$ref'})} 同用")
        ref = schema["$ref"]
        if not ref.startswith(_REF_PREFIX):
            raise UnsupportedSchemaError(f"{where}：不支持的引用 {ref}")
        return f"components['schemas']['{_schema_name(ref[len(_REF_PREFIX):], where)}']", False

    for key in ("anyOf", "oneOf"):
        if key in schema:
            if shape != {key}:
                raise UnsupportedSchemaError(f"{where}：{key} 不能与 {sorted(shape - {key})} 同用")
            parts = [_render(s, f"{where}[{key}]", indent, response_only)[0] for s in schema[key]]
            return _union(parts)

    if "const" in schema:
        if shape - {"const", "type"}:
            raise UnsupportedSchemaError(f"{where}：const 不能与 {sorted(shape - {'const', 'type'})} 同用")
        return _literal(schema["const"]), False

    if "enum" in schema:
        if shape - {"enum", "type"}:
            raise UnsupportedSchemaError(f"{where}：enum 不能与 {sorted(shape - {'enum', 'type'})} 同用")
        return _union([_literal(v) for v in schema["enum"]])

    typ = schema.get("type")
    if typ is None:
        if shape:
            raise UnsupportedSchemaError(f"{where}：缺少 type 却有 {sorted(shape)}")
        return "unknown", False
    if not isinstance(typ, str):
        raise UnsupportedSchemaError(f"{where}：不支持的 type 写法 {typ!r}")

    if typ in _PRIMITIVES:
        if shape != {"type"}:
            raise UnsupportedSchemaError(f"{where}：{typ} 不能与 {sorted(shape - {'type'})} 同用")
        return _PRIMITIVES[typ], False

    if typ == "array":
        if shape - {"type", "items", "prefixItems"}:
            raise UnsupportedSchemaError(f"{where}：array 不能与 {sorted(shape - {'type', 'items', 'prefixItems'})} 同用")
        if "prefixItems" in schema:
            if "items" in schema:
                raise UnsupportedSchemaError(f"{where}：prefixItems 与 items 同用（变长元组）暂不支持")
            parts = [_render(s, f"{where}[{i}]", indent, response_only)[0] for i, s in enumerate(schema["prefixItems"])]
            return "[" + ", ".join(parts) + "]", False
        if "items" not in schema:
            raise UnsupportedSchemaError(f"{where}：array 缺少 items")
        inner, is_union = _render(schema["items"], f"{where}[]", indent, response_only)
        return (f"({inner})[]" if is_union else f"{inner}[]"), False

    if typ == "object":
        if shape - {"type", "properties", "required", "additionalProperties"}:
            raise UnsupportedSchemaError(f"{where}：object 不能与 {sorted(shape - {'type', 'properties', 'required', 'additionalProperties'})} 同用")
        extra = schema.get("additionalProperties")
        if "properties" in schema:
            if extra not in (None, False):
                raise UnsupportedSchemaError(f"{where}：properties 与 additionalProperties 同用暂不支持")
            return _render_object(schema, where, indent, response_only), False
        if "required" in schema:
            raise UnsupportedSchemaError(f"{where}：有 required 却没有 properties")
        if extra is None or extra is True or extra == {}:
            # 没有声明字段的对象按 JSON Schema 语义允许任意键
            return "Record<string, unknown>", False
        if extra is False:
            raise UnsupportedSchemaError(f"{where}：不允许任何字段的空对象暂不支持")
        inner, _ = _render(extra, f"{where}{{}}", indent, response_only)
        return f"Record<string, {inner}>", False

    raise UnsupportedSchemaError(f"{where}：不支持的 type {typ!r}")


def _render_object(schema: dict, where: str, indent: int, response_only: bool) -> str:
    props = schema["properties"]
    required = set(schema.get("required", []))
    missing = required - set(props)
    if missing:
        raise UnsupportedSchemaError(f"{where}：required 中有未定义字段 {sorted(missing)}")
    if not props:
        raise UnsupportedSchemaError(f"{where}：没有字段的对象暂不支持")
    pad = "  " * (indent + 1)
    lines = ["{"]
    for name, sub in props.items():
        text, _ = _render(sub, f"{where}.{name}", indent + 1, response_only)
        # 只在返回里出现的模型：返回时全部字段都会输出，一律按必填处理
        mark = "" if name in required or response_only else "?"
        lines.append(f"{pad}{_prop_key(name)}{mark}: {text}")
    lines.append("  " * indent + "}")
    return "\n".join(lines)


def _collect_refs(node, found: set[str]) -> None:
    """收集一段定义里直接出现的所有模型引用（不展开引用本身）。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref[len(_REF_PREFIX):])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, found)


def _closure(roots: set[str], schemas: dict) -> set[str]:
    """沿模型之间的引用求传递闭包。"""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        found: set[str] = set()
        _collect_refs(schemas[name], found)
        todo.extend(found - seen)
    return seen


def _response_only_models(spec: dict) -> set[str]:
    """只被接口返回内容（含间接引用）用到、从未出现在请求参数或请求体里的模型。
    后端导出的定义把有默认值的字段（含 X | None = None、default_factory）标成可选，
    但返回时模型的全部字段都会输出，所以这些模型的字段一律视为必填；请求里用到的模型维持原样。"""
    schemas = spec.get("components", {}).get("schemas", {})
    response_roots: set[str] = set()
    request_roots: set[str] = set()
    for path_item in spec.get("paths", {}).values():
        _collect_refs(path_item.get("parameters", []), request_roots)
        for key, op in path_item.items():
            if key == "parameters" or not isinstance(op, dict):
                continue
            _collect_refs(op.get("parameters", []), request_roots)
            _collect_refs(op.get("requestBody", {}), request_roots)
            _collect_refs(op.get("responses", {}), response_roots)
    return _closure(response_roots, schemas) - _closure(request_roots, schemas)


def render_typescript(spec: dict) -> str:
    """把 spec['components']['schemas'] 写成 TS：导出 components 接口，模型名按字典序。"""
    schemas = spec.get("components", {}).get("schemas", {})
    response_only = _response_only_models(spec)
    lines = [HEADER, "export interface components {", "  schemas: {"]
    for name in sorted(schemas):
        text, _ = _render(schemas[name], name, 2, name in response_only)
        lines.append(f"    '{_schema_name(name, name)}': {text}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_openapi_json(spec: dict) -> str:
    """返回排好序的接口定义 JSON 文本（结尾带换行）。"""
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    from app.main import app

    spec = json.loads(json.dumps(app.openapi()))
    # 先生成类型，确认没有不认识的写法后再一起落盘
    typescript = render_typescript(spec)
    OPENAPI_PATH.write_text(render_openapi_json(spec), encoding="utf-8")
    SCHEMA_TS_PATH.write_text(typescript, encoding="utf-8")
    print(f"[export_openapi] 已写入 {OPENAPI_PATH.relative_to(ROOT)}、{SCHEMA_TS_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
