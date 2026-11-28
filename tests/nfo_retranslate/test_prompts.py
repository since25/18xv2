from __future__ import annotations

from pathlib import Path

import pytest

from app.services.nfo_retranslate.prompts import (
    build_user_message,
    known_names,
    load_actor_glossary,
    validate_output,
)

_GLOSSARY = {"麻仓忧": ("麻倉憂", "松山真琴")}


def _write_mapping(path: Path, rows: str) -> str:
    """写一个小 mapping_actor.xml，返回路径字符串。"""
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>\n<info>\n{rows}\n</info>\n', encoding="utf-8")
    return str(path)


def test_load_actor_glossary(tmp_path):
    path = _write_mapping(
        tmp_path / "mapping_actor.xml",
        '  <a zh_cn="麻仓忧" zh_tw="麻倉憂" jp="麻倉憂" keyword=",麻倉憂,松山真琴,麻仓忧,"/>',
    )

    assert load_actor_glossary(path) == {"麻仓忧": ("麻倉憂", "松山真琴")}

    with pytest.raises(ValueError):
        load_actor_glossary(str(tmp_path / "missing.xml"))

    broken = tmp_path / "broken.xml"
    broken.write_text("这不是 XML", encoding="utf-8")
    with pytest.raises(ValueError):
        load_actor_glossary(str(broken))


def test_build_user_message_lines():
    message = build_user_message(
        "title",
        num="ABC-001",
        actors=["麻仓忧", "不在对照表"],
        glossary=_GLOSSARY,
        studio="MOODYZ",
        series="",
        text="婚約したばかりの僕",
    )

    expected_in_order = [
        "类型：标题",
        "番号：ABC-001",
        "演员对照：麻倉憂、松山真琴 → 麻仓忧",
        "片商：MOODYZ",
        "原文：\n婚約したばかりの僕",
    ]
    positions = [message.index(part) for part in expected_in_order]
    assert positions == sorted(positions)
    assert "系列：" not in message
    assert "不在对照表" not in message

    # 本片没有一个演员在对照表里：整行省略
    message = build_user_message(
        "plot",
        num="ABC-001",
        actors=["不在对照表"],
        glossary=_GLOSSARY,
        studio="MOODYZ",
        series="某系列",
        text="第一段\n第二段",
    )
    assert "类型：简介" in message
    assert "演员对照" not in message
    assert "系列：某系列" in message


def test_known_names():
    assert known_names(["麻仓忧", "りかたん"], _GLOSSARY) == ["麻仓忧", "麻倉憂", "松山真琴", "りかたん"]


def _fails(field, source, output, names=()) -> bool:
    """检查不通过：没有译文，且给出了非空原因。"""
    cleaned, reason = validate_output(field, source, output, names=list(names))
    return cleaned is None and bool(reason)


def _passes(field, source, output, names=()) -> bool:
    cleaned, reason = validate_output(field, source, output, names=list(names))
    return cleaned is not None and reason is None


def test_validate_output_rules():
    # 空串或 1 个字
    assert _fails("title", "原文", "")
    assert _fails("title", "原文", " 好 ")
    # 带标签开头
    assert _fails("title", "原文", "标题：麻仓忧的初次体验")
    assert _fails("title", "原文", "Title: 麻仓忧的初次体验")
    # 含 <think>
    assert _fails("title", "原文", "<think>嗯</think>麻仓忧的初次体验")
    # 拒绝话术开头
    assert _fails("title", "原文", "抱歉，我无法翻译这段内容")
    assert _passes("title", "原文", "我无法抗拒的诱惑")
    # 假名占比 16%（25 字里 4 个假名）失败，15%（20 字里 3 个假名）通过
    assert _fails("title", "原文", "ああああ" + "好" * 21)
    assert _passes("title", "原文", "あああ" + "好" * 17)
    # 标题 61 字失败，60 字通过
    assert _fails("title", "原文", "好" * 61)
    assert _passes("title", "原文", "好" * 60)
    # 简介短于原文 20% 或长于 3 倍失败，边界通过
    source = "あ" * 100
    assert _fails("plot", source, "好" * 19)
    assert _fails("plot", source, "好" * 301)
    assert _passes("plot", source, "好" * 20)
    assert _passes("plot", source, "好" * 300)
    # 正常译文通过，首尾引号和空白去掉，简介换行保留
    assert validate_output("title", "原文", "  「麻仓忧的初次体验」\n", names=[]) == ("麻仓忧的初次体验", None)
    assert validate_output("title", "原文", '"麻仓忧的初次体验"', names=[]) == ("麻仓忧的初次体验", None)
    assert validate_output("title", "原文", "“麻仓忧的初次体验”", names=[]) == ("麻仓忧的初次体验", None)
    # 首尾都是台词时中间还有同种引号，不剥
    assert validate_output("title", "原文", "「A」和「B」", names=[]) == ("「A」和「B」", None)
    assert validate_output("title", "原文", '"A" 和 "B"', names=[]) == ('"A" 和 "B"', None)
    assert validate_output("plot", "第一段\n第二段", "第一段译文\n第二段译文", names=[]) == ("第一段译文\n第二段译文", None)


def test_validate_output_ignores_known_names_for_kana():
    assert validate_output("title", "原文", "りかたん的初次体验", names=["りかたん"]) == ("りかたん的初次体验", None)

    cleaned, reason = validate_output("title", "原文", "りかたん的初次体验", names=[])
    assert cleaned is None
    assert reason
