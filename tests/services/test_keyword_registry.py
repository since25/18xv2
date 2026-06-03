"""
KeywordRegistryService 单元测试。覆盖 create/duplicate/alias/merge 关键路径。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.whitelist import WhitelistCandidate
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text


class TestCreateEntry:
    def test_creates_entry_with_canonical_alias(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        entry = svc.create_entry(canonical_name="测试词", keyword_type="whitelist")

        assert entry.id is not None
        assert entry.canonical_name == "测试词"
        assert entry.keyword_type == "whitelist"
        # 创建时自动建 canonical alias
        alias_values = [a.alias for a in entry.aliases]
        assert "测试词" in alias_values

    def test_duplicate_create_returns_existing(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        e1 = svc.create_entry(canonical_name="重复词", keyword_type="whitelist")
        e2 = svc.create_entry(canonical_name="重复词", keyword_type="whitelist")
        assert e1.id == e2.id

    def test_create_with_aliases(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        entry = svc.create_entry(canonical_name="主词", keyword_type="whitelist", aliases=["别名A", "别名B"])
        alias_values = [a.alias for a in entry.aliases]
        assert "别名A" in alias_values
        assert "别名B" in alias_values

    def test_find_entry_by_keyword(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        svc.create_entry(canonical_name="查找目标", keyword_type="whitelist")
        found = svc.find_entry_by_keyword("查找目标")
        assert found is not None
        assert found.canonical_name == "查找目标"

    def test_find_nonexistent_returns_none(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        assert svc.find_entry_by_keyword("不存在的词") is None


class TestMergeEntries:
    def test_merge_moves_aliases(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        canonical = svc.create_entry(canonical_name="主词条", keyword_type="whitelist")
        secondary = svc.create_entry(canonical_name="副词条", keyword_type="whitelist")

        result = svc.merge_entries(canonical.id, [secondary.id])
        alias_values = [a.alias for a in result.aliases]
        # 合并后副词条的 canonical name 成为主词条的 alias
        assert "副词条" in alias_values


class TestDeleteEntry:
    def test_delete_entry_removes_whitelist_candidates(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        entry = svc.create_entry(canonical_name="待删白名单", keyword_type="whitelist")
        candidate = WhitelistCandidate(
            source_tid=1001,
            source_magnet="magnet:?xt=urn:btih:delete-me",
            source_title="候选资源",
            matched_keyword_entry_id=entry.id,
            matched_keyword=entry.canonical_name,
            duplicate_status="clear",
            target_path="/target",
        )
        db_session.add(candidate)
        db_session.commit()

        assert svc.delete_entry(entry.id) is True

        remaining = db_session.scalars(select(WhitelistCandidate)).all()
        assert remaining == []
        assert svc.find_entry_by_keyword("待删白名单") is None


class TestScanDuplicateKeywords:
    def test_scan_duplicate_keywords_considers_aliases(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        svc.create_entry(canonical_name="Alpha", keyword_type="whitelist", aliases=["ABP31"])
        svc.create_entry(canonical_name="ABP-31", keyword_type="whitelist")

        pairs = svc.scan_duplicate_keywords(keyword_type="whitelist", threshold=0.85)

        assert len(pairs) == 1
        left, right, score = pairs[0]
        assert {left.canonical_name, right.canonical_name} == {"Alpha", "ABP-31"}
        assert score >= 0.85

    def test_scan_duplicate_keywords_skips_same_entry_aliases(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        svc.create_entry(canonical_name="31", keyword_type="whitelist", aliases=["三一号"])
        svc.create_entry(canonical_name="ABP-123", keyword_type="whitelist")

        pairs = svc.scan_duplicate_keywords(keyword_type="whitelist", threshold=0.85)

        assert pairs == []


class TestNormalizeKeywordText:
    def test_strip_and_normalize(self):
        assert normalize_keyword_text("  Hello  ") == "Hello"

    def test_converts_separators_to_spaces(self):
        result = normalize_keyword_text("some-thing_here")
        assert "some" in result and "thing" in result

    def test_empty_string(self):
        assert normalize_keyword_text("") == ""
