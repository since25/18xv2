from __future__ import annotations

from datetime import UTC, datetime
import json

from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyMetadataCandidate, EmbyMetadataSnapshot
from app.models.keywords import KeywordAlias, KeywordEntry, KeywordOperationLog
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
        unique_actor_pairs: list[tuple[str, str]] = []
        seen_normalized_actors: set[str] = set()
        for actor in cleaned:
            normalized_actor = normalize_keyword_text(actor)
            if normalized_actor in seen_normalized_actors:
                continue
            seen_normalized_actors.add(normalized_actor)
            unique_actor_pairs.append((actor, normalized_actor))
        registry = KeywordRegistryService(self.db)
        entries_by_actor: list[tuple[str, str, KeywordEntry | None]] = []
        for actor, normalized_actor in unique_actor_pairs:
            existing = registry.find_entry_by_keyword(normalized_actor)
            if existing is not None and existing.keyword_type != candidate.target_list:
                raise ValueError(f"actor {actor} already exists in {existing.keyword_type}")
            entries_by_actor.append((actor, normalized_actor, existing))

        entry_ids: list[int] = []
        selected_actors: list[str] = []
        for actor, normalized_actor, existing in entries_by_actor:
            if existing is None:
                entry = KeywordEntry(
                    canonical_name=actor,
                    canonical_name_normalized=normalized_actor,
                    keyword_type=candidate.target_list,
                    note=note,
                )
                self.db.add(entry)
                self.db.flush()
                self.db.add(
                    KeywordAlias(
                        keyword_entry_id=entry.id,
                        alias=entry.canonical_name,
                        alias_normalized=normalized_actor,
                        source="canonical",
                        note="Auto-created from canonical name.",
                    )
                )
                self.db.add(
                    KeywordOperationLog(
                        action="create_entry",
                        keyword_entry_id=entry.id,
                        detail=json.dumps(
                            {
                                "canonical_name": entry.canonical_name,
                                "keyword_type": entry.keyword_type,
                                "aliases": [],
                                "source": "emby_media_actions",
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            else:
                entry = existing
            entry_ids.append(entry.id)
            selected_actors.append(actor)
        candidate.selected_actors_json = json.dumps(selected_actors, ensure_ascii=False)
        candidate.applied_keyword_entry_ids_json = json.dumps(entry_ids)
        candidate.note = note
        candidate.status = "applied"
        candidate.applied_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate
