from __future__ import annotations

from dataclasses import dataclass

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
        sql = text(
            """
            select tid, title, magnet, detail_url, section, category, sub_type, size
            from public.article
            where title ilike :pattern
            order by publish_date desc nulls last, tid desc
            limit :limit
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, {"pattern": f"%{query.strip()}%", "limit": resolved_limit}).mappings().all()
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

    def score_articles(self, query: str, *, matched_keyword: str | None = None, matched_alias: str | None = None, limit: int | None = None) -> list[tuple[ArticleRecord, float]]:
        records = self.search_articles(query, limit=limit)
        anchor = matched_alias or matched_keyword or query
        scored = [(record, similarity_score(anchor, record.title)) for record in records]
        scored.sort(key=lambda item: (item[1], item[0].tid), reverse=True)
        return scored
