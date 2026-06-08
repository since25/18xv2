from __future__ import annotations

import pytest

from app.models.dedupe import (
    DedupeCandidate,
    DedupeDeletePlan,
    DedupeDeletePlanItem,
    DedupeGroup,
    DedupeRemoteConfirmation,
    DedupeScanRun,
)
from app.models.tree import NodeFile, TreeImport
from app.services.client_115.schemas import NodePayload
from app.services.dedupe.delete_plan_service import DedupeDeletePlanService


def _seed_delete_candidate(
    db_session,
    *,
    confidence_level: str = "verified_duplicate",
    with_confirmation: bool = True,
) -> tuple[int, str]:
    tree_import = TreeImport(source_filename="tree.txt", status="completed", source_type="file_upload")
    db_session.add(tree_import)
    db_session.flush()
    node = NodeFile(
        tree_import=tree_import,
        raw_name="Example (1).mp4",
        normalized_name="Example (1).mp4",
        raw_path="根目录/重复/Example (1).mp4",
        parent_path="根目录/重复",
        depth=2,
        file_ext=".mp4",
        fingerprint_hint="fp",
    )
    db_session.add(node)
    db_session.flush()
    run = DedupeScanRun(tree_import_id=tree_import.id, status="completed")
    db_session.add(run)
    db_session.flush()
    group = DedupeGroup(
        scan_run_id=run.id,
        tree_import_id=tree_import.id,
        group_key="g",
        representative_name="Example.mp4",
        normalized_name="example",
        score_max=0.99,
        confidence_level=confidence_level,
        status="confirmed",
    )
    db_session.add(group)
    db_session.flush()
    candidate = DedupeCandidate(
        group_id=group.id,
        node_file_id=node.id,
        raw_name=node.raw_name,
        raw_path=node.raw_path,
        file_ext=node.file_ext,
        normalized_name="example",
        similarity_score=0.99,
        suggested_action="delete",
        suggested_reason="Likely duplicate.",
        user_action="delete",
    )
    db_session.add(candidate)
    db_session.flush()
    remote_file_id = "file-1"
    if with_confirmation:
        db_session.add(
            DedupeRemoteConfirmation(
                candidate_id=candidate.id,
                status="resolved",
                remote_file_id=remote_file_id,
                remote_path="重复/Example (1).mp4",
                remote_name=node.raw_name,
                sha1="sha",
                size_bytes=1000,
            )
        )
    db_session.commit()
    return candidate.id, remote_file_id


def test_create_plan_requires_resolved_remote_file_id(db_session):
    candidate_id, _remote_file_id = _seed_delete_candidate(db_session, with_confirmation=False)

    service = DedupeDeletePlanService(db_session, client=None)
    with pytest.raises(ValueError, match="remote confirmation"):
        service.create_plan(name="bad", candidate_ids=[candidate_id], rate_limit_seconds=2.0)


def test_create_plan_rejects_filename_suspected_candidates(db_session):
    candidate_id, _remote_file_id = _seed_delete_candidate(
        db_session,
        confidence_level="filename_suspected",
        with_confirmation=True,
    )

    service = DedupeDeletePlanService(db_session, client=None)
    with pytest.raises(ValueError, match="filename_suspected"):
        service.create_plan(name="too risky", candidate_ids=[candidate_id], rate_limit_seconds=2.0)


def test_create_plan_persists_pending_item(db_session):
    candidate_id, remote_file_id = _seed_delete_candidate(db_session)

    plan = DedupeDeletePlanService(db_session, client=None).create_plan(
        name="delete duplicates",
        candidate_ids=[candidate_id],
        rate_limit_seconds=1.5,
    )

    assert plan.status == "draft"
    assert plan.total_items == 1
    assert plan.rate_limit_seconds == 1.5
    item = db_session.query(DedupeDeletePlanItem).one()
    assert item.plan_id == plan.id
    assert item.remote_file_id == remote_file_id
    assert item.status == "pending"
    assert item.confirmation_level == "verified_duplicate"


def test_execute_plan_requires_second_confirmation(db_session, fake_client):
    candidate_id, _remote_file_id = _seed_delete_candidate(db_session)
    plan = DedupeDeletePlanService(db_session, client=None).create_plan(
        name="delete duplicates",
        candidate_ids=[candidate_id],
        rate_limit_seconds=0,
    )

    with pytest.raises(ValueError, match="confirm"):
        DedupeDeletePlanService(db_session, fake_client).execute_plan(plan.id, confirm=False, sleep_seconds=0)


def test_execute_plan_deletes_each_pending_item(db_session, fake_client):
    candidate_id, remote_file_id = _seed_delete_candidate(db_session)
    fake_client.add_node(
        NodePayload(
            id=remote_file_id,
            name="Example (1).mp4",
            path="重复/Example (1).mp4",
            parent_id=None,
            is_file=True,
        )
    )
    plan = DedupeDeletePlanService(db_session, client=None).create_plan(
        name="delete duplicates",
        candidate_ids=[candidate_id],
        rate_limit_seconds=0,
    )

    summary = DedupeDeletePlanService(db_session, fake_client).execute_plan(
        plan.id,
        confirm=True,
        sleep_seconds=0,
    )

    assert summary.deleted == 1
    assert summary.failed == 0
    assert summary.skipped == 0
    assert remote_file_id not in fake_client.nodes
    db_session.expire_all()
    assert db_session.get(DedupeDeletePlan, plan.id).status == "completed"
