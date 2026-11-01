from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import select

from app.models.downloader import (
    DownloaderPackage,
    DownloaderPackageCandidate,
    DownloaderSubmission,
    DownloaderTaskFileHistory,
    DownloaderTaskHistory,
    DownloaderTaskSnapshot,
)
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.downloader.query_service import DownloaderQueryService
from app.services.downloader.sync_service import DownloaderSyncService


class FakePackageRemote:
    def __init__(self, packages):
        self.packages = packages

    def list_packages(self, *, cursor=None, page_size=200):
        return {"items": self.packages, "next_cursor": None}


def add_keyword(db_session, name: str, keyword_type: str):
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type=keyword_type,
        status="active",
    )
    db_session.add(entry)
    db_session.flush()
    db_session.add(KeywordAlias(keyword_entry_id=entry.id, alias=name, alias_normalized=name.lower(), source="canonical"))
    db_session.flush()
    return entry


def seed_two_keyword_package(db_session):
    first = add_keyword(db_session, "Foo", "whitelist")
    second = add_keyword(db_session, "One", "whitelist")
    remote = FakePackageRemote(
        [
            {
                "id": 1,
                "title": "Foo One package",
                "channel_title": "Foo channel",
                "boundary_status": "stable",
                "current_download_status": "never",
                "index_revision": 1,
                "media_count": 2,
                "known_total_size": 2400,
                "published_at": "2026-10-28T06:05:00+00:00",
            }
        ]
    )
    DownloaderSyncService.sync_packages(db_session, remote)
    return first, second


def test_list_inbox_aggregates_multiple_keyword_candidates_per_package(db_session):
    first, second = seed_two_keyword_package(db_session)

    items, total, counts = DownloaderQueryService.list_inbox(db_session, view="candidates")

    assert total == 1
    assert counts == {"candidates": 1, "ignored": 0, "unmatched": 0}
    assert len(items) == 1
    assert len(items[0]["candidate_ids"]) == 2
    assert {item["keyword_entry_id"] for item in items[0]["keywords"]} == {first.id, second.id}


def test_ignore_and_unignore_package_is_idempotent_and_rematches(db_session):
    seed_two_keyword_package(db_session)
    candidates, _, _ = DownloaderQueryService.list_inbox(db_session, view="candidates")
    candidate_id = candidates[0]["candidate_ids"][0]
    package_id = candidates[0]["package_id"]

    assert DownloaderQueryService.ignore_packages(db_session, candidate_ids=[candidate_id], reason="later") == 1
    assert DownloaderQueryService.ignore_packages(db_session, candidate_ids=[candidate_id], reason="later") == 0
    candidate_items, _, candidate_counts = DownloaderQueryService.list_inbox(db_session, view="candidates")
    ignored_items, _, ignored_counts = DownloaderQueryService.list_inbox(db_session, view="ignored")
    assert candidate_items == []
    assert candidate_counts == {"candidates": 0, "ignored": 1, "unmatched": 0}
    assert len(ignored_items) == 1
    assert ignored_counts == {"candidates": 0, "ignored": 1, "unmatched": 0}

    assert DownloaderQueryService.unignore_packages(db_session, [package_id]) == 1
    restored, _, restored_counts = DownloaderQueryService.list_inbox(db_session, view="candidates")
    assert len(restored) == 1
    assert restored_counts == {"candidates": 1, "ignored": 0, "unmatched": 0}
    statuses = db_session.scalars(
        select(DownloaderPackageCandidate.status).where(DownloaderPackageCandidate.package_id == package_id)
    ).all()
    assert set(statuses) == {"pending"}


