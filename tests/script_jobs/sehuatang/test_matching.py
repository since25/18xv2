from __future__ import annotations

from app.services.script_jobs.sehuatang.matching import find_hit, normalize


TERMS = [("AI增强", normalize("AI增强")), ("示例演员", normalize("示例演员")), ("示例", normalize("示例"))]


def test_normalize_removes_spaces_and_casefolds():
    assert normalize(" Ai　增 强\t") == "ai增强"


def test_fullwidth_and_mixed_case_hit():
    assert find_hit("【新作】ＡＩ 增强 版", TERMS) == "AI增强"
    assert find_hit("ai增強", [("AI增強", normalize("AI增強"))]) == "AI增強"


def test_longest_term_wins():
    assert find_hit("示例演员的新作", TERMS) == "示例演员"


def test_same_length_keeps_list_order():
    terms = [("甲乙", normalize("甲乙")), ("乙丙", normalize("乙丙"))]
    assert find_hit("甲乙丙", terms) == "甲乙"


def test_no_hit_returns_none():
    assert find_hit("普通标题", TERMS) is None


def test_empty_normalized_term_is_ignored():
    assert find_hit("任意标题", [("   ", "")]) is None
