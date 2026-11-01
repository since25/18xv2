from __future__ import annotations

from app.models.keywords import KeywordAlias, KeywordEntry
from app.models.downloader import DownloaderPackageCandidate
from app.services.downloader.sync_service import DownloaderSyncService


class FakeDownloader:
    def __init__(self):
        self.submitted: list[tuple[int, str]] = []
        self.packages = [
            {"id": 1, "library_id": 4, "title": "Foo One", "boundary_status": "stable", "current_download_status": "never", "index_revision": 3, "media_count": 2, "known_total_size": 100},
            {"id": 2, "library_id": 4, "title": "Foo uncertain", "boundary_status": "uncertain", "current_download_status": "never", "index_revision": 4},
            {"id": 3, "library_id": 4, "title": "Blocked Foo", "boundary_status": "stable", "current_download_status": "never", "index_revision": 5},
        ]
        self.task_payload = {
            "status": "downloading",
            "title": "Foo One",
            "total_count": 2,
            "success_count": 1,
            "failed_count": 0,
            "current_file": {"filename": "a.mp4", "download_progress": 50},
            "files": [{"message_id": "1", "status": "downloading", "filename": "a.mp4"}],
        }

    def list_packages(self, *, cursor=None, page_size=200):
        return {
            "items": self.packages,
            "next_cursor": None,
        }

    def submit_package(self, package_id: int, idempotency_key: str, *, mode="incremental"):
        self.submitted.append((package_id, idempotency_key))
        return {"batch": {"id": 10 + package_id, "task_id": f"task-{package_id}"}, "created": True}

    def list_tasks(self):
        return [{"task_id": "task-1", "status": "downloading", "title": "Foo One", "total_count": 2, "success_count": 1}]

    def get_task(self, task_id: str):
        return {"task_id": task_id, **self.task_payload}


def add_keyword(db_session, name: str, keyword_type: str, aliases: list[str] = []):
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type=keyword_type,
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    db_session.add(KeywordAlias(keyword_entry_id=entry.id, alias=name, alias_normalized=name.lower(), source="canonical"))
    for alias in aliases:
        db_session.add(KeywordAlias(keyword_entry_id=entry.id, alias=alias, alias_normalized=alias.lower(), source="manual"))
    db_session.flush()
    return entry


def test_sync_matches_whitelist_alias_and_excludes_blacklist_or_unstable(db_session):
    whitelist = add_keyword(db_session, "Foo", "whitelist", aliases=["Bar"])
    add_keyword(db_session, "Blocked", "blacklist")
    client = FakeDownloader()

    summary = DownloaderSyncService.sync_packages(db_session, client)
    candidates, total = DownloaderSyncService.list_candidates(db_session)

    assert summary.packages_seen == 3
    assert total == 1
    assert candidates[0]["remote_package_id"] == 1
    assert candidates[0]["keyword_entry_id"] == whitelist.id
    assert candidates[0]["matched_term"] == "Foo"


def test_submit_selected_is_idempotent_and_syncs_task_snapshot(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    client = FakeDownloader()
    DownloaderSyncService.sync_packages(db_session, client)
    candidates, _ = DownloaderSyncService.list_candidates(db_session)
    candidate = DownloaderSyncService.select_candidate(db_session, candidates[0]["candidate_id"], True)
    assert candidate.status == "selected"

    first = DownloaderSyncService.submit_selected(db_session, client, [candidate.id])
    second = DownloaderSyncService.submit_selected(db_session, client, [candidate.id])
    assert first.submitted == 1
    assert second.submitted == 0
    assert len(client.submitted) == 1

    task_summary = DownloaderSyncService.sync_tasks(db_session, client)
    assert task_summary.tasks_seen == 1
    rows, _ = DownloaderSyncService.list_tasks(db_session)
    assert rows[0]["remote_task_id"] == "task-1"
    assert rows[0]["current_file"]["filename"] == "a.mp4"


def test_new_package_revision_creates_new_candidate_and_preserves_old_history(db_session):
    whitelist = add_keyword(db_session, "Foo", "whitelist")
    add_keyword(db_session, "Blocked", "blacklist")
    client = FakeDownloader()
    DownloaderSyncService.sync_packages(db_session, client)
    first_candidates, _ = DownloaderSyncService.list_candidates(db_session)
    old_candidate = db_session.get(DownloaderPackageCandidate, first_candidates[0]["candidate_id"])
    old_candidate.status = "completed"
    db_session.commit()

    client.packages[0] = {
        **client.packages[0],
        "index_revision": 4,
        "completed_revision": 3,
        "current_download_status": "outdated",
        "has_successful_attempt": True,
        "media_count": 20,
        "known_total_size": 2000,
    }
    summary = DownloaderSyncService.sync_packages(db_session, client)

    pending, pending_total = DownloaderSyncService.list_candidates(db_session)
    all_candidates, all_total = DownloaderSyncService.list_candidates(db_session, candidate_status=None)
    assert summary.candidates_created == 1
    assert pending_total == 1
    assert pending[0]["package_revision"] == 4
    assert pending[0]["media_count"] == 20
    assert all_total == 2
    assert {row["package_revision"] for row in all_candidates} == {3, 4}
    assert whitelist.id in {row["keyword_entry_id"] for row in all_candidates}


def test_task_history_deduplicates_identical_payload_and_keeps_file_changes(db_session):
    client = FakeDownloader()
    DownloaderSyncService.sync_tasks(db_session, client)
    DownloaderSyncService.sync_tasks(db_session, client)
    history = DownloaderSyncService.list_task_history(db_session, "task-1")
    assert len(history) == 1
    assert history[0]["files"][0]["message_id"] == "1"

    client.task_payload = {
        **client.task_payload,
        "status": "completed_with_errors",
        "success_count": 1,
        "failed_count": 1,
        "files": [
            {"message_id": "1", "status": "downloaded", "filename": "a.mp4"},
            {"message_id": "2", "status": "failed", "filename": "b.mp4", "error": "download_failed"},
        ],
    }
    DownloaderSyncService.sync_tasks(db_session, client)
    history = DownloaderSyncService.list_task_history(db_session, "task-1")
    assert len(history) == 2
    assert history[0]["status"] == "completed_with_errors"
    assert {item["message_id"] for item in history[0]["files"]} == {"1", "2"}


def test_incremental_submission_records_no_new_items_without_remote_batch(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    client = FakeDownloader()
    DownloaderSyncService.sync_packages(db_session, client)
    candidates, _ = DownloaderSyncService.list_candidates(db_session)
    candidate = DownloaderSyncService.select_candidate(db_session, candidates[0]["candidate_id"], True)

    client.submit_package = lambda package_id, idempotency_key, *, mode="incremental": {"batch": None, "reason": "no_new_items"}
    result = DownloaderSyncService.submit_selected(db_session, client, [candidate.id])

    assert result.submitted == 0
    assert result.skipped == 1
    assert result.items[0]["status"] == "no_new_items"
