from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tree import TreeNode


FLAG_MAP = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
}


@dataclass(slots=True)
class ExtractedKeywordStat:
    keyword: str
    count: int
    source: str
    examples: list[str]


@dataclass(slots=True)
class RegexPreviewItem:
    node_id: int
    folder_name: str
    raw_path: str
    extracted_keyword: str


class KeywordExtractorService:
    def __init__(self, db: Session):
        self.db = db

    def _load_folder_nodes(self, import_id: int, node_ids: list[int] | None = None) -> list[TreeNode]:
        query = select(TreeNode).where(TreeNode.import_id == import_id, TreeNode.node_type == "folder")
        if node_ids:
            query = query.where(TreeNode.id.in_(node_ids))
        query = query.order_by(TreeNode.id.asc())
        return list(self.db.scalars(query).all())

    def extract_manual_keywords(
        self,
        import_id: int,
        keywords: list[str],
        *,
        node_ids: list[int] | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> tuple[list[ExtractedKeywordStat], int]:
        nodes = self._load_folder_nodes(import_id=import_id, node_ids=node_ids)
        cleaned_keywords = [self._clean_keyword(item) for item in keywords]
        cleaned_keywords = [item for item in cleaned_keywords if item]

        stats: list[ExtractedKeywordStat] = []
        for keyword in cleaned_keywords:
            examples: list[str] = []
            count = 0
            needle = keyword if case_sensitive else keyword.lower()
            for node in nodes:
                haystack = node.raw_name if case_sensitive else node.raw_name.lower()
                if needle in haystack:
                    count += 1
                    if len(examples) < 5:
                        examples.append(node.raw_path)
            if count > 0:
                stats.append(
                    ExtractedKeywordStat(keyword=keyword, count=count, source="manual", examples=examples)
                )
        stats.sort(key=lambda item: (-item.count, item.keyword))
        return stats[:limit], len(nodes)

    def extract_regex_keywords(
        self,
        import_id: int,
        pattern: str,
        *,
        node_ids: list[int] | None = None,
        flags: str = "",
        group_index: int = 1,
        min_count: int = 1,
        limit: int = 100,
    ) -> tuple[list[ExtractedKeywordStat], list[RegexPreviewItem], int]:
        nodes = self._load_folder_nodes(import_id=import_id, node_ids=node_ids)
        compiled = re.compile(pattern, self._parse_flags(flags))
        grouped: OrderedDict[str, ExtractedKeywordStat] = OrderedDict()
        preview: list[RegexPreviewItem] = []

        for node in nodes:
            seen_keywords: set[str] = set()
            for match in compiled.finditer(node.raw_name):
                extracted = self._extract_group_value(match, group_index)
                keyword = self._clean_keyword(extracted)
                if not keyword:
                    continue
                if keyword in seen_keywords:
                    continue
                seen_keywords.add(keyword)

                stat = grouped.get(keyword)
                if stat is None:
                    stat = ExtractedKeywordStat(keyword=keyword, count=0, source="regex", examples=[])
                    grouped[keyword] = stat
                stat.count += 1
                if len(stat.examples) < 5:
                    stat.examples.append(node.raw_path)
                preview.append(
                    RegexPreviewItem(
                        node_id=node.id,
                        folder_name=node.raw_name,
                        raw_path=node.raw_path,
                        extracted_keyword=keyword,
                    )
                )

        stats = [item for item in grouped.values() if item.count >= min_count]
        stats.sort(key=lambda item: (-item.count, item.keyword))
        return stats, preview, len(nodes)

    def extract_regex_keywords_from_path(
        self,
        raw_path: str,
        pattern: str,
        *,
        flags: str = "",
        group_index: int = 1,
        limit: int = 100,
    ) -> tuple[list[ExtractedKeywordStat], list[RegexPreviewItem], int]:
        cleaned_path = raw_path.strip()
        if not cleaned_path:
            raise ValueError("raw_path is required")

        compiled = re.compile(pattern, self._parse_flags(flags))
        target_name = PurePosixPath(cleaned_path).name or cleaned_path
        grouped: OrderedDict[str, ExtractedKeywordStat] = OrderedDict()
        preview: list[RegexPreviewItem] = []
        seen_keywords: set[str] = set()

        for match in compiled.finditer(target_name):
            extracted = self._extract_group_value(match, group_index)
            keyword = self._clean_keyword(extracted)
            if not keyword or keyword in seen_keywords:
                continue
            seen_keywords.add(keyword)

            stat = grouped.get(keyword)
            if stat is None:
                stat = ExtractedKeywordStat(keyword=keyword, count=0, source="manual_path_regex", examples=[])
                grouped[keyword] = stat
            stat.count += 1
            if len(stat.examples) < 5:
                stat.examples.append(cleaned_path)
            preview.append(
                RegexPreviewItem(
                    node_id=0,
                    folder_name=target_name,
                    raw_path=cleaned_path,
                    extracted_keyword=keyword,
                )
            )

        stats = list(grouped.values())
        stats.sort(key=lambda item: (-item.count, item.keyword))
        return stats[:limit], preview[:limit], 1

    def _parse_flags(self, flags: str) -> int:
        resolved = 0
        for flag in flags:
            resolved |= FLAG_MAP.get(flag.lower(), 0)
        return resolved

    def _extract_group_value(self, match: re.Match[str], group_index: int) -> str:
        if group_index == 0:
            return match.group(0)
        if group_index > match.re.groups:
            raise ValueError(f"group_index {group_index} exceeds regex groups {match.re.groups}")
        return match.group(group_index)

    def _clean_keyword(self, raw: str | None) -> str | None:
        if raw is None:
            return None
        cleaned = raw.strip().strip("._- ").replace("/", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if len(cleaned) < 2:
            return None
        return cleaned
