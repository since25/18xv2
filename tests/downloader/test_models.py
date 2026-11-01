from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy import BigInteger

from app.models.downloader import (
    DownloaderPackage,
    DownloaderPackageCandidate,
    DownloaderSubmission,
    DownloaderTaskFileHistory,
    DownloaderTaskHistory,
)


def test_downloader_source_chat_id_supports_telegram_supergroup_ids():
    assert isinstance(DownloaderPackage.__table__.c.source_chat_id.type, BigInteger)
    assert isinstance(DownloaderPackage.__table__.c.known_total_size.type, BigInteger)


def test_downloader_package_and_candidate_defaults(db_session, fake_client):
    package = DownloaderPackage(
        node_key="rn",
        remote_package_id=101,
        library_id=7,
        title="Example package",
        boundary_status="stable",
        current_download_status="never",
        raw_payload_json="{}",
    )
    db_session.add(package)
    db_session.flush()
    candidate = DownloaderPackageCandidate(
        package_id=package.id,
        keyword_entry_id=1,
        matched_term="Example",
    )
    db_session.add(candidate)
    db_session.flush()
    assert candidate.status == "pending"
    assert candidate.package_revision == 0
    assert package.node_key == "rn"


def test_downloader_history_models_keep_revision_and_mode(db_session):
    package = DownloaderPackage(
        node_key="rn",
        remote_package_id=102,
        title="Versioned package",
        boundary_status="stable",
        current_download_status="outdated",
        completed_revision=3,
        index_revision=4,
        raw_payload_json="{}",
    )
    db_session.add(package)
    db_session.flush()
    candidate = DownloaderPackageCandidate(
        package_id=package.id,
        keyword_entry_id=2,
        package_revision=4,
        matched_term="Versioned",
    )
    submission = DownloaderSubmission(
        package_id=package.id,
        candidate_id=candidate.id,
        package_revision=4,
        download_mode="incremental",
        idempotency_key="18x:rn:package:102:r4:incremental",
    )
    db_session.add(candidate)
    db_session.flush()
    submission.candidate_id = candidate.id
    db_session.add(submission)
    db_session.flush()
    history = DownloaderTaskHistory(
        node_key="rn",
        remote_task_id="task-history",
        payload_hash="hash-1",
        status="completed_with_errors",
        total_count=20,
        success_count=18,
        failed_count=2,
        raw_payload_json="{}",
    )
    db_session.add(history)
    db_session.flush()
    db_session.add(
        DownloaderTaskFileHistory(
            history_id=history.id,
            message_id="42",
            status="failed",
            raw_payload_json="{}",
        )
    )
    db_session.commit()

    assert submission.download_mode == "incremental"
    assert history.files[0].message_id == "42"


def test_downloader_candidate_is_unique_per_package_and_keyword(db_session):
    package = DownloaderPackage(
        node_key="rn",
        remote_package_id=101,
        library_id=7,
        title="Example package",
        boundary_status="stable",
        current_download_status="never",
        raw_payload_json="{}",
    )
    db_session.add(package)
    db_session.flush()
    db_session.add_all(
        [
            DownloaderPackageCandidate(package_id=package.id, keyword_entry_id=1, matched_term="one"),
            DownloaderPackageCandidate(package_id=package.id, keyword_entry_id=1, matched_term="two"),
        ]
    )
    try:
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
    else:  # pragma: no cover - the assertion documents the required constraint
        raise AssertionError("duplicate candidate should violate the unique constraint")
