"""
KeywordRegistryService 单元测试。覆盖 create/duplicate/alias/merge 关键路径。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordAlias, KeywordOperationLog
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

    def test_create_entry_defaults_merge_policy_to_normal(self, db_session: Session):
        svc = KeywordRegistryService(db_session)

        entry = svc.create_entry(canonical_name="口巾SANG", keyword_type="whitelist")

        assert entry.merge_policy == "normal"

    def test_create_and_update_entry_persist_fallback_only_policy(self, db_session: Session):
        svc = KeywordRegistryService(db_session)

        entry = svc.create_entry(
            canonical_name="露脸_泄密_反差_电报",
            keyword_type="whitelist",
            merge_policy="fallback_only",
        )

        assert entry.merge_policy == "fallback_only"

        updated = svc.update_entry(entry.id, merge_policy="normal")

        assert updated.merge_policy == "normal"

    def test_find_entry_by_keyword(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        svc.create_entry(canonical_name="查找目标", keyword_type="whitelist")
        found = svc.find_entry_by_keyword("查找目标")
        assert found is not None
        assert found.canonical_name == "查找目标"

    def test_find_nonexistent_returns_none(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        assert svc.find_entry_by_keyword("不存在的词") is None

    def test_create_entry_no_commit_flushes_without_committing(self, db_session: Session, monkeypatch):
        def fail_commit():
            raise AssertionError("create_entry_no_commit must not commit")

        monkeypatch.setattr(db_session, "commit", fail_commit)
        svc = KeywordRegistryService(db_session)

        entry = svc.create_entry_no_commit(
            canonical_name="事务演员",
            keyword_type="emby_whitelist",
            note="测试备注",
            source="emby_media_actions",
        )

        assert entry.id is not None
        assert entry.canonical_name == "事务演员"
        alias = db_session.scalar(select(KeywordAlias).where(KeywordAlias.keyword_entry_id == entry.id))
        assert alias is not None
        assert alias.alias == "事务演员"
        log = db_session.scalar(select(KeywordOperationLog).where(KeywordOperationLog.keyword_entry_id == entry.id))
        assert log is not None
        assert log.action == "create_entry"
        assert json.loads(log.detail or "{}")["source"] == "emby_media_actions"


class TestMergeEntries:
    def test_merge_moves_aliases(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        canonical = svc.create_entry(canonical_name="主词条", keyword_type="whitelist")
        secondary = svc.create_entry(canonical_name="副词条", keyword_type="whitelist")

        result = svc.merge_entries(canonical.id, [secondary.id])
        alias_values = [a.alias for a in result.aliases]
        # 合并后副词条的 canonical name 成为主词条的 alias
        assert "副词条" in alias_values

    def test_merge_moves_whitelist_candidate_references(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        canonical = svc.create_entry(canonical_name="主白名单", keyword_type="whitelist")
        secondary = svc.create_entry(canonical_name="副白名单", keyword_type="whitelist")
        db_session.add_all(
            [
                WhitelistCandidate(
                    source_tid=2001,
                    source_magnet="magnet:?xt=urn:btih:merge-a",
                    source_title="主候选",
                    matched_keyword_entry_id=canonical.id,
                    matched_keyword=canonical.canonical_name,
                    duplicate_status="clear",
                    target_path="/target/main",
                ),
                WhitelistCandidate(
                    source_tid=2002,
                    source_magnet="magnet:?xt=urn:btih:merge-b",
                    source_title="副候选",
                    matched_keyword_entry_id=secondary.id,
                    matched_keyword=secondary.canonical_name,
                    duplicate_status="clear",
                    target_path="/target/secondary",
                ),
            ]
        )
        db_session.commit()

        svc.merge_entries(canonical.id, [secondary.id])

        rows = db_session.scalars(select(WhitelistCandidate).order_by(WhitelistCandidate.id)).all()
        assert len(rows) == 2
        assert {row.matched_keyword_entry_id for row in rows} == {canonical.id}
        assert {row.matched_keyword for row in rows} == {canonical.canonical_name}
        assert svc.find_entry_by_keyword("副白名单") is not None
        assert db_session.get(type(canonical), secondary.id) is None

    def test_merge_deduplicates_conflicting_whitelist_candidate_references(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        canonical = svc.create_entry(canonical_name="主白名单", keyword_type="whitelist")
        secondary = svc.create_entry(canonical_name="副白名单", keyword_type="whitelist")
        shared = {
            "source_tid": 2003,
            "source_magnet": "magnet:?xt=urn:btih:merge-shared",
            "source_title": "同一个资源",
            "duplicate_status": "clear",
            "target_path": "/target/shared",
        }
        db_session.add_all(
            [
                WhitelistCandidate(
                    **shared,
                    matched_keyword_entry_id=canonical.id,
                    matched_keyword=canonical.canonical_name,
                    lifecycle_status="pending",
                ),
                WhitelistCandidate(
                    **shared,
                    matched_keyword_entry_id=secondary.id,
                    matched_keyword=secondary.canonical_name,
                    lifecycle_status="submitted",
                ),
            ]
        )
        db_session.commit()

        svc.merge_entries(canonical.id, [secondary.id])

        rows = db_session.scalars(select(WhitelistCandidate)).all()
        assert len(rows) == 1
        assert rows[0].matched_keyword_entry_id == canonical.id
        assert rows[0].matched_keyword == canonical.canonical_name
        assert rows[0].lifecycle_status == "submitted"


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

    def test_count_whitelist_candidate_references(self, db_session: Session):
        svc = KeywordRegistryService(db_session)
        first = svc.create_entry(canonical_name="Alpha", keyword_type="whitelist")
        second = svc.create_entry(canonical_name="ABP-31", keyword_type="whitelist")
        db_session.add_all(
            [
                WhitelistCandidate(
                    source_tid=3001,
                    source_magnet="magnet:?xt=urn:btih:refs-a",
                    source_title="引用 A",
                    matched_keyword_entry_id=first.id,
                    matched_keyword=first.canonical_name,
                    duplicate_status="clear",
                    target_path="/target/a",
                ),
                WhitelistCandidate(
                    source_tid=3002,
                    source_magnet="magnet:?xt=urn:btih:refs-b",
                    source_title="引用 B",
                    matched_keyword_entry_id=first.id,
                    matched_keyword=first.canonical_name,
                    duplicate_status="clear",
                    target_path="/target/b",
                ),
                WhitelistCandidate(
                    source_tid=3003,
                    source_magnet="magnet:?xt=urn:btih:refs-c",
                    source_title="引用 C",
                    matched_keyword_entry_id=second.id,
                    matched_keyword=second.canonical_name,
                    duplicate_status="clear",
                    target_path="/target/c",
                ),
            ]
        )
        db_session.commit()

        counts = svc.count_whitelist_candidate_references([first.id, second.id, 9999])

        assert counts == {first.id: 2, second.id: 1, 9999: 0}


class TestNormalizeKeywordText:
    def test_strip_and_normalize(self):
        assert normalize_keyword_text("  Hello  ") == "Hello"

    def test_converts_separators_to_spaces(self):
        result = normalize_keyword_text("some-thing_here")
        assert "some" in result and "thing" in result

    def test_empty_string(self):
        assert normalize_keyword_text("") == ""
