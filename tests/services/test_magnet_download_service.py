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

    result = service._check_single_duplicate(
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

    result = service._check_single_duplicate(
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

    result = service._check_single_duplicate(
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


def test_preview_whitelist_batch_dedupes_cross_keyword_candidates_and_builds_target_path(db_session) -> None:
    julia = _create_whitelist_entry(db_session, canonical_name="Julia", aliases=["Julia Ann"])
    mia = _create_whitelist_entry(db_session, canonical_name="Mia")
    tree_import = _create_tree_import(db_session, source_filename="local-tree")
    db_session.add(
        NodeFile(
            import_id=tree_import.id,
            folder_node_id=None,
            raw_name="MIA-222 Mia 中文字幕.mp4",
            normalized_name="mia 222 mia 中文字幕 mp4",
            raw_path="/root/MIA-222 Mia 中文字幕.mp4",
            parent_path="/root",
            depth=1,
            file_ext=".mp4",
            fingerprint_hint="file:mia-222",
        )
    )
    db_session.commit()

    same_record = magnet_download_service_module.ArticleRecord(
        tid=5001,
        title="JUL-001 Julia Ann Debut",
        magnet="magnet:?xt=urn:btih:5001",
        detail_url="https://example.com/5001",
        section="A",
        category=None,
        sub_type=None,
        size=None,
    )
    duplicate_record = magnet_download_service_module.ArticleRecord(
        tid=5002,
        title="MIA-222 Mia Collection",
        magnet="magnet:?xt=urn:btih:5002",
        detail_url="https://example.com/5002",
        section="B",
        category=None,
        sub_type=None,
        size=None,
    )
    article_db = _WhitelistArticleDB(
        {
            "Julia": [(same_record, 0.86)],
            "Julia Ann": [(same_record, 0.97)],
            "Mia": [(duplicate_record, 0.95)],
        }
    )

    service = MagnetDownloadService(db_session, article_db=article_db, client_115=Fake115Client())
    preview_run = service.preview_whitelist_batch(
        tree_import_id=tree_import.id,
        per_keyword_limit=5,
        total_limit=10,
    )
    entries = preview_run.whitelist_entries
    preview = preview_run.preview_items

    assert len(entries) == 2
    assert preview_run.scanned_keyword_count == 2
    assert preview_run.total_candidates == 2
    assert len(preview) == 2
    assert preview[0].item.source_tid == 5001
    assert preview[0].item.matched_alias == "Julia Ann"
    assert preview[0].target_path == "/已整理/Julia/JUL-001 Julia Ann Debut"
    assert preview[0].duplicate_status == "clear"
    assert preview[1].item.source_tid == 5002
    assert preview[1].duplicate_status == "duplicate_found"
    assert preview[1].matched_import_id == tree_import.id
    assert preview[1].target_path == "/已整理/Mia/MIA-222 Mia Collection"


def test_submit_whitelist_batch_creates_nested_target_directories_and_uses_submit_limit(db_session, monkeypatch) -> None:
    julia = _create_whitelist_entry(db_session, canonical_name="Julia")
    mia = _create_whitelist_entry(db_session, canonical_name="Mia")
    tree_import = _create_tree_import(db_session)

    article_db = _WhitelistArticleDB(
        {
            "Julia": [
                (
                    magnet_download_service_module.ArticleRecord(
                        tid=6001,
                        title="JUL-600 Julia First",
                        magnet="magnet:?xt=urn:btih:6001",
                        detail_url=None,
                        section=None,
                        category=None,
                        sub_type=None,
                        size=None,
                    ),
                    0.91,
                )
            ],
            "Mia": [
                (
                    magnet_download_service_module.ArticleRecord(
                        tid=6002,
                        title="MIA-600 Mia Second",
                        magnet="magnet:?xt=urn:btih:6002",
                        detail_url=None,
                        section=None,
                        category=None,
                        sub_type=None,
                        size=None,
                    ),
                    0.89,
                )
            ],
        }
    )
    client = _Counting115Client()
    sleep_calls: list[int] = []
    monkeypatch.setattr(magnet_download_service_module.time, "sleep", sleep_calls.append)

    service = MagnetDownloadService(db_session, article_db=article_db, client_115=client)
    service.settings.offline_submit_interval_seconds = 7

    preview_run, tasks = service.submit_whitelist_batch(
        tree_import_id=tree_import.id,
        keyword_entry_ids=[julia.id, mia.id],
        per_keyword_limit=5,
        total_limit=10,
        submit_limit=1,
        force_submit=False,
    )
    entries = preview_run.whitelist_entries
    preview_items = preview_run.preview_items

    assert len(entries) == 2
    assert preview_run.scanned_keyword_count == 2
    assert preview_run.total_candidates == 2
    assert len(preview_items) == 2
    assert len(tasks) == 1
    assert tasks[0].status == "submitted"
    assert client.submit_calls == [("magnet:?xt=urn:btih:6001", "3")]
    assert "1" in client.nodes and client.nodes["1"].path == "已整理"
    assert "2" in client.nodes and client.nodes["2"].path == "已整理/Julia"
    assert "3" in client.nodes and client.nodes["3"].path == "已整理/Julia/JUL-600 Julia First"
    assert sleep_calls == []


def test_preview_whitelist_batch_reuses_single_tree_index_and_duplicate_result_cache(db_session, monkeypatch) -> None:
    entry = _create_whitelist_entry(db_session, canonical_name="Julia", aliases=["Julia Ann"])
    tree_import = _create_tree_import(db_session, source_filename="local-tree")
    db_session.add(
        NodeFile(
            import_id=tree_import.id,
            folder_node_id=None,
            raw_name="JUL-001 Julia Ann Debut.mp4",
            normalized_name="jul 001 julia ann debut mp4",
            raw_path="/root/JUL-001 Julia Ann Debut.mp4",
            parent_path="/root",
            depth=1,
            file_ext=".mp4",
            fingerprint_hint="file:jul-001",
        )
    )
    db_session.commit()

    same_record = magnet_download_service_module.ArticleRecord(
        tid=7001,
        title="JUL-001 Julia Ann Debut",
        magnet="magnet:?xt=urn:btih:7001",
        detail_url=None,
        section=None,
        category=None,
        sub_type=None,
        size=None,
    )
    article_db = _WhitelistArticleDB({"Julia": [(same_record, 0.86)], "Julia Ann": [(same_record, 0.97)]})
    service = MagnetDownloadService(db_session, article_db=article_db, client_115=Fake115Client())

    build_calls: list[int] = []
    original_get_index = service._get_local_tree_index

    def tracked_get_index(tree_import_id: int):
        build_calls.append(tree_import_id)
        return original_get_index(tree_import_id)

    monkeypatch.setattr(service, "_get_local_tree_index", tracked_get_index)

    preview_run = service.preview_whitelist_batch(
        tree_import_id=tree_import.id,
        keyword_entry_ids=[entry.id],
        per_keyword_limit=5,
        total_limit=10,
    )

    assert len(preview_run.preview_items) == 1
    assert build_calls == [tree_import.id]
