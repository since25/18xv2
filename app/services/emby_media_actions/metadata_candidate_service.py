from __future__ import annotations

from datetime import UTC, datetime
import json

from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyMetadataCandidate, EmbyMetadataSnapshot
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

VALID_TARGET_LISTS = {"emby_blacklist", "emby_whitelist"}


class EmbyMetadataCandidateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_candidate(
        self,
        *,
        target_list: str,
        emby_item_id: str,
        title: str,
        nfo_xml: str | None,
        emby_payload: dict,
        actors: list[dict],
        source_path: str | None,
        mapping_id: int | None = None,
    ) -> EmbyMetadataCandidate:
        if target_list not in VALID_TARGET_LISTS:
            raise ValueError("target_list must be emby_blacklist or emby_whitelist")
        snapshot = EmbyMetadataSnapshot(
            emby_item_id=emby_item_id,
            mapping_id=mapping_id,
            snapshot_type="nfo_emby",
            title=title,
            nfo_path=source_path,
            nfo_xml=nfo_xml,
            emby_json=json.dumps(emby_payload, ensure_ascii=False),
            actors_json=json.dumps(actors, ensure_ascii=False),
        )
        self.db.add(snapshot)
        self.db.flush()
        candidate = EmbyMetadataCandidate(
            target_list=target_list,
            emby_item_id=emby_item_id,
            snapshot_id=snapshot.id,
            status="pending",
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def apply_actors(self, *, candidate_id: int, actors: list[str], note: str | None) -> EmbyMetadataCandidate:
        candidate = self.db.get(EmbyMetadataCandidate, candidate_id)
        if candidate is None:
            raise LookupError("metadata candidate not found")
        if candidate.status == "applied":
            raise ValueError("metadata candidate already applied")
        cleaned = [actor.strip() for actor in actors if actor.strip()]
        if not cleaned:
            raise ValueError("at least one actor is required")
        registry = KeywordRegistryService(self.db)
        entry_ids: list[int] = []
        for actor in dict.fromkeys(cleaned):
            normalized_actor = normalize_keyword_text(actor)
            existing = registry.find_entry_by_keyword(normalized_actor)
            if existing is None:
                entry = registry.create_entry(
                    canonical_name=actor,
                    keyword_type=candidate.target_list,
                    note=note,
                    source="emby_media_actions",
                )
            elif existing.keyword_type != candidate.target_list:
                raise ValueError(f"actor {actor} already exists in {existing.keyword_type}")
            else:
                entry = existing
            entry_ids.append(entry.id)
        candidate.selected_actors_json = json.dumps(cleaned, ensure_ascii=False)
        candidate.applied_keyword_entry_ids_json = json.dumps(entry_ids)
        candidate.note = note
        candidate.status = "applied"
        candidate.applied_at = datetime.now(UTC)
        self.db.commit()
        registry.sync_legacy_library()
        self.db.refresh(candidate)
        return candidate
