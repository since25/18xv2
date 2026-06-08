from __future__ import annotations

import json

from app.models.dedupe import DedupeGroup, DedupeScanRun
from app.models.tree import NodeFile, TreeImport
from app.services.dedupe.scan_service import DedupeScanOptions, DedupeScanService


def _seed_import(db_session) -> int:
    tree_import = TreeImport(source_filename="sample.txt", status="completed", note="test")
    db_session.add(tree_import)
    db_session.flush()
    rows = [
        NodeFile(
            tree_import=tree_import,
            raw_name="www.98T.la@Example 1080P.mp4",
            normalized_name="www.98T.la@Example 1080P.mp4",
            raw_path="根目录/待整理/www.98T.la@Example 1080P.mp4",
            parent_path="根目录/待整理",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint="a",
        ),
        NodeFile(
            tree_import=tree_import,
            raw_name="Example (1).MP4",
            normalized_name="Example (1).MP4",
            raw_path="根目录/重复/Example (1).MP4",
            parent_path="根目录/重复",
            depth=2,
            file_ext=".MP4",
            fingerprint_hint="b",
        ),
        NodeFile(
            tree_import=tree_import,
            raw_name="Different Title.mp4",
            normalized_name="Different Title.mp4",
            raw_path="根目录/待整理/Different Title.mp4",
            parent_path="根目录/待整理",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint="c",
        ),
        NodeFile(
            tree_import=tree_import,
            raw_name="Example.txt",
            normalized_name="Example.txt",
            raw_path="根目录/重复/Example.txt",
            parent_path="根目录/重复",
            depth=2,
            file_ext=".txt",
            fingerprint_hint="d",
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return tree_import.id


def test_scan_creates_persistent_duplicate_group(db_session) -> None:
    import_id = _seed_import(db_session)

    summary = DedupeScanService(db_session).scan(
        DedupeScanOptions(
            tree_import_id=import_id,
            candidate_threshold=0.82,
            high_confidence_threshold=0.92,
        )
    )

    assert summary.total_files == 3
    assert summary.total_groups == 1
    assert summary.total_candidates == 2

    scan_run = db_session.get(DedupeScanRun, summary.scan_run_id)
    assert scan_run is not None
    assert scan_run.status == "completed"
    assert scan_run.total_files == 3
    assert scan_run.total_groups == 1
    assert scan_run.total_candidates == 2
    assert scan_run.finished_at is not None
    assert json.loads(scan_run.summary_json or "{}") == {
        "scan_run_id": summary.scan_run_id,
        "total_files": 3,
        "total_groups": 1,
        "total_candidates": 2,
    }

    group = db_session.query(DedupeGroup).one()
    assert group.confidence_level == "high_probability"
    assert group.status == "pending_review"
    assert group.suggested_keep_candidate_id is not None
    assert len(group.candidates) == 2

    candidates_by_action = {candidate.suggested_action: candidate for candidate in group.candidates}
    assert set(candidates_by_action) == {"keep", "delete"}
    assert candidates_by_action["keep"].id == group.suggested_keep_candidate_id
    assert "cleaner" in (candidates_by_action["keep"].suggested_reason or "")
    assert "duplicate" in (candidates_by_action["delete"].suggested_reason or "")


def test_scope_path_prefix_limits_scan(db_session) -> None:
    import_id = _seed_import(db_session)

    summary = DedupeScanService(db_session).scan(
        DedupeScanOptions(tree_import_id=import_id, scope_path_prefix="根目录/重复")
    )

    assert summary.total_files == 1
    assert summary.total_groups == 0
    assert summary.total_candidates == 0

    scan_run = db_session.get(DedupeScanRun, summary.scan_run_id)
    assert scan_run is not None
    assert scan_run.status == "completed"
    assert scan_run.scope_path_prefix == "根目录/重复"
    assert scan_run.total_files == 1
    assert scan_run.total_groups == 0
    assert scan_run.total_candidates == 0