def test_list_inbox_reports_new_media_and_filters_search_status_and_size(db_session):
    entry = add_keyword(db_session, "Foo", "whitelist")
    first = DownloaderPackage(
        node_key="rn",
        remote_package_id=1,
        title="Foo older package",
        boundary_status="stable",
        current_download_status="outdated",
        index_revision=2,
        completed_revision=1,
        completed_media_count=18,
        media_count=20,
        known_total_size=100,
        raw_payload_json="{}",
    )
    second = DownloaderPackage(
        node_key="rn",
        remote_package_id=2,
        title="Foo failed package",
        boundary_status="stable",
        current_download_status="cancelled",
        index_revision=1,
        media_count=2,
        known_total_size=300,
        raw_payload_json="{}",
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all(
        [
            DownloaderPackageCandidate(package_id=first.id, keyword_entry_id=entry.id, package_revision=2, matched_term="Foo"),
            DownloaderPackageCandidate(package_id=second.id, keyword_entry_id=entry.id, package_revision=1, matched_term="Foo"),
        ]
    )
    db_session.commit()

    items, total, _ = DownloaderQueryService.list_inbox(db_session, view="candidates", search="older")
    assert total == 1
    assert items[0]["new_media_count"] == 2

    failed, failed_total, _ = DownloaderQueryService.list_inbox(
        db_session, view="candidates", download_status="failed", sort="size"
    )
    assert failed_total == 1
    assert failed[0]["current_download_status"] == "cancelled"

    no_completed, _, _ = DownloaderQueryService.list_inbox(
        db_session, view="candidates", search="older", download_status="outdated"
    )
    db_session.query(DownloaderPackage).filter(DownloaderPackage.id == first.id).update({"completed_media_count": None})
    db_session.commit()
    no_count, _, _ = DownloaderQueryService.list_inbox(db_session, view="candidates", search="older")
    assert no_completed[0]["new_media_count"] == 2
    assert no_count[0]["new_media_count"] is None


def test_list_inbox_filters_by_channel_title(db_session):
    entry = add_keyword(db_session, "Foo", "whitelist")
    packages = [
        DownloaderPackage(
            node_key="rn",
            remote_package_id=index,
            title=f"Foo package {index}",
            channel_title=channel,
            boundary_status="stable",
            current_download_status="never",
            index_revision=1,
            raw_payload_json="{}",
        )
        for index, channel in enumerate(["频道 A", "频道 B"], start=1)
    ]
    db_session.add_all(packages)
    db_session.flush()
    db_session.add_all(
        [
            DownloaderPackageCandidate(package_id=package.id, keyword_entry_id=entry.id, package_revision=1, matched_term="Foo")
            for package in packages
        ]
    )
    db_session.commit()

    items, total, counts = DownloaderQueryService.list_inbox(db_session, view="candidates", channel_title="频道 B")
    assert total == 1
    assert items[0]["channel_title"] == "频道 B"
    assert counts["candidates"] == 1


def _seed_tasks(db_session):
    keyword = add_keyword(db_session, "Foo", "whitelist")
    package = DownloaderPackage(
        node_key="rn",
        remote_package_id=11,
        title="Foo task package",
        channel_title="Foo channel",
        boundary_status="stable",
        raw_payload_json="{}",
    )
    db_session.add(package)
    db_session.flush()
    candidate = DownloaderPackageCandidate(
        package_id=package.id,
        keyword_entry_id=keyword.id,
        package_revision=0,
        matched_term="Foo",
    )
    db_session.add(candidate)
    db_session.flush()
    db_session.add(
        DownloaderSubmission(
            package_id=package.id,
            candidate_id=candidate.id,
            package_revision=0,
            remote_task_id="task-1",
            idempotency_key="key-task-1",
        )
    )
    db_session.add_all(
        [
            DownloaderTaskSnapshot(
                node_key="rn",
                remote_task_id="task-1",
                title="Foo active",
                status="downloading",
                total_count=2,
                success_count=1,
                remote_created_at=datetime(2026, 10, 31, 0, tzinfo=UTC),
                remote_updated_at=datetime(2026, 11, 1, 1, tzinfo=UTC),
                total_bytes=200,
                downloaded_bytes=100,
                channel_title="Foo channel",
                current_file_json=json.dumps({"filename": "001.jpg", "download_speed_bytes": 30}),
            ),
            DownloaderTaskSnapshot(
                node_key="rn",
                remote_task_id="task-2",
                title="Foo completed",
                status="completed_with_errors",
                total_count=2,
                success_count=1,
                failed_count=1,
                remote_created_at=datetime(2026, 10, 31, 2, tzinfo=UTC),
                remote_updated_at=datetime(2026, 11, 1, 2, tzinfo=UTC),
                finished_at=datetime(2026, 11, 1, 2, tzinfo=UTC),
                total_bytes=400,
                downloaded_bytes=200,
                channel_title="Foo channel",
                current_file_json=json.dumps({"filename": "002.jpg", "download_speed_bytes": 40}),
            ),
            DownloaderTaskSnapshot(
                node_key="rn",
                remote_task_id="task-3",
                title="Old task",
                status="completed",
                remote_created_at=datetime(2026, 10, 20, tzinfo=UTC),
                finished_at=datetime(2026, 10, 20, tzinfo=UTC),
                downloaded_bytes=50,
            ),
            DownloaderTaskSnapshot(
                node_key="rn",
                remote_task_id="task-no-created",
                title="No created time",
                status="queued",
            ),
        ]
    )
    db_session.flush()
    history = DownloaderTaskHistory(
        node_key="rn",
        remote_task_id="task-2",
        payload_hash="history-task-2",
        status="completed_with_errors",
        raw_payload_json="{}",
    )
    db_session.add(history)
    db_session.flush()
    db_session.add_all(
        [
            DownloaderTaskFileHistory(
                history_id=history.id,
                message_id="001",
                filename="001.jpg",
                status="downloaded",
                total_size=100,
                downloaded_size=100,
                raw_payload_json=json.dumps({"message_id": "001", "filename": "001.jpg", "status": "downloaded", "total_size_bytes": 100, "downloaded_size_bytes": 100}),
            ),
            DownloaderTaskFileHistory(
                history_id=history.id,
                message_id="003",
                filename="003.jpg",
                status="download_failed",
                error="Connection reset by peer",
                raw_payload_json=json.dumps({"message_id": "003", "filename": "003.jpg", "status": "download_failed", "error": "Connection reset by peer"}),
            ),
        ]
    )
    db_session.commit()
    return keyword


def test_list_tasks_filters_active_time_missing_created_and_keyword(db_session):
    keyword = _seed_tasks(db_session)
    active, total = DownloaderQueryService.list_tasks(db_session, node_key="rn", status=["active"])
    assert total == 2
    assert {row["remote_task_id"] for row in active} == {"task-1", "task-no-created"}

    since = datetime(2026, 10, 30, tzinfo=UTC)
    until = datetime(2026, 11, 1, 1, 30, tzinfo=UTC)
    filtered, filtered_total = DownloaderQueryService.list_tasks(
        db_session, node_key="rn", since=since, until=until
    )
    assert filtered_total == 2
    assert {row["remote_task_id"] for row in filtered} == {"task-1", "task-2"}

    by_keyword, keyword_total = DownloaderQueryService.list_tasks(
        db_session, node_key="rn", keyword_entry_id=keyword.id
    )
    assert keyword_total == 1
    assert by_keyword[0]["remote_task_id"] == "task-1"

    all_tasks, all_total = DownloaderQueryService.list_tasks(db_session, node_key="rn")
    assert all_total == 4
    assert all_tasks[-1]["remote_task_id"] == "task-no-created"


def test_task_detail_returns_only_failed_files(db_session):
    _seed_tasks(db_session)

    detail = DownloaderQueryService.task_detail(db_session, "task-2", node_key="rn")

    assert detail is not None
    assert [file_payload["filename"] for file_payload in detail["files"]] == ["001.jpg", "003.jpg"]
    assert [file_payload["filename"] for file_payload in detail["failed_files"]] == ["003.jpg"]
    assert detail["failed_files"][0]["error"] == "Connection reset by peer"
    assert DownloaderQueryService.task_detail(db_session, "missing", node_key="rn") is None


def test_summary_counts_today_week_active_and_failed_files(db_session):
    _seed_tasks(db_session)

    result = DownloaderQueryService.summary(
        db_session, node_key="rn", now=datetime(2026, 11, 1, 12, tzinfo=UTC)
    )

    assert result == {
        "today_count": 1,
        "today_bytes": 200,
        "week_count": 1,
        "week_bytes": 200,
        "active_count": 2,
        "week_failed_files": 1,
    }


def test_list_inbox_query_count_does_not_grow_with_package_count(db_session):
    from sqlalchemy import event

    add_keyword(db_session, "Foo", "whitelist")
    remote = FakePackageRemote(
        [
            {
                "id": index,
                "title": f"Foo package {index}",
                "boundary_status": "stable",
                "current_download_status": "never",
                "index_revision": 1,
                "published_at": "2026-10-28T06:05:00+00:00",
            }
            for index in range(1, 31)
        ]
    )
    DownloaderSyncService.sync_packages(db_session, remote)

    statements: list[str] = []

    def count_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        for view in ("candidates", "ignored"):
            statements.clear()
            _, total, counts = DownloaderQueryService.list_inbox(db_session, view=view, page_size=1)
            # 30 个资源包时仍只需固定几条查询，不再逐包查询候选
            assert len(statements) <= 5, (view, len(statements))
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)
    assert counts == {"candidates": 30, "ignored": 0, "unmatched": 0}


