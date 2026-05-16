from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import create_engine, text

from app.core.config import Settings, get_settings
from app.services.keywords.registry_service import normalize_keyword_text, similarity_score


@dataclass(slots=True)
class ArticleRecord:
    tid: int
    title: str
    magnet: str
    detail_url: str | None
    section: str | None
    category: str | None
    sub_type: str | None
    size: int | None


class SourceArticleDatabaseError(RuntimeError):
    pass


class SourceArticleDatabaseService:
    cjk_pattern = re.compile(r"[\u4e00-\u9fff]")

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _database_url(self) -> str:
        if not self.settings.source_article_db_host or not self.settings.source_article_db_name:
            raise SourceArticleDatabaseError("SOURCE_ARTICLE_DB_HOST or SOURCE_ARTICLE_DB_NAME is not configured")
        user = self.settings.source_article_db_user or "postgres"
        password = self.settings.source_article_db_password or ""
        return (
            f"postgresql+psycopg://{user}:{password}@{self.settings.source_article_db_host}:"
            f"{self.settings.source_article_db_port}/{self.settings.source_article_db_name}"
        )

    def search_articles(self, query: str, *, limit: int | None = None) -> list[ArticleRecord]:
        normalized_query = normalize_keyword_text(query)
        if not normalized_query:
            return []
        resolved_limit = max(1, limit or self.settings.source_article_search_limit)
        engine = create_engine(self._database_url(), future=True)
        sql, params = self._build_search_sql(query=normalized_query, limit=resolved_limit)
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [
            ArticleRecord(
                tid=int(row["tid"]),
                title=str(row["title"]),
                magnet=str(row["magnet"]),
                detail_url=row["detail_url"],
                section=row["section"],
                category=row["category"],
                sub_type=row["sub_type"],
                size=row["size"],
            )
            for row in rows
        ]

    @classmethod
    def _build_search_sql(cls, *, query: str, limit: int) -> tuple[object, dict[str, object]]:
        if cls._should_use_word_boundary_match(query):
            return (
                text(
                    """
                    select tid, title, magnet, detail_url, section, category, sub_type, size
                    from public.article
                    where title ~* :regex_pattern
                    order by publish_date desc nulls last, tid desc
                    limit :limit
                    """
                ),
                {"regex_pattern": cls._build_word_boundary_regex(query), "limit": limit},
            )
        return (
            text(
                """
                select tid, title, magnet, detail_url, section, category, sub_type, size
                from public.article
                where title ilike :pattern
                order by publish_date desc nulls last, tid desc
                limit :limit
                """
            ),
            {"pattern": f"%{query.strip()}%", "limit": limit},
        )

    @staticmethod
    def _should_use_word_boundary_match(query: str) -> bool:
        normalized = normalize_keyword_text(query)
        if not normalized:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9]+(?: [A-Za-z0-9]+)*", normalized))

    @staticmethod
    def _build_word_boundary_regex(query: str) -> str:
        normalized = normalize_keyword_text(query)
        tokens = [re.escape(token) for token in normalized.split() if token]
        body = r"[\s._\-]*".join(tokens)
        return rf"(^|[^0-9A-Za-z]){body}($|[^0-9A-Za-z])"

    def score_articles(self, query: str, *, matched_keyword: str | None = None, matched_alias: str | None = None, limit: int | None = None) -> list[tuple[ArticleRecord, float]]:
        records = self.search_articles(query, limit=limit)
        anchor = matched_alias or matched_keyword or query
        scored = [(record, self._score_title_match(anchor, record.title)) for record in records]
        scored.sort(key=lambda item: (item[1], item[0].tid), reverse=True)
        return scored

    @classmethod
    def _score_title_match(cls, anchor: str, title: str) -> float:
        base = similarity_score(anchor, title)
        normalized_anchor = normalize_keyword_text(anchor)
        if not cls._should_use_word_boundary_match(normalized_anchor):
            return base

        score = base
        boundary_pattern = cls._build_word_boundary_regex(normalized_anchor)
        boundary_matches = list(re.finditer(boundary_pattern, title, re.IGNORECASE))
        if boundary_matches:
            score += 0.35
            if cls.cjk_pattern.search(title):
                score += 0.15
            if cls._has_wrapped_exact_match(normalized_anchor, title):
                score += 0.2
        return round(score, 4)

    @staticmethod
    def _has_wrapped_exact_match(anchor: str, title: str) -> bool:
        escaped = re.escape(anchor)
        patterns = [
            rf"[【\[]\s*{escaped}\s*[】\]]",
            rf"[『「（(]\s*{escaped}\s*[』」）)]",
        ]
        return any(re.search(pattern, title, re.IGNORECASE) for pattern in patterns)
