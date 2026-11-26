from __future__ import annotations

from app.services.actresses.names import normalize_actress_name


def test_normalize_actress_name_ignores_spaces_and_width():
    assert normalize_actress_name("甲 乙") == normalize_actress_name("甲乙")
    assert normalize_actress_name("ＡＢＣ　甲") == "ABC甲"
    assert normalize_actress_name("  ") == ""
