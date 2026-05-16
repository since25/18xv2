from __future__ import annotations

from app.services.classifier.keyword_extractor_service import KeywordExtractorService


def test_extract_regex_keywords_from_path_uses_filename_and_deduplicates(db_session):
    service = KeywordExtractorService(db_session)

    stats, preview, total_nodes = service.extract_regex_keywords_from_path(
        "/Volumes/docker1/SSD_cache/finish/⚫️神仙颜值魔鬼身材，马来西亚留学生【姝姬娘娘】最新520福利/489155.com@⚫️神仙颜值魔鬼身材，马来西亚留学生【姝姬娘娘】最新520福利.mp4",
        r"[【「『［\[]([^】」』］\]]+)[】」』］\]]",
        group_index=1,
    )

    assert total_nodes == 1
    assert [item.keyword for item in stats] == ["姝姬娘娘"]
    assert stats[0].source == "manual_path_regex"
    assert stats[0].examples == [
        "/Volumes/docker1/SSD_cache/finish/⚫️神仙颜值魔鬼身材，马来西亚留学生【姝姬娘娘】最新520福利/489155.com@⚫️神仙颜值魔鬼身材，马来西亚留学生【姝姬娘娘】最新520福利.mp4"
    ]
    assert len(preview) == 1
    assert preview[0].folder_name == "489155.com@⚫️神仙颜值魔鬼身材，马来西亚留学生【姝姬娘娘】最新520福利.mp4"
    assert preview[0].extracted_keyword == "姝姬娘娘"


def test_extract_regex_keywords_from_path_rejects_empty_path(db_session):
    service = KeywordExtractorService(db_session)

    try:
        service.extract_regex_keywords_from_path("   ", r".+")
    except ValueError as exc:
        assert str(exc) == "raw_path is required"
    else:
        raise AssertionError("expected ValueError")
