from __future__ import annotations

from app.services.emby_media_actions.emby_client import build_item_context


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
