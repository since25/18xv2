"""从投递路径里切出候选关键词。

纯函数模块，不查库、不依赖 Session，便于单测与回归脚本直接调用。

取材范围只有「直接父目录名 + 文件名（去扩展名）」两段：生产数据显示
272 条已批准记录里有 270 条（99.3%）的最终关键词就落在这两段内，
再往上是 /Volumes/... 这类固定仓库路径，切片全是噪声。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from app.services.keywords.registry_service import normalize_keyword_text

# 三条抽取规则
HASHTAG_RE = re.compile(r"#([^\s#]+)")
BRACKET_RE = re.compile(r"[【「『［\[]([^】」』］\]]+)[】」』］\]]")
# 分隔符 = 一切非「字母/数字/下划线/文字」的字符。\w 在 Python 里本就包含中日韩文字，
# 所以这一条同时切开空格、标点、@、点号，以及素材名里常见的装饰符（▌ ✿ ⚫️ 等）——
# 生产样本显示这些装饰符是把人名和描述粘在一起的主因。
# 刻意保留下划线：monmon_tw 这类账号型关键词被切开就废了，而下划线连接的纯数字串
# 会在归一化之后被「纯数字」规则挡掉。
SEPARATOR_RE = re.compile(r"\W+", re.UNICODE)
# 文件名/目录名开头的流水号前缀，如 "163379-" 或 "25481 - "
SERIAL_PREFIX_RE = re.compile(r"^\d+\s*[-_.]?\s*")
# 片段尾部的编号后缀，如「杏吧爱坤3」「小葵2」——生产样本里人名后跟集数编号很常见
TRAILING_INDEX_RE = re.compile(r"[0-9]+$")

# 技术噪声表：文件命名带进来的通用词，与内容无关，稳定可硬编码。
# 这不是露骨词表——露骨片段靠用户自己的「忽略」关键词库过滤。
NOISE_TOKENS = frozenset(
    {
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "m4v", "ts", "webm",
        "marked", "new", "copy", "final", "output", "untitled",
        "video", "movie", "img", "image", "photo", "pic",
        "tmp", "temp", "part", "hd", "fhd", "uhd",
        "1080p", "720p", "480p", "2160p", "4k",
    }
)

MIN_LENGTH = 2
# 长度上限按来源区分：【】和 #标签 是投稿者自己标出来的名字字段，可信度高，
# 放宽到 32；自由文本切片放宽会把整句露骨描述放进候选，仍按 16 卡死。
MAX_LENGTH_MARKED = 32
MAX_LENGTH_SEGMENT = 16
SOURCE_RANK = {"hashtag": 0, "bracket": 1, "segment": 2}


@dataclass(frozen=True)
class RawCandidate:
    """一个候选片段。text 保留原始写法，排序/去重都按归一化文本判断。"""

    text: str
    source: str
    from_parent: bool
    order: int


def _material_parts(raw_path: str) -> list[tuple[str, bool]]:
    """返回 [(取材文本, 是否来自父目录)]。"""
    cleaned = raw_path.strip()
    if not cleaned:
        return []
    pure = PurePosixPath(cleaned)
    file_stem = pure.stem or pure.name
    parent_name = pure.parent.name
    parts: list[tuple[str, bool]] = []
    if parent_name:
        parts.append((parent_name, True))
    if file_stem:
        parts.append((file_stem, False))
    return parts


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """把已被 hashtag/bracket 命中的区间抹成空格，避免同一段文字被切两次。"""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def is_noise(text: str, source: str = "segment") -> bool:
    """结构过滤。所有判断都在归一化 + casefold 之后进行。

    normalize_keyword_text 会把 _ - / ~ ( ) . 等替换成空格，
    因此必须先归一化再比对，否则 "marked~1" 这类片段永远匹配不上噪声表。
    """
    normalized = normalize_keyword_text(text).casefold()
    if not normalized:
        return True
    max_length = MAX_LENGTH_SEGMENT if source == "segment" else MAX_LENGTH_MARKED
    if len(normalized) < MIN_LENGTH or len(normalized) > max_length:
        return True
    tokens = normalized.split()
    if all(token.isdigit() for token in tokens):
        return True
    if any(token in NOISE_TOKENS for token in tokens):
        return True
    if normalized.isascii() and len(normalized) < 3:
        return True
    return False


def _sort_key(candidate: RawCandidate) -> tuple[int, int, int, int]:
    normalized = normalize_keyword_text(candidate.text)
    return (
        SOURCE_RANK.get(candidate.source, 9),
        0 if candidate.from_parent else 1,
        0 if MIN_LENGTH <= len(normalized) <= 10 else 1,
        candidate.order,
    )


def extract_raw_candidates(raw_path: str) -> list[RawCandidate]:
    """切片 → 结构过滤 → 去重 → 排序。不查库。"""
    collected: list[RawCandidate] = []
    order = 0

    def take(token: str, source: str, from_parent: bool) -> None:
        """收下一个片段，并顺带补上它的去尾号变体。

        变体排在原片段之后，保证「整块」永远优先于「拆出来的部分」，
        这样旧规则本就能命中的样本不会因为新增变体而被挤出前几名。
        """
        nonlocal order
        token = token.strip()
        if not token:
            return
        collected.append(RawCandidate(token, source, from_parent, order))
        order += 1
        trimmed = TRAILING_INDEX_RE.sub("", token).strip()
        if trimmed and trimmed != token:
            collected.append(RawCandidate(trimmed, source, from_parent, order))
            order += 1

    for text, from_parent in _material_parts(raw_path):
        spans: list[tuple[int, int]] = []

        for match in HASHTAG_RE.finditer(text):
            spans.append(match.span())
            marked = match.group(1).strip("._- ")
            take(marked, "hashtag", from_parent)
            # 标签内部还可能粘着描述，把切片也一并作为候选（排在整块之后）
            for piece in SEPARATOR_RE.split(marked):
                if piece.strip() != marked:
                    take(piece, "hashtag", from_parent)

        for match in BRACKET_RE.finditer(text):
            spans.append(match.span())
            marked = match.group(1).strip()
            take(marked, "bracket", from_parent)
            for piece in SEPARATOR_RE.split(marked):
                if piece.strip() != marked:
                    take(piece, "bracket", from_parent)

        rest = SERIAL_PREFIX_RE.sub("", _mask_spans(text, spans), count=1)
        for piece in SEPARATOR_RE.split(rest):
            take(piece, "segment", from_parent)

    survivors = [item for item in collected if not is_noise(item.text, item.source)]
    survivors.sort(key=_sort_key)

    # 同一归一化文本跨来源只保留排名最高的一条
    deduped: list[RawCandidate] = []
    seen: set[str] = set()
    for item in survivors:
        key = normalize_keyword_text(item.text).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
