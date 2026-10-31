from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.models.downloader import DownloaderPackage, DownloaderPackageCandidate


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
    assert package.node_key == "rn"


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
