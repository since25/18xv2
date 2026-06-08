from __future__ import annotations

from app.services.dedupe.normalization import DedupeRuleSet, normalize_filename, preview_normalization


def test_normalize_removes_media_noise_and_copy_marker() -> None:
    rules = DedupeRuleSet()
    result = normalize_filename("www.98T.la@Example_1080P (1).MP4", rules)
    assert result.normalized_name == "example"
    assert "site_prefix" in result.applied_rules
    assert "copy_marker" in result.applied_rules


def test_normalize_preserves_series_part_number() -> None:
    rules = DedupeRuleSet()
    result = normalize_filename("Movie.Title.Part2.mkv", rules)
    assert result.normalized_name == "movie title part2"


def test_preview_uses_temporary_noise_words() -> None:
    rows = preview_normalization(
        ["VIP站点@漂亮标题.mp4"],
        DedupeRuleSet(noise_words=["VIP站点"]),
    )
    assert rows[0]["raw_name"] == "VIP站点@漂亮标题.mp4"
    assert rows[0]["normalized_name"] == "漂亮标题"
