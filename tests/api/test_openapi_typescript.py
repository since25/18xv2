"""
scripts/export_openapi.py 中类型生成器 render_typescript 的单元测试：
每条映射规则一个小输入，外加“不认识的写法报错”和“重复生成结果相同”。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from export_openapi import UnsupportedSchemaError, render_typescript  # noqa: E402


def _spec(schemas: dict) -> dict:
    return {"components": {"schemas": schemas}}


def _model(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required}


def _field(schema: dict) -> str:
    """生成只有一个字段 f 的模型，返回该字段那一行（去掉缩进）。"""
    out = render_typescript(_spec({"M": _model({"f": schema})}))
    line = next(x for x in out.splitlines() if x.strip().startswith("f"))
    return line.strip()


def test_header_and_wrapper():
    out = render_typescript(_spec({"B": _model({"x": {"type": "string"}}), "A": _model({"y": {"type": "string"}})}))
    assert out.startswith("// 本文件由 scripts/export_openapi.py")
    assert "scripts/gen-api-types.sh" in out
    assert "export interface components {\n  schemas: {\n" in out
    # 模型名按字典序
    assert out.index("'A': {") < out.index("'B': {")
    assert out.endswith("  }\n}\n")


@pytest.mark.parametrize(
    "schema, expected",
    [
        ({"type": "string", "format": "date-time", "maxLength": 3, "title": "T"}, "f: string"),
        ({"type": "integer", "minimum": 0}, "f: number"),
        ({"type": "number"}, "f: number"),
        ({"type": "boolean"}, "f: boolean"),
        ({"type": "null"}, "f: null"),
        ({}, "f: unknown"),
        ({"title": "仅说明"}, "f: unknown"),
    ],
)
def test_primitives_and_empty(schema, expected):
    assert _field(schema) == expected


def test_optional_field_has_question_mark_and_field_order_kept():
    out = render_typescript(
        _spec({"M": _model({"b": {"type": "string"}, "a": {"type": "integer", "default": 1}}, required=["b"])})
    )
    assert "      b: string\n      a?: number\n" in out


def test_nullable_becomes_union_with_null():
    assert _field({"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}) == "f: string | null"


def test_one_of_is_union():
    assert _field({"oneOf": [{"type": "integer"}, {"type": "string"}]}) == "f: number | string"


def test_enum_and_const_are_literals():
    assert _field({"type": "string", "enum": ["a", "b"]}) == 'f: "a" | "b"'
    assert _field({"enum": [1, None]}) == "f: 1 | null"
    assert _field({"const": "x", "type": "string"}) == 'f: "x"'


def test_array_and_union_items_in_parentheses():
    assert _field({"type": "array", "items": {"type": "string"}}) == "f: string[]"
    assert (
        _field({"type": "array", "items": {"anyOf": [{"type": "integer"}, {"type": "null"}]}})
        == "f: (number | null)[]"
    )


def test_prefix_items_become_tuple():
    assert _field({"type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}]}) == "f: [string, number]"


def test_ref():
    assert _field({"$ref": "#/components/schemas/Other"}) == "f: components['schemas']['Other']"


def test_additional_properties():
    assert _field({"type": "object", "additionalProperties": {"type": "integer"}}) == "f: Record<string, number>"
    assert _field({"type": "object", "additionalProperties": True}) == "f: Record<string, unknown>"
    assert _field({"type": "object", "additionalProperties": {}}) == "f: Record<string, unknown>"
    # 补充规则：没有字段也没有 additionalProperties 的对象，按 JSON Schema 语义允许任意键
    assert _field({"type": "object"}) == "f: Record<string, unknown>"


def test_inline_object_is_nested_literal():
    out = render_typescript(_spec({"M": _model({"f": _model({"g": {"type": "string"}}, required=[])})}))
    assert "      f: {\n        g?: string\n      }\n" in out


def test_non_identifier_property_is_quoted():
    assert _field_named("a-b") == '"a-b": string'


def _field_named(name: str) -> str:
    out = render_typescript(_spec({"M": _model({name: {"type": "string"}})}))
    return out.splitlines()[-4].strip()


@pytest.mark.parametrize(
    "schema",
    [
        {"allOf": [{"type": "string"}]},
        {"not": {"type": "string"}},
        {"oneOf": [{"type": "string"}], "discriminator": {"propertyName": "kind"}},
        {"type": ["string", "null"]},
        {"type": "array"},
        {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": True},
        {"$ref": "#/definitions/Other"},
        {"type": "string", "patternProperties": {}},
    ],
)
def test_unknown_shapes_raise_with_model_and_field(schema):
    with pytest.raises(UnsupportedSchemaError) as exc:
        render_typescript(_spec({"Model": _model({"field": schema})}))
    assert "Model.field" in str(exc.value)


def test_same_input_renders_identically():
    spec = _spec(
        {
            "M": _model({"a": {"anyOf": [{"$ref": "#/components/schemas/N"}, {"type": "null"}]}}),
            "N": _model({"b": {"type": "array", "items": {"type": "integer"}}}),
        }
    )
    assert render_typescript(spec) == render_typescript(spec)


# ── 按用途决定非必填字段是否按必填输出（只在返回里出现的模型 → 全部必填）────────

_REF = "#/components/schemas/"


def _ref(name: str) -> dict:
    return {"$ref": _REF + name}


def _json(schema: dict) -> dict:
    return {"content": {"application/json": {"schema": schema}}}


def _usage_spec(schemas: dict, *, response=None, request=None, param=None) -> dict:
    """构造带 paths 的 spec：response/request/param 分别为返回、请求体、查询参数里的 schema。"""
    op: dict = {"responses": {"200": _json(response) if response else {"description": "ok"}}}
    if request:
        op["requestBody"] = _json(request)
    if param:
        op["parameters"] = [{"name": "p", "in": "query", "schema": param}]
    return {"paths": {"/x": {"post": op}}, "components": {"schemas": schemas}}


def _defaulted(extra: dict | None = None) -> dict:
    props = {"a": {"type": "string", "default": "x"}, **(extra or {})}
    return {"type": "object", "properties": props, "required": []}


def _model_block(out: str, name: str) -> str:
    start = out.index(f"    '{name}': {{")
    return out[start : out.index("\n    }", start)]


def test_response_only_model_default_fields_are_required():
    out = render_typescript(_usage_spec({"R": _defaulted()}, response=_ref("R")))
    assert "      a: string" in _model_block(out, "R")


def test_request_only_model_default_fields_stay_optional():
    out = render_typescript(_usage_spec({"Q": _defaulted()}, request=_ref("Q")))
    assert "      a?: string" in _model_block(out, "Q")


def test_model_used_by_both_request_and_response_stays_optional():
    out = render_typescript(_usage_spec({"M": _defaulted()}, response=_ref("M"), request=_ref("M")))
    assert "      a?: string" in _model_block(out, "M")


def test_parameters_count_as_request():
    out = render_typescript(_usage_spec({"M": _defaulted()}, response=_ref("M"), param=_ref("M")))
    assert "      a?: string" in _model_block(out, "M")


def test_unused_model_stays_optional():
    out = render_typescript(_usage_spec({"U": _defaulted()}))
    assert "      a?: string" in _model_block(out, "U")


def test_response_only_fields_without_default_are_required_too():
    # default_factory 和 X | None = None 在导出的定义里没有 default，返回时同样一直输出
    model = _defaulted(
        {
            "b": {"type": "array", "items": {"type": "string"}},
            "c": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        }
    )
    out = render_typescript(_usage_spec({"R": model}, response=_ref("R")))
    block = _model_block(out, "R")
    assert "      a: string" in block
    assert "      b: string[]" in block
    assert "      c: string | null" in block


def test_request_model_fields_without_default_stay_optional():
    model = _defaulted({"c": {"anyOf": [{"type": "string"}, {"type": "null"}]}})
    out = render_typescript(_usage_spec({"Q": model}, request=_ref("Q")))
    assert "      c?: string | null" in _model_block(out, "Q")


@pytest.mark.parametrize(
    "link",
    [
        _ref("B"),
        {"type": "array", "items": _ref("B")},
        {"anyOf": [_ref("B"), {"type": "null"}]},
        {"type": "object", "additionalProperties": _ref("B")},
    ],
)
def test_models_reachable_from_response_become_required(link):
    schemas = {"A": {"type": "object", "properties": {"b": link}, "required": ["b"]}, "B": _defaulted()}
    out = render_typescript(_usage_spec(schemas, response=_ref("A")))
    assert "      a: string" in _model_block(out, "B")


def test_reachable_model_also_used_in_request_stays_optional():
    schemas = {"A": {"type": "object", "properties": {"b": _ref("B")}, "required": ["b"]}, "B": _defaulted()}
    out = render_typescript(_usage_spec(schemas, response=_ref("A"), request={"type": "array", "items": _ref("B")}))
    assert "      a?: string" in _model_block(out, "B")
