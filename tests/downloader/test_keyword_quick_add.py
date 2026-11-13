from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.downloader import DownloaderPackage, DownloaderPackageCandidate
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.downloader.keyword_quick_add import KeywordQuickAddError, quick_add_keyword
from app.services.downloader.query_service import DownloaderQueryService
from app.services.downloader.sync_service import DownloaderSyncService


class FakePackageRemote:
    def __init__(self, titles):
        self.titles = titles

    def list_packages(self, *, cursor=None, page_size=200):
        items = [
            {
                "id": index + 1,
                "title": title,
                "channel_title": "频道",
                "boundary_status": "stable",
                "current_download_status": "never",
                "index_revision": 1,
                "media_count": 1,
            }
            for index, title in enumerate(self.titles)
        ]
        return {"items": items, "next_cursor": None}


def add_keyword(db_session, name: str, keyword_type: str, aliases: tuple[str, ...] = ()):
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type=keyword_type,
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    for alias in (name, *aliases):
        db_session.add(
            KeywordAlias(keyword_entry_id=entry.id, alias=alias, alias_normalized=alias.lower(), source="manual")
        )
    db_session.flush()
    return entry


def seed(db_session, titles):
    DownloaderSyncService.sync_packages(db_session, FakePackageRemote(titles))
    db_session.commit()


def pending_count(db_session) -> int:
    return db_session.scalar(
        select(func.count()).select_from(DownloaderPackageCandidate).where(DownloaderPackageCandidate.status == "pending")
    )


def test_blacklist_dry_run_reports_but_writes_nothing(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    seed(db_session, ["Foo Bar pack", "Foo Baz pack"])
    assert pending_count(db_session) == 2

    result = quick_add_keyword(db_session, keyword=" bar ", list_type="blacklist", dry_run=True)

    assert result["candidates_dismissed"] == 1
    assert result["candidates_created"] == 0
    assert result["packages_affected"] == 1
    assert result["sample_titles"] == ["Foo Bar pack"]
    assert result["entry_status"] == "created"
    assert result["keyword_entry_id"] is None
    assert db_session.scalar(select(KeywordEntry).where(KeywordEntry.canonical_name_normalized == "bar")) is None
    assert pending_count(db_session) == 2


def test_blacklist_commit_dismisses_matching_candidates(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    seed(db_session, ["Foo Bar pack", "Foo Baz pack"])

    result = quick_add_keyword(db_session, keyword="bar", list_type="blacklist", dry_run=False)

    assert result["candidates_dismissed"] == 1
    entry = db_session.get(KeywordEntry, result["keyword_entry_id"])
    assert entry.keyword_type == "blacklist"
    assert entry.status == "active"
    items, _, counts = DownloaderQueryService.list_inbox(db_session, view="candidates")
    assert [item["title"] for item in items] == ["Foo Baz pack"]
    assert counts["candidates"] == 1


def test_whitelist_commit_creates_candidates_from_unmatched(db_session):
    seed(db_session, ["Qux pack", "Other pack"])

    result = quick_add_keyword(db_session, keyword="QUX", list_type="whitelist", dry_run=False)

    assert result["candidates_created"] == 1
    assert result["packages_affected"] == 1
    items, _, _ = DownloaderQueryService.list_inbox(db_session, view="candidates")
    assert [item["title"] for item in items] == ["Qux pack"]


def test_whitelist_skips_ignored_and_blacklisted_packages(db_session):
    add_keyword(db_session, "bad", "blacklist")
    seed(db_session, ["Qux one", "Qux bad"])
    first = db_session.scalar(select(DownloaderPackage).where(DownloaderPackage.title == "Qux one"))
    DownloaderQueryService.ignore_packages(db_session, package_ids=[first.id], reason="test")
    db_session.commit()

    result = quick_add_keyword(db_session, keyword="qux", list_type="whitelist", dry_run=False)

    assert result["packages_affected"] == 2
    assert result["candidates_created"] == 0
    assert pending_count(db_session) == 0


def test_rejects_short_keyword(db_session):
    with pytest.raises(KeywordQuickAddError) as error:
        quick_add_keyword(db_session, keyword=" a ", list_type="blacklist", dry_run=True)
    assert error.value.status_code == 400


def test_rejects_existing_keyword_of_other_type(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    db_session.commit()

    with pytest.raises(KeywordQuickAddError) as error:
        quick_add_keyword(db_session, keyword="foo", list_type="blacklist", dry_run=False)
    assert error.value.status_code == 409
    assert "关键词页" in str(error.value)


def test_existing_alias_same_type_reuses_entry(db_session):
    entry = add_keyword(db_session, "Foo", "whitelist", aliases=("Fu",))
    seed(db_session, ["Fu pack"])
    before = db_session.scalar(select(func.count()).select_from(KeywordEntry))

    result = quick_add_keyword(db_session, keyword="fu", list_type="whitelist", dry_run=False)

    assert result["entry_status"] == "existing"
    assert result["keyword_entry_id"] == entry.id
    assert db_session.scalar(select(func.count()).select_from(KeywordEntry)) == before
    assert pending_count(db_session) == 1


def test_conflict_check_ignores_case(db_session):
    # 生产里正名归一化保留大小写，下载器匹配却不分大小写
    entry = KeywordEntry(canonical_name="Foo", canonical_name_normalized="Foo", keyword_type="whitelist", status="active")
    db_session.add(entry)
    db_session.commit()

    with pytest.raises(KeywordQuickAddError) as error:
        quick_add_keyword(db_session, keyword="foo", list_type="blacklist", dry_run=True)
    assert error.value.status_code == 409


def test_rejects_disabled_keyword_of_same_type(db_session):
    entry = add_keyword(db_session, "Foo", "blacklist")
    entry.status = "inactive"
    db_session.commit()

    with pytest.raises(KeywordQuickAddError) as error:
        quick_add_keyword(db_session, keyword="foo", list_type="blacklist", dry_run=False)
    assert error.value.status_code == 409
    assert "停用" in str(error.value)
