from __future__ import annotations

import pytest

from app.services.dedupe.normalization import (
    DedupeRuleSet,
    InvalidDedupeRegexError,
    normalize_filename,
    preview_normalization,
)


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


def test_normalize_removes_numeric_copy_suffix_without_dropping_series_number() -> None:
    result = normalize_filename("Movie.Title._1.mkv", DedupeRuleSet())

    assert result.normalized_name == "movie title"
    assert "copy_marker" in result.applied_rules


def test_normalize_preserves_copy_as_title_word() -> None:
    result = normalize_filename("Copy.1986.1080p.mkv", DedupeRuleSet())

    assert result.normalized_name == "copy 1986"
    assert "copy_marker" not in result.applied_rules


def test_custom_regex_records_only_when_changed() -> None:
    result = normalize_filename("sample-REMOVE.mp4", DedupeRuleSet(regex_patterns=["remove"]))

    assert result.normalized_name == "sample"
    assert "custom_regex" in result.applied_rules


def test_clean_filename_has_no_applied_rules() -> None:
    result = normalize_filename("Clean Title.mp4", DedupeRuleSet())

    assert result.normalized_name == "clean title"
    assert result.applied_rules == []


def test_invalid_custom_regex_raises_domain_error() -> None:
    with pytest.raises(InvalidDedupeRegexError) as exc_info:
        normalize_filename("sample.mp4", DedupeRuleSet(regex_patterns=["("]))

    assert exc_info.value.pattern_index == 0
