from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
import re
import unicodedata


DEFAULT_NOISE_WORDS: tuple[str, ...] = (
    "www.98t.la",
    "98t.la",
    "高清",
    "全集下面已更新",
)

QUALITY_TAG_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:480p|720p|1080p|2160p|4k|x264|x265|h264|h265|hevc)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
COPY_MARKER_RE = re.compile(
    r"(?:\(\s*\d+\s*\)\s*$|(?<![A-Za-z0-9])(?:copy|副本|复制)(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
SITE_PREFIX_RE = re.compile(r"^\s*(?P<prefix>[^@]{1,80})@\s*")
DOMAIN_RE = re.compile(r"^(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"[/\\._\-]+")
SPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class DedupeRuleSet:
    noise_words: list[str] = field(default_factory=list)
    regex_patterns: list[str] = field(default_factory=list)
    strip_quality_tags: bool = True
    strip_copy_markers: bool = True


@dataclass(slots=True)
class NormalizedFilename:
    raw_name: str
    normalized_name: str
    tokens: list[str]
    applied_rules: list[str]


def normalize_filename(raw_name: str, rules: DedupeRuleSet | None = None) -> NormalizedFilename:
    active_rules = rules or DedupeRuleSet()
    applied_rules: list[str] = []
    name = unicodedata.normalize("NFKC", _strip_extension(raw_name))

    name = _remove_site_prefix(name, active_rules, applied_rules)
    name = _remove_noise_words(name, active_rules, applied_rules)
    name = _apply_custom_regexes(name, active_rules, applied_rules)

    if active_rules.strip_quality_tags:
        name = _sub_with_rule(QUALITY_TAG_RE, " ", name, "quality_tag", applied_rules)

    if active_rules.strip_copy_markers:
        name = _sub_with_rule(COPY_MARKER_RE, " ", name, "copy_marker", applied_rules)

    normalized_name = _finalize_name(name)
    tokens = normalized_name.split(" ") if normalized_name else []
    return NormalizedFilename(
        raw_name=raw_name,
        normalized_name=normalized_name,
        tokens=tokens,
        applied_rules=applied_rules,
    )


def preview_normalization(raw_names: list[str], rules: DedupeRuleSet | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_name in raw_names:
        normalized = normalize_filename(raw_name, rules)
        rows.append(
            {
                "raw_name": normalized.raw_name,
                "normalized_name": normalized.normalized_name,
                "tokens": normalized.tokens,
                "applied_rules": normalized.applied_rules,
            }
        )
    return rows


def _strip_extension(raw_name: str) -> str:
    name = PurePath(str(raw_name or "")).name
    if "." not in name.lstrip("."):
        return name
    return name.rsplit(".", 1)[0]


def _remove_site_prefix(name: str, rules: DedupeRuleSet, applied_rules: list[str]) -> str:
    match = SITE_PREFIX_RE.match(name)
    if not match:
        return name

    prefix = match.group("prefix").strip()
    if _looks_like_site_prefix(prefix, rules):
        _record_rule(applied_rules, "site_prefix")
        return name[match.end() :]
    return name


def _looks_like_site_prefix(prefix: str, rules: DedupeRuleSet) -> bool:
    folded_prefix = prefix.casefold()
    noise_words = [word.casefold() for word in _all_noise_words(rules)]
    return folded_prefix in noise_words or bool(DOMAIN_RE.match(prefix))


def _remove_noise_words(name: str, rules: DedupeRuleSet, applied_rules: list[str]) -> str:
    updated = name
    for word in _all_noise_words(rules):
        if not word:
            continue
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        updated = _sub_with_rule(pattern, " ", updated, "noise_word", applied_rules)
    return updated


def _apply_custom_regexes(name: str, rules: DedupeRuleSet, applied_rules: list[str]) -> str:
    updated = name
    for pattern_text in rules.regex_patterns:
        if not pattern_text:
            continue
        pattern = re.compile(pattern_text, re.IGNORECASE)
        updated = _sub_with_rule(pattern, " ", updated, "custom_regex", applied_rules)
    return updated


def _sub_with_rule(pattern: re.Pattern[str], replacement: str, name: str, rule_name: str, applied_rules: list[str]) -> str:
    updated = pattern.sub(replacement, name)
    if updated != name:
        _record_rule(applied_rules, rule_name)
    return updated


def _all_noise_words(rules: DedupeRuleSet) -> tuple[str, ...]:
    return (*DEFAULT_NOISE_WORDS, *tuple(rules.noise_words))


def _finalize_name(name: str) -> str:
    normalized = SEPARATOR_RE.sub(" ", name)
    normalized = SPACE_RE.sub(" ", normalized)
    return normalized.strip().casefold()


def _record_rule(applied_rules: list[str], rule_name: str) -> None:
    if rule_name not in applied_rules:
        applied_rules.append(rule_name)
