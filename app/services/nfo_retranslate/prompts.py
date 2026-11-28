"""给模型的内容与输出检查：演员对照表、系统提示词、用户消息、译文检查。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Literal
import xml.etree.ElementTree as ET

SYSTEM_PROMPT = """你是一位专业的日本成人影片翻译专员，擅长把影片的日文标题或简介翻译成简体中文，也熟悉行业专有名词的译法。
翻译规则如下：
1. 人名：用户消息里的「演员对照」列出了本片演员的日文写法和对应的中文写法，译文里出现这些人时一律用给出的中文写法；对照里没有的人名（素人昵称等）保留日文原文，不要翻译或音译。
2. 栏目名、系列名、厂牌名、番号和英文专名保留原文（如「ラグジュTV」「S1 NO.1 STYLE」「SSIS-951」），其中的期数照原样保留，不要换算或解释（如「56in渋谷」中的「56in」）。
3. 如果是标题：翻译成简体中文，超过30个汉字时精简到30字以内，优先保留剧情关键词。
4. 如果是简介：先去掉与影片无关的内容（优惠价格、促销期限、活动公告、购买说明、官网链接、特典说明等），保留全部与剧情、人物、场景相关的句子，不要概括或删减剧情，再翻译成流畅的简体中文，不限字数；原文的换行照样保留。
5. 确保语法流畅，符合中文阅读习惯，不要故意隐去敏感词。
输出要求：
绝对禁止添加任何形式的标签（如「标题」「中文翻译」等）、解释或说明。你的回答必须有且仅有翻译后的中文文本本身，不包含任何其他字符。"""

_FIELD_NAMES = {"title": "标题", "plot": "简介"}
# 日文假名（平假名、片假名）
_KANA = re.compile("[぀-ヿ]")
_WHITESPACE = re.compile(r"\s")
# 首尾成对的引号
_QUOTE_PAIRS = (("「", "」"), ('"', '"'), ("“", "”"))
# 模型自带的「标题：」「Title:」之类标签
_LABEL_PREFIX = re.compile(
    r"^(?:标题|简介|翻译|中文翻译|译文|中文标题|中文简介|Title|Plot|Translation)\s*[：:]", re.IGNORECASE
)
# 拒绝话术：只看开头，避免误伤剧情里本来就有的「对不起」「我不能」
_REFUSAL_PREFIXES = ("抱歉", "很抱歉", "对不起", "无法翻译", "我不能", "I cannot", "I can't", "I'm sorry")
_MIN_CHARS = 2
_MAX_KANA_PERCENT = 15
_MAX_TITLE_CHARS = 60


def load_actor_glossary(path: str) -> dict[str, tuple[str, ...]]:
    """读 MDC 的 mapping_actor.xml：zh_cn → 其他写法（jp、zh_tw、keyword 拆开），去重、去空、不含 zh_cn 本身。

    文件读不了或不是合法 XML 时抛 ValueError。
    """
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"演员对照表读不了：{path}（{exc}）") from exc
    glossary: dict[str, list[str]] = {}
    for row in root.iter("a"):
        zh_cn = (row.get("zh_cn") or "").strip()
        if not zh_cn:
            continue
        others = glossary.setdefault(zh_cn, [])
        names = [row.get("jp") or "", row.get("zh_tw") or ""] + (row.get("keyword") or "").split(",")
        for name in names:
            name = name.strip()
            if name and name != zh_cn and name not in others:
                others.append(name)
    return {zh_cn: tuple(others) for zh_cn, others in glossary.items()}


def build_user_message(
    field: Literal["title", "plot"],
    *,
    num: str,
    actors: Sequence[str],
    glossary: Mapping[str, tuple[str, ...]],
    studio: str,
    series: str,
    text: str,
) -> str:
    """拼一次请求的用户消息：类型、番号、演员对照、片商、系列（有才带）、原文。"""
    lines = [f"类型：{_FIELD_NAMES[field]}", f"番号：{num}"]
    pairs = [f"{'、'.join(glossary[actor])} → {actor}" for actor in actors if glossary.get(actor)]
    if pairs:
        lines.append(f"演员对照：{'；'.join(pairs)}")
    if studio.strip():
        lines.append(f"片商：{studio.strip()}")
    if series.strip():
        lines.append(f"系列：{series.strip()}")
    lines.append("原文：")
    lines.append(text)
    return "\n".join(lines)


def known_names(actors: Sequence[str], glossary: Mapping[str, tuple[str, ...]]) -> list[str]:
    """本片演员的所有写法：演员名本身加对照表里的其他写法，去重、保持顺序。"""
    names: list[str] = []
    for actor in actors:
        for name in (actor, *glossary.get(actor, ())):
            if name and name not in names:
                names.append(name)
    return names


def _char_count(text: str) -> int:
    """去掉空白后的字数。"""
    return len(_WHITESPACE.sub("", text))


def _clean(output: str) -> str:
    """去首尾空白，再去首尾成对的引号（中间还有同种引号时不剥，免得拆坏台词）。"""
    text = output.strip()
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            inner = text[len(left) : -len(right)]
            if left not in inner and right not in inner:
                return inner.strip()
    return text


def _kana_too_many(text: str, names: Sequence[str]) -> bool:
    """去掉已知人名后，假名占非空白字数的比例是否超过上限。"""
    for name in sorted(names, key=len, reverse=True):
        if name:
            text = text.replace(name, "")
    total = _char_count(text)
    if total == 0:
        return False
    return len(_KANA.findall(text)) * 100 > total * _MAX_KANA_PERCENT


def validate_output(
    field: Literal["title", "plot"], source: str, output: str, *, names: Sequence[str]
) -> tuple[str | None, str | None]:
    """检查模型输出。通过返回 (清理后的译文, None)，不通过返回 (None, 失败原因)。"""
    text = _clean(output)
    length = _char_count(text)
    if length < _MIN_CHARS:
        return None, "译文为空或不到 2 个字"
    if _LABEL_PREFIX.match(text):
        return None, "译文带了标签开头"
    if "<think>" in text or "</think>" in text:
        return None, "译文含思考标签"
    lowered = text.lower()
    if any(lowered.startswith(prefix.lower()) for prefix in _REFUSAL_PREFIXES):
        return None, "译文是拒绝话术"
    if _kana_too_many(text, names):
        return None, f"假名占比超过 {_MAX_KANA_PERCENT}%，疑似没翻"
    if field == "title":
        if length > _MAX_TITLE_CHARS:
            return None, f"标题超过 {_MAX_TITLE_CHARS} 字"
    else:
        source_length = _char_count(source)
        if length * 5 < source_length:
            return None, "简介不到原文的 20%"
        if length > source_length * 3:
            return None, "简介超过原文的 3 倍"
    return text, None
