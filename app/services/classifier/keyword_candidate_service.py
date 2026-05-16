from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tree import TreeNode


BRACKET_PATTERNS = [
    re.compile(r"【([^】]{2,40})】"),
    re.compile(r"「([^」]{2,40})」"),
    re.compile(r"『([^』]{2,40})』"),
    re.compile(r"\[([^\]]{2,40})\]"),
    re.compile(r"［([^］]{2,40})］"),
    re.compile(r"\(([^)]{2,40})\)"),
    re.compile(r"（([^）]{2,40})）"),
]
CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,20}")
STOPWORDS = {
    "最新",
    "重磅",
    "内部",
    "至尊",
    "完整",
    "高清",
    "超清",
    "合集",
    "作品",
    "大神",
    "顶级",
    "新品",
    "福利",
    "清纯",
    "露脸",
    "学妹",
    "女神",
}


@dataclass(slots=True)
class CandidateStat:
    keyword: str
    node_ids: set[int]
    examples: list[str]
    bracket_hits: int = 0

    @property
    def count(self) -> int:
        return len(self.node_ids)

    @property
    def score(self) -> float:
        base = float(self.count)
        return base + self.bracket_hits * 0.5 + min(len(self.keyword), 10) * 0.05


class KeywordCandidateService:
    def __init__(self, db: Session):
        self.db = db

    def _load_nodes(self, import_id: int, node_ids: list[int] | None = None) -> list[TreeNode]:
        query = select(TreeNode).where(TreeNode.import_id == import_id, TreeNode.node_type == "folder")
        if node_ids:
            query = query.where(TreeNode.id.in_(node_ids))
        return list(self.db.scalars(query).all())

    def list_candidates(self, import_id: int, min_count: int = 2, limit: int = 30, node_ids: list[int] | None = None) -> tuple[list[CandidateStat], int]:
        nodes = self._load_nodes(import_id=import_id, node_ids=node_ids)
        stats: dict[str, CandidateStat] = {}

        for node in nodes:
            seen_for_node: set[str] = set()
            bracket_terms = self._extract_bracket_terms(node.raw_name)
            plain_terms = self._extract_plain_terms(node.raw_name)

            for keyword in bracket_terms + plain_terms:
                if keyword in seen_for_node:
                    continue
                seen_for_node.add(keyword)
                stat = stats.setdefault(keyword, CandidateStat(keyword=keyword, node_ids=set(), examples=[]))
                stat.node_ids.add(node.id)
                if len(stat.examples) < 5:
                    stat.examples.append(node.raw_path)
                if keyword in bracket_terms:
                    stat.bracket_hits += 1

        filtered = [stat for stat in stats.values() if stat.count >= min_count]
        filtered.sort(key=lambda item: (-item.score, -item.count, item.keyword))
        return filtered[:limit], len(nodes)

    def _extract_bracket_terms(self, name: str) -> list[str]:
        results: list[str] = []
        for pattern in BRACKET_PATTERNS:
            for match in pattern.findall(name):
                cleaned = self._clean_keyword(match)
                if cleaned:
                    results.append(cleaned)
        return results

    def _extract_plain_terms(self, name: str) -> list[str]:
        results: list[str] = []
        for match in CHINESE_RUN_RE.findall(name):
            cleaned = self._clean_keyword(match)
            if cleaned:
                results.append(cleaned)
        for match in ASCII_TOKEN_RE.findall(name):
            cleaned = self._clean_keyword(match)
            if cleaned:
                results.append(cleaned)
        return results

    def _clean_keyword(self, raw: str) -> str | None:
        cleaned = raw.strip().strip("._- ").replace("/", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if len(cleaned) < 2:
            return None
        if cleaned.lower() in {"mp4", "mkv", "avi", "mov"}:
            return None
        if cleaned in STOPWORDS:
            return None
        if cleaned.isdigit():
            return None
        return cleaned
