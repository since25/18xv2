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
# 分隔符里刻意不含下划线：monmon_tw 这类账号型关键词被切开就废了，
# 而下划线连接的纯数字串会在归一化之后被「纯数字」规则挡掉。
SEPARATOR_RE = re.compile(r"[\s,，、:：;；\-/|~()（）\[\]【】]+")
# 文件名/目录名开头的流水号前缀，如 "163379-" 或 "25481 - "
SERIAL_PREFIX_RE = re.compile(r"^\d+\s*[-_.]?\s*")

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
MAX_LENGTH = 16
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


def is_noise(text: str) -> bool:
    """结构过滤。所有判断都在归一化 + casefold 之后进行。

    normalize_keyword_text 会把 _ - / ~ ( ) . 等替换成空格，
    因此必须先归一化再比对，否则 "marked~1" 这类片段永远匹配不上噪声表。
    """
    normalized = normalize_keyword_text(text).casefold()
    if not normalized:
        return True
    if len(normalized) < MIN_LENGTH or len(normalized) > MAX_LENGTH:
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

    for text, from_parent in _material_parts(raw_path):
        spans: list[tuple[int, int]] = []

        for match in HASHTAG_RE.finditer(text):
            spans.append(match.span())
            token = match.group(1).strip("._- ")
            if token:
                collected.append(RawCandidate(token, "hashtag", from_parent, order))
                order += 1

        for match in BRACKET_RE.finditer(text):
            spans.append(match.span())
            token = match.group(1).strip()
            if token:
                collected.append(RawCandidate(token, "bracket", from_parent, order))
                order += 1

        rest = SERIAL_PREFIX_RE.sub("", _mask_spans(text, spans), count=1)
        for piece in SEPARATOR_RE.split(rest):
            token = piece.strip()
            if token:
                collected.append(RawCandidate(token, "segment", from_parent, order))
                order += 1

    survivors = [item for item in collected if not is_noise(item.text)]
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
