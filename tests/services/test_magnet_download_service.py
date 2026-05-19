from __future__ import annotations

import app.services.magnet_download_service as magnet_download_service_module

from app.models.keywords import KeywordAlias, KeywordEntry
from app.models.tasks import MagnetDownloadTask
from app.models.tree import NodeFile, TreeImport, TreeNode
from app.schemas.magnet_tasks import DuplicateCheckItemRequest, MagnetTaskCreateItem
from app.services.client_115.client import Fake115Client
from app.services.magnet_download_service import MagnetDownloadService


class _FakeArticleDB:
    def score_articles(self, *args, **kwargs):
        return []


class _WhitelistArticleDB:
    def __init__(self, mapping):
        self.mapping = mapping

    def score_articles(self, query, *, matched_keyword=None, matched_alias=None, limit=None):
        rows = list(self.mapping.get(query, []))
        if limit is not None:
            rows = rows[:limit]
        return rows


class _Exploding115Client(Fake115Client):
    def search_nodes(self, *args, **kwargs):
        raise AssertionError("should not call 115 search_nodes")


class _Counting115Client(Fake115Client):
    def __init__(self):
        super().__init__()
        self.submit_calls: list[tuple[str, str | None]] = []

    def submit_magnet_download(self, magnet_url: str, target_cid: str | None = None):
        self.submit_calls.append((magnet_url, target_cid))
        return super().submit_magnet_download(magnet_url, target_cid=target_cid)


def _create_tree_import(db_session, *, source_filename: str = "tree.txt") -> TreeImport:
    tree_import = TreeImport(
        source_filename=source_filename,
        source_type="file_upload",
        status="completed",
        note="test import",
    )
    db_session.add(tree_import)
    db_session.commit()
    db_session.refresh(tree_import)
    return tree_import


def _create_whitelist_entry(db_session, *, canonical_name: str, aliases: list[str] | None = None) -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=canonical_name,
        canonical_name_normalized=canonical_name.lower(),
        keyword_type="whitelist",
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    db_session.add(
        KeywordAlias(
            keyword_entry_id=entry.id,
            alias=canonical_name,
            alias_normalized=canonical_name.lower(),
            source="canonical",
        )
    )
    for alias in aliases or []:
        db_session.add(
            KeywordAlias(
                keyword_entry_id=entry.id,
                alias=alias,
                alias_normalized=alias.lower(),
                source="manual",
            )
        )
    db_session.commit()
    db_session.refresh(entry)
    return entry


def test_local_duplicate_check_requires_more_than_single_broad_keyword(db_session) -> None:
    tree_import = _create_tree_import(db_session)
    db_session.add(
        TreeNode(
            import_id=tree_import.id,
            raw_name="Julia",
            normalized_name="julia",
            raw_path="/root/Julia",
            parent_path="/root",
            depth=1,
            node_type="folder",
            parent_id=None,
            fingerprint_hint="folder:julia",
        )
    )
    db_session.commit()

    service = MagnetDownloadService(
        db_session,
        article_db=_FakeArticleDB(),
        client_115=Fake115Client(),
    )

    result = service.check_single_duplicate(
        DuplicateCheckItemRequest(
            source_tid=1001,
            source_title="Julia Newcomer Collection Vol.1",
            source_magnet="magnet:?xt=urn:btih:test",
            matched_keyword="Julia",
            matched_alias=None,
        ),
        tree_import_id=tree_import.id,
    )

    assert result.status == "clear"


