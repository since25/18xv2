from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeRemoteConfirmation
from app.services.client_115.client import Client115Error


@dataclass(slots=True)
class DedupeConfirmationSummary:
    requested: int
    resolved: int
    failed: int


class DedupeConfirmationService:
    def __init__(self, db: Session, client):
        self.db = db
        self.client = client

    def confirm_candidates(self, candidate_ids: list[int]) -> DedupeConfirmationSummary:
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            return DedupeConfirmationSummary(requested=0, resolved=0, failed=0)

        candidates = list(
            self.db.scalars(
                select(DedupeCandidate)
                .where(DedupeCandidate.id.in_(unique_ids))
                .order_by(DedupeCandidate.id.asc())
            ).all()
        )
        found_ids = {candidate.id for candidate in candidates}
        resolved = 0
        failed = len(set(unique_ids) - found_ids)

        for candidate in candidates:
            try:
                remote_file_id = self._resolve_path_to_id(candidate.raw_path)
                data = self.client.get_file(file_id=remote_file_id).get("data", {})
                self.db.add(
                    DedupeRemoteConfirmation(
                        candidate_id=candidate.id,
                        status="resolved",
                        remote_file_id=remote_file_id,
                        remote_parent_id=_optional_str(data.get("parent_id")),
                        remote_path=self._remote_path(remote_file_id, candidate.raw_path),
                        remote_name=data.get("file_name") or candidate.raw_name,
                        sha1=data.get("sha1") or data.get("file_sha1"),
                        size_bytes=_optional_int(data.get("file_size")),
                        file_status=_optional_str(data.get("area_id") or data.get("file_category")),
                    )
                )
                resolved += 1
            except Exception as exc:  # noqa: BLE001 - confirmation records per-item failures
                self.db.add(
                    DedupeRemoteConfirmation(
                        candidate_id=candidate.id,
                        status="not_found",
                        error_message=str(exc),
                    )
                )
                failed += 1

        self.db.flush()
        self._refresh_group_confidence({candidate.group_id for candidate in candidates})
        self.db.commit()
        return DedupeConfirmationSummary(requested=len(unique_ids), resolved=resolved, failed=failed)

    def _resolve_path_to_id(self, path: str) -> str:
        parts = self._path_parts(path)
        if not parts:
            raise Client115Error("Path is empty")

        current_id = "0"
        for part in parts:
            listing = self.client.list_files(cid=current_id, limit=500, offset=0, show_dir=1)
            matches = [item for item in listing.get("data", []) if item.get("fn") == part]
            if not matches:
                raise Client115Error(f"Path segment is missing: {part}")
            if len(matches) > 1:
                raise Client115Error(f"Path segment is ambiguous: {part}")
            current_id = str(matches[0].get("fid"))
        return current_id

    def _path_parts(self, path: str) -> list[str]:
        if hasattr(self.client, "path_parts_for_display_path"):
            return list(self.client.path_parts_for_display_path(path))
        cleaned = path.strip().strip("/")
        if not cleaned:
            return []
        parts = [part for part in cleaned.split("/") if part]
        if parts and parts[0] == "根目录":
            parts = parts[1:]
        return parts

    def _remote_path(self, remote_file_id: str, fallback_path: str) -> str:
        if hasattr(self.client, "get_full_path"):
            try:
                return str(self.client.get_full_path(remote_file_id))
            except Exception:  # noqa: BLE001 - keep confirmation usable even if path expansion fails
                return fallback_path
        return fallback_path

    def _refresh_group_confidence(self, group_ids: set[int]) -> None:
        for group_id in group_ids:
            group = self.db.get(DedupeGroup, group_id)
            if group is None:
                continue
            candidates = list(
                self.db.scalars(select(DedupeCandidate).where(DedupeCandidate.group_id == group_id)).all()
            )
            latest_confirmations = [_latest_resolved_confirmation(candidate) for candidate in candidates]
            resolved_confirmations = [item for item in latest_confirmations if item is not None]
            if len(resolved_confirmations) < 1:
                continue
            if _has_verified_match(resolved_confirmations):
                group.confidence_level = "verified_duplicate"
            elif group.confidence_level == "filename_suspected":
                group.confidence_level = "high_probability"


def _latest_resolved_confirmation(candidate: DedupeCandidate) -> DedupeRemoteConfirmation | None:
    confirmations = [item for item in candidate.confirmations if item.status == "resolved"]
    if not confirmations:
        return None
    return max(confirmations, key=lambda item: item.id or 0)


def _has_verified_match(confirmations: list[DedupeRemoteConfirmation]) -> bool:
    sha_counts: dict[str, int] = defaultdict(int)
    size_counts: dict[int, int] = defaultdict(int)
    for confirmation in confirmations:
        if confirmation.sha1:
            sha_counts[confirmation.sha1] += 1
        if confirmation.size_bytes is not None:
            size_counts[confirmation.size_bytes] += 1
    return any(count >= 2 for count in sha_counts.values()) or any(count >= 2 for count in size_counts.values())


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
