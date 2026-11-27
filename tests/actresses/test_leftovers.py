from __future__ import annotations

import pytest

from app.services.actresses.leftovers import LeftoverPlan, is_sidecar, plan_dir, sidecar_names


def test_plan_whole_dir_when_only_sidecars():
    entries = [
        ("XYZ-001 x.nfo", False),
        ("XYZ-001 x-poster.jpg", False),
        ("XYZ-001 x-fanart.png", False),
        ("XYZ-001 x-thumb.webp", False),
    ]

    assert plan_dir(["XYZ-001 x.avi"], entries) == LeftoverPlan(whole_dir=True, names=[])


def test_plan_whole_dir_when_empty():
    assert plan_dir(["XYZ-001 x.avi"], []) == LeftoverPlan(whole_dir=True, names=[])


def test_plan_dir_with_other_video_deletes_same_name_only():
    entries = [
        ("ABC-001.nfo", False),
        ("ABC-001-poster.jpg", False),
        ("ABC-002.mp4", False),
        ("ABC-002.nfo", False),
    ]

    assert plan_dir(["ABC-001.mp4"], entries) == LeftoverPlan(
        whole_dir=False, names=["ABC-001-poster.jpg", "ABC-001.nfo"]
    )


@pytest.mark.parametrize(
    "extra",
    [("sub", True), ("readme.txt", False), ("ABC-002.strm", False)],
    ids=["subdir", "unknown", "other-strm"],
)
def test_plan_dir_with_subdir_or_unknown_file_falls_back(extra):
    entries = [("ABC-001.nfo", False), extra]

    assert plan_dir(["ABC-001.mp4"], entries) == LeftoverPlan(whole_dir=False, names=["ABC-001.nfo"])


def test_sidecar_names_exact_suffixes():
    entries = [
        ("ABC-001-poster.png", False),
        ("ABC-001.zh.srt", False),
        ("ABC-0011.nfo", False),
        ("abc-001.nfo", False),
        ("ABC-001.srt", False),
    ]

    assert sidecar_names(["ABC-001.mp4"], entries) == ["ABC-001-poster.png", "ABC-001.srt"]


def test_is_sidecar_matches_lowercase_extensions():
    assert is_sidecar("a.NFO") is True
    assert is_sidecar("a-fanart.JPG") is True
    assert is_sidecar("a.ass") is True
    assert is_sidecar("a.strm") is False
    assert is_sidecar("a") is False
