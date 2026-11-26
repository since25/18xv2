from __future__ import annotations

from app.services.jellyfin.display_names import compute_display_names


ROOT = "/r/已整理"


def test_three_level_paths_numbered_within_pack():
    names = compute_display_names([f"{ROOT}/甲/包/b.mp4", f"{ROOT}/甲/包/a.mp4"], [ROOT])

    assert names == {f"{ROOT}/甲/包/a.mp4": "甲/包 · 01", f"{ROOT}/甲/包/b.mp4": "甲/包 · 02"}


def test_natural_sort_parenthesized_numbers():
    paths = [f"{ROOT}/甲/包/x (10).mp4", f"{ROOT}/甲/包/x (2).mp4", f"{ROOT}/甲/包/10.mp4", f"{ROOT}/甲/包/2.mp4"]

    names = compute_display_names(paths, [ROOT])

    assert names[f"{ROOT}/甲/包/2.mp4"] == "甲/包 · 01"
    assert names[f"{ROOT}/甲/包/10.mp4"] == "甲/包 · 02"
    assert names[f"{ROOT}/甲/包/x (2).mp4"] == "甲/包 · 03"
    assert names[f"{ROOT}/甲/包/x (10).mp4"] == "甲/包 · 04"


def test_deeper_subfolders_join_pack_group():
    paths = [f"{ROOT}/甲/包/视图/y.mp4", f"{ROOT}/甲/包/z.mp4", f"{ROOT}/甲/包/V/x.mp4"]

    names = compute_display_names(paths, [ROOT])

    assert names[f"{ROOT}/甲/包/V/x.mp4"] == "甲/包 · 01"
    assert names[f"{ROOT}/甲/包/z.mp4"] == "甲/包 · 02"
    assert names[f"{ROOT}/甲/包/视图/y.mp4"] == "甲/包 · 03"


def test_file_directly_under_keyword_uses_keyword_only():
    assert compute_display_names([f"{ROOT}/甲__乙/a.mp4"], [ROOT]) == {f"{ROOT}/甲__乙/a.mp4": "甲__乙 · 01"}


def test_file_directly_under_root_or_outside_roots_skipped():
    assert compute_display_names([f"{ROOT}/a.mp4", "/别处/甲/包/a.mp4"], [ROOT]) == {}


def test_root_prefix_requires_path_boundary():
    assert compute_display_names([f"{ROOT}2/甲/包/a.mp4"], [ROOT]) == {}
    assert compute_display_names([f"{ROOT}/甲/包/a.mp4"], [ROOT + "/"]) == {f"{ROOT}/甲/包/a.mp4": "甲/包 · 01"}


def test_padding_grows_with_group_size():
    paths = [f"{ROOT}/甲/包/{i}.mp4" for i in range(1, 101)]

    names = compute_display_names(paths, [ROOT])

    assert names[f"{ROOT}/甲/包/1.mp4"] == "甲/包 · 001"
    assert names[f"{ROOT}/甲/包/100.mp4"] == "甲/包 · 100"
