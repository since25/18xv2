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


def test_extract_regex_keywords_from_multiline_paths(db_session):
    service = KeywordExtractorService(db_session)

    stats, preview, total_nodes = service.extract_regex_keywords_from_path(
        "\n".join(
            [
                "[DELETED] 已删除目录：/mnt/cache/docker1/SSD_cache/finish/绿帽母狗人妻【深绿岸腐猫儿】全集18《约见粉丝巨炮第二弹》第1集",
                "[DELETED] 已删除目录：/mnt/cache/docker1/SSD_cache/finish/✨推特性爱大师95后绿帽情侣美腿女王「汐梦瑶」大屌爆肏超爽姿势JK制服黑丝母狗阿黑颜无套内射",
                "[DELETED] 已删除目录：/mnt/cache/docker1/SSD_cache/finish/❣️推荐❣️颜值嫩妹【爱喵学姐】一对一视频被出卖,大尺度掰逼诱惑,道具自慰高潮,大哥撸管非常满意",
            ]
        ),
        r"[【「『［\[]([^】」』］\]]+)[】」』］\]]",
        group_index=1,
    )

    assert total_nodes == 3
    assert [item.keyword for item in stats] == ["汐梦瑶", "深绿岸腐猫儿", "爱喵学姐"]
    assert [item.extracted_keyword for item in preview] == ["深绿岸腐猫儿", "汐梦瑶", "爱喵学姐"]
    assert [item.folder_name for item in preview] == [
        "绿帽母狗人妻【深绿岸腐猫儿】全集18《约见粉丝巨炮第二弹》第1集",
        "✨推特性爱大师95后绿帽情侣美腿女王「汐梦瑶」大屌爆肏超爽姿势JK制服黑丝母狗阿黑颜无套内射",
        "❣️推荐❣️颜值嫩妹【爱喵学姐】一对一视频被出卖,大尺度掰逼诱惑,道具自慰高潮,大哥撸管非常满意",
    ]
