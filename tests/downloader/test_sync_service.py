from __future__ import annotations

from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.downloader.sync_service import DownloaderSyncService


class FakeDownloader:
    def __init__(self):
        self.submitted: list[tuple[int, str]] = []

    def list_packages(self, *, cursor=None, page_size=200):
        return {
            "items": [
                {"id": 1, "library_id": 4, "title": "Foo One", "boundary_status": "stable", "current_download_status": "never", "index_revision": 3, "media_count": 2, "known_total_size": 100},
                {"id": 2, "library_id": 4, "title": "Foo uncertain", "boundary_status": "uncertain", "current_download_status": "never", "index_revision": 4},
                {"id": 3, "library_id": 4, "title": "Blocked Foo", "boundary_status": "stable", "current_download_status": "never", "index_revision": 5},
            ],
            "next_cursor": None,
        }

    def submit_package(self, package_id: int, idempotency_key: str):
        self.submitted.append((package_id, idempotency_key))
        return {"batch": {"id": 10 + package_id, "task_id": f"task-{package_id}"}, "created": True}

    def list_tasks(self):
        return [{"task_id": "task-1", "status": "downloading", "title": "Foo One", "total_count": 2, "success_count": 1}]

    def get_task(self, task_id: str):
        return {"task_id": task_id, "status": "downloading", "title": "Foo One", "total_count": 2, "success_count": 1, "current_file": {"filename": "a.mp4", "download_progress": 50}}


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
