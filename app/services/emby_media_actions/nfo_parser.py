from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class ParsedActor:
    name: str
    role: str | None
    provider_ids: dict[str, str]


def parse_nfo_actors(xml_text: str) -> list[ParsedActor]:
    root = ET.fromstring(xml_text)
    actors: list[ParsedActor] = []
    for actor in root.findall(".//actor"):
        name = (actor.findtext("name") or "").strip()
        if not name:
            continue
        provider_ids: dict[str, str] = {}
        tmdb_id = (actor.findtext("tmdbid") or "").strip()
        if tmdb_id:
            provider_ids["tmdb"] = tmdb_id
        imdb_id = (actor.findtext("imdbid") or "").strip()
        if imdb_id:
            provider_ids["imdb"] = imdb_id
        actors.append(
            ParsedActor(
                name=name,
                role=(actor.findtext("role") or "").strip() or None,
                provider_ids=provider_ids,
            )
        )
    return actors
