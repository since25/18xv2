from __future__ import annotations

from app.services.emby_media_actions.emby_client import EmbyClient, build_item_context


class StubResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class RecordingHttpGetter:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, str], timeout: float) -> StubResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return StubResponse(self.payload)


def test_build_item_context_for_episode() -> None:
    payload = {
        "Id": "episode-1",
        "Type": "Episode",
        "Name": "第 3 集",
        "SeriesId": "series-1",
        "SeasonId": "season-1",
        "MediaSources": [{"Path": "/mnt/media/a.strm"}],
        "People": [{"Name": "演员A", "Type": "Actor"}],
    }

    context = build_item_context(payload)

    assert context.emby_item_id == "episode-1"
    assert context.item_type == "Episode"
    assert context.series_id == "series-1"
    assert context.primary_path == "/mnt/media/a.strm"
    assert context.actors == [{"name": "演员A", "role": None, "provider_ids": {}}]


def test_build_item_context_uses_top_level_path_when_media_source_path_missing() -> None:
    payload = {
        "Id": "movie-1",
        "Type": "Movie",
        "Name": "电影",
        "Path": "/mnt/media/movie.strm",
        "MediaSources": [],
    }

    context = build_item_context(payload)

    assert context.primary_path == "/mnt/media/movie.strm"


def test_get_item_calls_user_scoped_emby_endpoint() -> None:
    http_getter = RecordingHttpGetter({"Id": "item-1"})
    client = EmbyClient(
        base_url="http://emby.example/",
        api_key="secret",
        user_id="user-1",
        http_getter=http_getter,
    )

    result = client.get_item("item-1")

    assert result == {"Id": "item-1"}
    assert http_getter.calls == [
        {
            "url": "http://emby.example/emby/Users/user-1/Items/item-1",
            "params": {"api_key": "secret", "Fields": "Path,MediaSources,People,ProviderIds"},
            "timeout": 10.0,
        }
    ]


def test_find_items_by_title_calls_user_scoped_emby_endpoint() -> None:
    http_getter = RecordingHttpGetter({"Items": [{"Id": "item-1"}]})
    client = EmbyClient(
        base_url="http://emby.example/",
        api_key="secret",
        user_id="user-1",
        http_getter=http_getter,
    )

    result = client.find_items_by_title("电影")

    assert result == [{"Id": "item-1"}]
    assert http_getter.calls == [
        {
            "url": "http://emby.example/emby/Users/user-1/Items",
            "params": {
                "api_key": "secret",
                "SearchTerm": "电影",
                "Recursive": "true",
                "Fields": "Path,MediaSources,People,ProviderIds",
            },
            "timeout": 10.0,
        }
    ]
