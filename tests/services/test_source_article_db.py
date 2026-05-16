from __future__ import annotations

import re

from app.services.source_article_db import SourceArticleDatabaseService


def test_word_boundary_match_enabled_for_ascii_keywords() -> None:
    assert SourceArticleDatabaseService._should_use_word_boundary_match("Aram") is True
    assert SourceArticleDatabaseService._should_use_word_boundary_match("Julia Ann") is True
    assert SourceArticleDatabaseService._should_use_word_boundary_match("IPX 123") is True


def test_word_boundary_match_disabled_for_non_ascii_keywords() -> None:
    assert SourceArticleDatabaseService._should_use_word_boundary_match("三上悠亚") is False
    assert SourceArticleDatabaseService._should_use_word_boundary_match("Aram 混合") is False


def test_word_boundary_regex_avoids_embedded_english_substrings() -> None:
    pattern = SourceArticleDatabaseService._build_word_boundary_regex("Aram")

    assert re.search(pattern, "⚫️顶级名媛财阀母狗【Aram】最新福利", re.IGNORECASE) is not None
    assert re.search(pattern, "明星颜值反差女神『ARAM』首次露下体", re.IGNORECASE) is not None
    assert re.search(pattern, "DANEJONES.-CARAMELLA.DEL.Xnan", re.IGNORECASE) is None
    assert re.search(pattern, "LOOKATHERNOW-.SKY.ALEXIS.I.NEED.PARAMEDIC.PUSSY.720Pnan", re.IGNORECASE) is None
    assert re.search(pattern, "SEXMEX-KAROL.JARAMILLO.FUCKED.BY.UNCLE", re.IGNORECASE) is None


def test_word_boundary_regex_allows_common_separator_variants() -> None:
    pattern = SourceArticleDatabaseService._build_word_boundary_regex("Julia Ann")

    assert re.search(pattern, "JULIA ANN Debut", re.IGNORECASE) is not None
    assert re.search(pattern, "JULIA.ANN.Debut", re.IGNORECASE) is not None
    assert re.search(pattern, "JULIA_ANN_Debut", re.IGNORECASE) is not None
    assert re.search(pattern, "JULIA-ANN-Debut", re.IGNORECASE) is not None


def test_short_ascii_keyword_scores_bracketed_cjk_titles_higher() -> None:
    wrapped = SourceArticleDatabaseService._score_title_match("Aram", "⚫️顶级名媛财阀母狗【Aram】最新福利")
    plain = SourceArticleDatabaseService._score_title_match("Aram", "Aram debut scene")

    assert wrapped > plain


def test_short_ascii_keyword_scores_exact_boundary_titles_above_raw_similarity() -> None:
    score = SourceArticleDatabaseService._score_title_match("Aram", "明星颜值反差女神『ARAM』首次露下体")
    raw = 0.1509

    assert score > raw
