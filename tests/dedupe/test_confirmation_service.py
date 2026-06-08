from __future__ import annotations

from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeRemoteConfirmation, DedupeScanRun
from app.models.tree import NodeFile, TreeImport
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.dedupe.confirmation_service import DedupeConfirmationService


class DetailFake115Client(Fake115Client):
    def __init__(self) -> None:
        super().__init__()
        self.details: dict[str, dict] = {}

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        payload = super().get_file(file_id=file_id, path=path)
        node_id = str(payload["data"]["file_id"])
        payload["data"].update(self.details.get(node_id, {}))
        return payload


def _seed_group(db_session, *, file_count: int = 1) -> tuple[list[int], int]:
    tree_import = TreeImport(source_filename="tree.txt", status="completed", source_type="file_upload")
    db_session.add(tree_import)
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
        confidence_level="high_probability",
    )
    db_session.add(group)
    db_session.flush()

    candidate_ids: list[int] = []
    for index in range(file_count):
        raw_name = "Example.mp4" if index == 0 else f"Example ({index}).mp4"
        raw_path = f"根目录/待整理/{raw_name}"
        node = NodeFile(
            tree_import=tree_import,
            raw_name=raw_name,
            normalized_name=raw_name,
            raw_path=raw_path,
            parent_path="根目录/待整理",
            depth=2,
            file_ext=".mp4",
            fingerprint_hint=f"fp-{index}",
        )
        db_session.add(node)
        db_session.flush()
        candidate = DedupeCandidate(
            group_id=group.id,
            node_file_id=node.id,
            raw_name=node.raw_name,
            raw_path=node.raw_path,
            file_ext=node.file_ext,
            normalized_name="example",
            similarity_score=0.99,
            user_action="delete" if index else "keep",
        )
        db_session.add(candidate)
        db_session.flush()
        candidate_ids.append(candidate.id)

    db_session.commit()
    return candidate_ids, group.id


def test_confirm_selected_candidate_resolves_remote_file(db_session):
    candidate_ids, group_id = _seed_group(db_session)
    client = Fake115Client()
    client.add_node(NodePayload(id="10", name="待整理", path="待整理", parent_id=None, is_file=False))
    client.add_node(NodePayload(id="11", name="Example.mp4", path="待整理/Example.mp4", parent_id="10", is_file=True))

    result = DedupeConfirmationService(db_session, client).confirm_candidates(candidate_ids)

    assert result.requested == 1
    assert result.resolved == 1
    assert result.failed == 0
    candidate = db_session.get(DedupeCandidate, candidate_ids[0])
    assert candidate is not None
    assert candidate.confirmations[-1].remote_file_id == "11"
    assert candidate.confirmations[-1].remote_path == "待整理/Example.mp4"
    assert db_session.get(DedupeGroup, group_id).confidence_level == "high_probability"


def test_confirm_missing_remote_file_records_failure(db_session):
    candidate_ids, _group_id = _seed_group(db_session)
    client = Fake115Client()

    result = DedupeConfirmationService(db_session, client).confirm_candidates(candidate_ids)

    assert result.requested == 1
    assert result.resolved == 0
    assert result.failed == 1
    confirmation = db_session.query(DedupeRemoteConfirmation).one()
    assert confirmation.status == "not_found"
    assert "待整理" in (confirmation.error_message or "")


def test_matching_sha_promotes_group_to_verified_duplicate(db_session):
    candidate_ids, group_id = _seed_group(db_session, file_count=2)
    client = DetailFake115Client()
    client.add_node(NodePayload(id="10", name="待整理", path="待整理", parent_id=None, is_file=False))
    client.add_node(NodePayload(id="11", name="Example.mp4", path="待整理/Example.mp4", parent_id="10", is_file=True))
    client.add_node(NodePayload(id="12", name="Example (1).mp4", path="待整理/Example (1).mp4", parent_id="10", is_file=True))
    client.details["11"] = {"sha1": "same-sha", "file_size": 1000}
    client.details["12"] = {"file_sha1": "same-sha", "file_size": "1000"}

    result = DedupeConfirmationService(db_session, client).confirm_candidates(candidate_ids)

    assert result.resolved == 2
    assert db_session.get(DedupeGroup, group_id).confidence_level == "verified_duplicate"
