from __future__ import annotations

from dataclasses import dataclass
import re

import yaml


NOISE_RE = re.compile(
    r"(\b(?:720p|1080p|2160p|4k|x264|x265|h265|bluray|web-dl|webrip)\b|\[[^\]]+\]|【[^】]+】)",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"(19|20)\d{2}")


@dataclass(slots=True)
class RuleMatch:
    tag: str
    score: float
    target_root: str
    target_template: str
    matched_keywords: list[str]
    priority: int


def normalize_folder_name(name: str) -> str:
    lowered = name.lower().strip()
    lowered = NOISE_RE.sub(" ", lowered)
    lowered = re.sub(r"[._]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def extract_keywords(name: str) -> set[str]:
    normalized = normalize_folder_name(name)
    tokens = {token for token in re.split(r"[\s/\-()]+", normalized) if token}
    year_match = YEAR_RE.findall(normalized)
    if year_match:
        tokens.update(re.findall(YEAR_RE, normalized))
    return tokens


def load_rules_from_yaml(path: str) -> dict:
    from pathlib import Path

    with Path(path).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


class KeywordClassifier:
    def __init__(self, raw_rules: dict | str):
        if isinstance(raw_rules, str):
            raw_rules = load_rules_from_yaml(raw_rules)
        self.raw_rules = raw_rules
        self.rules = sorted(self.raw_rules["rules"], key=lambda item: item["priority"])
        self.version = self.raw_rules.get("version", "rules-v1")

    @classmethod
    def from_yaml(cls, rules_file: str) -> "KeywordClassifier":
        return cls(load_rules_from_yaml(rules_file))

    def classify(self, name: str, parent_path: str | None = None) -> RuleMatch:
        haystack = " ".join(filter(None, [normalize_folder_name(name), normalize_folder_name(parent_path or "")]))
        matched_default: RuleMatch | None = None

        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            keywords = [keyword.lower() for keyword in rule.get("keywords", [])]
            matched = [keyword for keyword in keywords if keyword and keyword in haystack]
            if keywords and matched:
                score = min(0.99, 0.55 + 0.15 * len(matched))
                return RuleMatch(
                    tag=rule["name"],
                    score=score,
                    target_root=rule["target_root"],
                    target_template=rule.get("target_template", "{normalized_name}"),
                    matched_keywords=matched,
                    priority=rule["priority"],
                )
            if rule["name"] == "unsorted":
                matched_default = RuleMatch(
                    tag="unsorted",
                    score=0.2,
                    target_root=rule["target_root"],
                    target_template=rule.get("target_template", "{normalized_name}"),
                    matched_keywords=[],
                    priority=rule["priority"],
                )

        if matched_default:
            return matched_default
        return RuleMatch(
            tag="unsorted",
            score=0.1,
            target_root="/Unsorted",
            target_template="{normalized_name}",
            matched_keywords=[],
            priority=999,
        )
