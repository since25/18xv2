"""候选词提取模块单测。

夹具一律使用脱敏假路径：不含真实素材名、真实人名或露骨内容，
只保留与生产数据相同的结构特征（流水号前缀、hashtag、括号、噪声片段）。
"""
from __future__ import annotations

from app.services.review_intake_candidates import extract_raw_candidates


def _texts(raw_path: str) -> list[str]:
    return [item.text for item in extract_raw_candidates(raw_path)]


def _sources(raw_path: str) -> dict[str, str]:
    return {item.text: item.source for item in extract_raw_candidates(raw_path)}


def test_从父目录切出候选词():
    """答案在直接父目录、不在文件名里——这是生产上占 43/67 的主要场景。"""
    path = "/vol/archive/tg/163379-平台甲 小葵/163379 - video_2026-07-15_20-29-11 (2)_marked~1.mp4"
    texts = _texts(path)

    assert "小葵" in texts
    assert "平台甲" in texts


def test_剥掉流水号前缀且不把纯数字当候选():
    path = "/vol/archive/tg/163379-平台甲 小葵/163379 - video_2026-07-15_20-29-11 (2)_marked~1.mp4"
    texts = _texts(path)

    assert "163379" not in texts
    assert not any(text.strip("()~ ").isdigit() for text in texts)


def test_过滤掉技术噪声片段():
    """marked~1 / (new)~1 / (2) 这类必须在归一化之后才判得掉。"""
    path = "/vol/archive/tg/25478-频道甲 小葵/25481 - 5_6147779538538464336_(new)~1.mp4"
    texts = _texts(path)

    normalized = [text.casefold() for text in texts]
    assert not any("marked" in text for text in normalized)
    assert not any(text.strip("()~_ ").casefold() == "new" for text in texts)
    assert "5_6147779538538464336_" not in texts


def test_hashtag_优先于普通切片且去掉尾部符号():
    path = "/vol/archive/tg/25478-#频道甲_ #小葵 #是小葵呀 会员更新/25481 - 1 (15)~1.mp4"
    result = extract_raw_candidates(path)
    sources = {item.text: item.source for item in result}

    assert sources.get("频道甲") == "hashtag"
    assert sources.get("小葵") == "hashtag"
    # hashtag 来源必须排在普通切片之前
    first_segment_index = next(
        (index for index, item in enumerate(result) if item.source == "segment"),
        len(result),
    )
    last_hashtag_index = max(
        (index for index, item in enumerate(result) if item.source == "hashtag"),
        default=-1,
    )
    assert last_hashtag_index < first_segment_index


def test_括号内容仍然被提取且排在普通切片之前():
    path = "/vol/finish/作品【小葵】.mp4"
    result = extract_raw_candidates(path)

    assert result[0].text == "小葵"
    assert result[0].source == "bracket"


def test_同一个词跨来源只保留一条():
    path = "/vol/archive/tg/163200-小葵/163201 - 小葵.mp4"
    texts = _texts(path)

    assert texts.count("小葵") == 1


def test_下划线不作为分隔符以保住账号型关键词():
    """monmon_tw 这类 handle 被下划线切开就废了。"""
    path = "/vol/archive/temp/平台乙 monmon_tw/平台乙 monmon_tw.mp4"
    texts = _texts(path)

    assert "monmon_tw" in texts


def test_过短的纯英文片段被丢弃():
    path = "/vol/archive/tg/100-ab 小葵/100 - ab.mp4"
    texts = _texts(path)

    assert "ab" not in texts


def test_过长的描述性片段被丢弃():
    long_text = "这是一段很长的描述性文字用来测试长度上限过滤"
    path = f"/vol/archive/tg/100-{long_text} 小葵/100 - x.mp4"
    texts = _texts(path)

    assert long_text not in texts
    assert "小葵" in texts


def test_只取文件名与直接父目录不向上追溯():
    path = "/vol/archive/tg/mediastore/163379-小葵/163379 - x.mp4"
    texts = _texts(path)

    assert "mediastore" not in texts
    assert "archive" not in texts


def test_括号内部粘着描述时切片也作为候选():
    """【小葵CC(小莉)】这种，整块和拆出来的部分都要能选到。"""
    path = "/vol/archive/tg/100-合集/100 - 【小葵CC(小莉)】第四弹.mp4"
    texts = _texts(path)

    assert "小葵CC(小莉)" in texts
    assert "小葵CC" in texts
    assert "小莉" in texts
    # 整块必须排在拆出来的部分之前，否则旧规则本能命中的样本会被挤掉
    assert texts.index("小葵CC(小莉)") < texts.index("小葵CC")


def test_去掉片段尾部编号后的变体也是候选():
    path = "/vol/archive/tg/100-小葵3 私拍/100 - x.mp4"
    texts = _texts(path)

    assert "小葵3" in texts
    assert "小葵" in texts
    assert texts.index("小葵3") < texts.index("小葵")


def test_装饰符号被当作分隔符切开():
    """▌ ✿ ⚫ @ 这类装饰符是把人名和描述粘在一起的主因。"""
    path = "/vol/archive/tg/100-✿全裸盛宴✿ 女神娃娃▌小葵▌情欲按摩/100 - WWW.98T.LA@小莉.mp4"
    texts = _texts(path)

    assert "小葵" in texts
    assert "小莉" in texts


def test_标记来源允许更长的关键词():
    """【】里是投稿者标出来的名字字段，可信度高，长度上限放宽到 32。"""
    long_name = "dulianmaomaoxiaoxin"  # 19 字符，超过自由文本 16 的上限
    path = f"/vol/archive/tg/100-合集/100 - 大神【{long_name}】更新.mp4"
    texts = _texts(path)

    assert long_name in texts


def test_自由文本仍然卡在16字以内():
    long_desc = "这是一段刻意写长的描述性文字"  # 14 字，边界内
    too_long = "这是一段刻意写得更长一些的描述性文字用于越界"  # 越界
    path = f"/vol/archive/tg/100-{long_desc} 小葵 {too_long}/100 - x.mp4"
    texts = _texts(path)

    assert "小葵" in texts
    assert too_long not in texts


def test_相似词建议会扫描全部关键词而不是只看前二十条(db_session):
    """回归：suggest_similar 早先漏传 limit，只比对按名称排序的前 20 条，
    导致库大了之后这个功能实际失效。"""
    from app.services.keywords.registry_service import KeywordRegistryService

    registry = KeywordRegistryService(db_session)
    # 先塞 30 个排序靠前的干扰词，把目标词挤出前 20
    for index in range(30):
        registry.create_entry(canonical_name=f"aaa{index:03d}", keyword_type="whitelist")
    registry.create_entry(canonical_name="zzz小葵酱", keyword_type="whitelist")

    suggestions = registry.suggest_similar(["zzz小葵酱酱"], threshold=0.75, limit=5)

    assert any(item.matched_canonical_name == "zzz小葵酱" for item in suggestions)
