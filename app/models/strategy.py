from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyRule(Base):
    __tablename__ = "strategy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    match_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="contains_any")
    keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    target_root: Mapped[str] = mapped_column(String(255), nullable=False)
    target_template: Mapped[str] = mapped_column(Text, nullable=False, default="{normalized_name}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
