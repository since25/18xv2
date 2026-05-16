from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tree import NodeFile


NOISE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("packing_hint", re.compile(r"(收藏不迷路|最新地址|最新地址|获取地址|访问地址)", re.IGNORECASE)),
    ("numbered_copy", re.compile(r"^(?:mp4_|V)\s*\(\d+\)\.(?:mp4|mkv|avi|mov)$", re.IGNORECASE)),
    # Plain numeric image/text files are often package residue; numeric videos are too common to auto-flag.
    ("serial_media", re.compile(r"^\d{2,4}\.(?:jpg|jpeg|png|txt|nfo|url)$", re.IGNORECASE)),
    ("ad_text", re.compile(r"\.(?:txt|url|nfo)$", re.IGNORECASE)),
    ("domain_hint", re.compile(r"[A-Za-z0-9-]+\.(?:com|net|org|cc|xyz)", re.IGNORECASE)),
]


@dataclass(slots=True)
class NoiseFileStat:
    filename: str
    file_ids: set[int]
    examples: list[str]
    reasons: set[str]

    @property
    def count(self) -> int:
        return len(self.file_ids)

    @property
    def score(self) -> float:
        base = float(self.count)
        if "packing_hint" in self.reasons:
            base += 4.0
        if "domain_hint" in self.reasons:
            base += 2.0
        if "ad_text" in self.reasons:
            base += 1.5
        if "numbered_copy" in self.reasons:
            base += 1.0
        if "serial_media" in self.reasons:
            base += 0.5
        return base


class NoiseFileService:
    def __init__(self, db: Session):
        self.db = db

    def _load_files(self, import_id: int, file_ids: list[int] | None = None) -> list[NodeFile]:
        query = select(NodeFile).where(NodeFile.import_id == import_id)
        if file_ids:
            query = query.where(NodeFile.id.in_(file_ids))
        return list(self.db.scalars(query).all())

    def list_candidates(
        self,
        import_id: int,
        min_count: int = 2,
        limit: int = 30,
        file_ids: list[int] | None = None,
        suspicious_only: bool = True,
    ) -> tuple[list[NoiseFileStat], int]:
        nodes = self._load_files(import_id=import_id, file_ids=file_ids)
        grouped: dict[str, NoiseFileStat] = {}

        for node in nodes:
            reasons = self._detect_reasons(node.raw_name)
            stat = grouped.setdefault(
                node.raw_name,
                NoiseFileStat(filename=node.raw_name, file_ids=set(), examples=[], reasons=set()),
            )
            stat.file_ids.add(node.id)
            stat.reasons.update(reasons)
            if len(stat.examples) < 5:
                stat.examples.append(node.raw_path)

        filtered: list[NoiseFileStat] = []
        for stat in grouped.values():
            if stat.count < min_count:
                continue
            if suspicious_only and not stat.reasons:
                continue
            filtered.append(stat)

        filtered.sort(key=lambda item: (-item.score, -item.count, item.filename))
        return filtered[:limit], len(nodes)

    def _detect_reasons(self, filename: str) -> set[str]:
        reasons: set[str] = set()
        for reason, pattern in NOISE_PATTERNS:
            if pattern.search(filename):
                reasons.add(reason)
        return reasons
