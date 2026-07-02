from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class HttpGetter(Protocol):
    def get(self, url: str, *, params: dict[str, str], timeout: float) -> httpx.Response:
        ...


@dataclass(frozen=True, slots=True)
class EmbyItemContext:
    emby_item_id: str
    item_type: str
    title: str
    series_id: str | None
    season_id: str | None
    primary_path: str | None
    media_sources: list[dict]
    actors: list[dict[str, object]]
    raw: dict


def build_item_context(payload: dict) -> EmbyItemContext:
    media_sources = list(payload.get("MediaSources") or [])
    primary_path = None
    if media_sources:
        primary_path = media_sources[0].get("Path") or None
    if not primary_path:
        primary_path = payload.get("Path")
    actors = []
    for person in payload.get("People") or []:
        if person.get("Type") != "Actor":
            continue
        actors.append(
            {
                "name": person.get("Name"),
                "role": person.get("Role"),
                "provider_ids": person.get("ProviderIds") or {},
            }
        )
    return EmbyItemContext(
        emby_item_id=str(payload["Id"]),
        item_type=str(payload.get("Type") or "Unknown"),
        title=str(payload.get("Name") or ""),
        series_id=payload.get("SeriesId"),
        season_id=payload.get("SeasonId"),
        primary_path=primary_path,
        media_sources=media_sources,
        actors=actors,
        raw=payload,
    )


class EmbyClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        user_id: str,
        http_getter: HttpGetter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.http_getter = http_getter or httpx

    def get_item(self, item_id: str) -> dict:
        response = self.http_getter.get(
            f"{self.base_url}/emby/Users/{self.user_id}/Items/{item_id}",
            params={"api_key": self.api_key, "Fields": "Path,MediaSources,People,ProviderIds"},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    def find_items_by_title(self, title: str) -> list[dict]:
        response = self.http_getter.get(
            f"{self.base_url}/emby/Users/{self.user_id}/Items",
            params={
                "api_key": self.api_key,
                "SearchTerm": title,
                "Recursive": "true",
                "Fields": "Path,MediaSources,People,ProviderIds",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("Items") or [])
