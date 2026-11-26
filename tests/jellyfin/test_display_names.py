from __future__ import annotations

from app.services.jellyfin.display_names import compute_display_names


ROOT = "/r/已整理"


def _names(paths, roots=(ROOT,)):
    """只取显示名，便于断言。"""
    return {path: value.name for path, value in compute_display_names(paths, list(roots)).items()}


def test_three_level_paths_numbered_within_pack():
    names = _names([f"{ROOT}/甲/包/b.mp4", f"{ROOT}/甲/包/a.mp4"])

    assert names == {f"{ROOT}/甲/包/a.mp4": "01 · 甲/包", f"{ROOT}/甲/包/b.mp4": "02 · 甲/包"}


def test_natural_sort_parenthesized_numbers():
    paths = [f"{ROOT}/甲/包/x (10).mp4", f"{ROOT}/甲/包/x (2).mp4", f"{ROOT}/甲/包/10.mp4", f"{ROOT}/甲/包/2.mp4"]

    names = _names(paths)

    assert names[f"{ROOT}/甲/包/2.mp4"] == "01 · 甲/包"
    assert names[f"{ROOT}/甲/包/10.mp4"] == "02 · 甲/包"
    assert names[f"{ROOT}/甲/包/x (2).mp4"] == "03 · 甲/包"
    assert names[f"{ROOT}/甲/包/x (10).mp4"] == "04 · 甲/包"


def test_deeper_subfolders_join_pack_group():
    paths = [f"{ROOT}/甲/包/视图/y.mp4", f"{ROOT}/甲/包/z.mp4", f"{ROOT}/甲/包/V/x.mp4"]

    names = _names(paths)

    assert names[f"{ROOT}/甲/包/V/x.mp4"] == "01 · 甲/包"
    assert names[f"{ROOT}/甲/包/z.mp4"] == "02 · 甲/包"
    assert names[f"{ROOT}/甲/包/视图/y.mp4"] == "03 · 甲/包"


def test_file_directly_under_keyword_uses_keyword_only():
    assert _names([f"{ROOT}/甲__乙/a.mp4"]) == {f"{ROOT}/甲__乙/a.mp4": "01 · 甲__乙"}


def test_file_directly_under_root_or_outside_roots_skipped():
    assert compute_display_names([f"{ROOT}/a.mp4", "/别处/甲/包/a.mp4"], [ROOT]) == {}


def test_root_prefix_requires_path_boundary():
    assert compute_display_names([f"{ROOT}2/甲/包/a.mp4"], [ROOT]) == {}
    assert _names([f"{ROOT}/甲/包/a.mp4"], roots=(ROOT + "/",)) == {f"{ROOT}/甲/包/a.mp4": "01 · 甲/包"}


def test_padding_grows_with_group_size():
    paths = [f"{ROOT}/甲/包/{i}.mp4" for i in range(1, 101)]

    names = _names(paths)

    assert names[f"{ROOT}/甲/包/1.mp4"] == "001 · 甲/包"
    assert names[f"{ROOT}/甲/包/100.mp4"] == "100 · 甲/包"


def test_sort_name_keeps_packs_together_in_play_order():
    # 显示名序号在前，若直接按显示名排序会把各包的 01 排在一起；排序名必须仍按「包 → 序号」
    paths = [f"{ROOT}/甲/11935-包/a.mp4", f"{ROOT}/甲/6605-包/b.mp4", f"{ROOT}/甲/6605-包/a.mp4"]

    result = compute_display_names(paths, [ROOT])
    ordered = sorted(paths, key=lambda path: result[path].sort_name)

    assert ordered == [f"{ROOT}/甲/6605-包/a.mp4", f"{ROOT}/甲/6605-包/b.mp4", f"{ROOT}/甲/11935-包/a.mp4"]
    assert result[f"{ROOT}/甲/6605-包/b.mp4"].name == "02 · 甲/6605-包"
    assert result[f"{ROOT}/甲/6605-包/b.mp4"].sort_name == "甲/0000006605-包 · 0000000002"
