from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.strategy import StrategyRule
from app.services.classifier.keyword_classifier import KeywordClassifier, load_rules_from_yaml


class StrategyRuleService:
    def __init__(self, db: Session | None = None):
        self.db = db
        self.settings = get_settings()

    def build_classifier(self) -> KeywordClassifier:
        source = (self.settings.strategy_source or "auto").lower()
        if source not in {"auto", "db", "yaml"}:
            raise ValueError(f"Unsupported STRATEGY_SOURCE: {self.settings.strategy_source}")

        if source in {"auto", "db"} and self.db is not None:
            db_rules = self._load_rules_from_db()
            if db_rules["rules"]:
                return KeywordClassifier(db_rules)
            if source == "db":
                raise ValueError("STRATEGY_SOURCE=db but strategy_rules table is empty")

        return KeywordClassifier.from_yaml(self.settings.rules_file)

    def sync_yaml_to_db(self, rules_file: str | None = None) -> dict[str, int | str]:
        if self.db is None:
            raise ValueError("Database session is required for sync")

        payload = load_rules_from_yaml(rules_file or self.settings.rules_file)
        desired_rules = payload.get("rules", [])
        existing = {
            row.name: row for row in self.db.scalars(select(StrategyRule)).all()
        }

        seen_names: set[str] = set()
        for item in desired_rules:
            name = str(item["name"])
            seen_names.add(name)
            row = existing.get(name)
            values = {
                "enabled": bool(item.get("enabled", True)),
                "priority": int(item.get("priority", 100)),
                "match_mode": str(item.get("match_mode", "contains_any")),
                "keywords_json": list(item.get("keywords", [])),
                "target_root": str(item["target_root"]),
                "target_template": str(item.get("target_template", "{normalized_name}")),
            }
            if row is None:
                self.db.add(StrategyRule(name=name, **values))
                continue
            for key, value in values.items():
                setattr(row, key, value)

        for name, row in existing.items():
            if name not in seen_names:
                row.enabled = False

        self.db.commit()
        return {"version": str(payload.get("version", "rules-v1")), "rule_count": len(desired_rules)}

    def _load_rules_from_db(self) -> dict:
        rows = list(
            self.db.scalars(select(StrategyRule).where(StrategyRule.enabled.is_(True)).order_by(StrategyRule.priority.asc())).all()
        )
        return {
            "version": "db-rules-v1",
            "rules": [
                {
                    "name": row.name,
                    "enabled": row.enabled,
                    "priority": row.priority,
                    "match_mode": row.match_mode,
                    "keywords": list(row.keywords_json),
                    "target_root": row.target_root,
                    "target_template": row.target_template,
                }
                for row in rows
            ],
        }