def test_local_duplicate_check_reports_specific_batch_and_path_for_strong_match(db_session) -> None:
    tree_import = _create_tree_import(db_session, source_filename="remote:root")
    db_session.add(
        NodeFile(
            import_id=tree_import.id,
            folder_node_id=None,
            raw_name="IPX-123 Julia 中文字幕.mp4",
            normalized_name="ipx 123 julia 中文字幕 mp4",
            raw_path="/root/IPX-123 Julia 中文字幕.mp4",
            parent_path="/root",
            depth=1,
            file_ext=".mp4",
            fingerprint_hint="file:ipx-123",
        )
    )
    db_session.commit()

    service = MagnetDownloadService(
        db_session,
        article_db=_FakeArticleDB(),
        client_115=Fake115Client(),
    )

    result = service.check_single_duplicate(
        DuplicateCheckItemRequest(
            source_tid=1002,
            source_title="IPX-123 Julia 完整版",
            source_magnet="magnet:?xt=urn:btih:test2",
            matched_keyword="Julia",
            matched_alias=None,
        ),
        tree_import_id=tree_import.id,
    )

    assert result.status == "duplicate_found"
    assert result.matched_import_id == tree_import.id
    assert result.matched_import_label == "remote:root"
    assert result.matched_nodes[0].path == "/root/IPX-123 Julia 中文字幕.mp4"
    assert "IPX-123" in (result.reason or "")


def test_create_and_submit_tasks_assigns_shared_batch_id(db_session) -> None:
    service = MagnetDownloadService(
        db_session,
        article_db=_FakeArticleDB(),
        client_115=Fake115Client(),
    )

    created = service.create_and_submit_tasks(
        items=[
            MagnetTaskCreateItem(
                source_tid=2001,
                source_title="IPX-001",
                source_magnet="magnet:?xt=urn:btih:1",
                match_score=0.9,
                keyword_entry_id=None,
            ),
            MagnetTaskCreateItem(
                source_tid=2002,
                source_title="IPX-002",
                source_magnet="magnet:?xt=urn:btih:2",
                match_score=0.8,
                keyword_entry_id=None,
            ),
        ],
        target_cid=None,
        force_submit=False,
        tree_import_id=None,
    )

    assert len(created) == 2
    assert created[0].batch_id
    assert created[0].batch_id == created[1].batch_id

    rows = db_session.query(MagnetDownloadTask).order_by(MagnetDownloadTask.id.asc()).all()
    assert len(rows) == 2
    assert rows[0].batch_id == rows[1].batch_id


def test_duplicate_check_without_tree_import_does_not_call_115_search(db_session) -> None:
    service = MagnetDownloadService(
        db_session,
        article_db=_FakeArticleDB(),
        client_115=_Exploding115Client(),
    )

    result = service.check_single_duplicate(
        DuplicateCheckItemRequest(
            source_tid=3001,
            source_title="IPX-123 Julia",
            source_magnet="magnet:?xt=urn:btih:test3",
            matched_keyword="Julia",
            matched_alias=None,
        ),
        tree_import_id=None,
    )

    assert result.status == "clear"
    assert "不再调用 115 搜索接口" in (result.reason or "")


def test_create_and_submit_tasks_waits_between_actual_submissions(db_session, monkeypatch) -> None:
    sleep_calls: list[int] = []
    client = _Counting115Client()
    service = MagnetDownloadService(
        db_session,
        article_db=_FakeArticleDB(),
        client_115=client,
    )
    service.settings.offline_submit_interval_seconds = 10
    monkeypatch.setattr(magnet_download_service_module.time, "sleep", sleep_calls.append)

    created = service.create_and_submit_tasks(
        items=[
            MagnetTaskCreateItem(
                source_tid=4001,
                source_title="IPX-010",
                source_magnet="magnet:?xt=urn:btih:10",
                match_score=0.9,
                keyword_entry_id=None,
            ),
            MagnetTaskCreateItem(
                source_tid=4002,
                source_title="IPX-011",
                source_magnet="magnet:?xt=urn:btih:11",
                match_score=0.8,
                keyword_entry_id=None,
            ),
        ],
        target_cid=None,
        force_submit=False,
        tree_import_id=None,
    )

    assert [task.status for task in created] == ["submitted", "submitted"]
    assert len(client.submit_calls) == 2
    assert sleep_calls == [10]