def test_ignore_channel_ignores_only_that_channels_inbox_packages_and_exposes_rn_errors(db_session):
    add_keyword(db_session, "Foo", "whitelist")
    base = {"boundary_status": "stable", "current_download_status": "never", "index_revision": 1}
    remote = FakePackageRemote(
        [
            {**base, "id": 1, "title": "Foo a", "channel_title": "Dead channel", "current_download_status": "failed",
             "last_download_error": "channel_unavailable", "channel_last_error": "channel_unavailable"},
            {**base, "id": 2, "title": "Foo b", "channel_title": "Dead channel"},
            {**base, "id": 3, "title": "Foo c", "channel_title": "Live channel"},
        ]
    )
    DownloaderSyncService.sync_packages(db_session, remote)

    items, _, _ = DownloaderQueryService.list_inbox(db_session, view="candidates")
    dead = next(item for item in items if item["remote_package_id"] == 1)
    assert dead["last_download_error"] == "channel_unavailable"
    assert dead["channel_error"] == "channel_unavailable"

    package_ids = DownloaderQueryService.ignore_channel(db_session, "Dead channel", reason="channel_dead")
    assert len(package_ids) == 2
    remaining, _, counts = DownloaderQueryService.list_inbox(db_session, view="candidates")
    assert [item["channel_title"] for item in remaining] == ["Live channel"]
    assert counts == {"candidates": 1, "ignored": 2, "unmatched": 0}
    assert DownloaderQueryService.ignore_channel(db_session, "Dead channel") == []

    assert DownloaderQueryService.unignore_packages(db_session, package_ids) == 2
    _, _, restored_counts = DownloaderQueryService.list_inbox(db_session, view="candidates")
    assert restored_counts == {"candidates": 3, "ignored": 0, "unmatched": 0}
