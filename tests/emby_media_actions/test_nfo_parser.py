from __future__ import annotations

from app.services.emby_media_actions.nfo_parser import parse_nfo_actors


def test_parse_nfo_actors_extracts_names_and_roles() -> None:
    xml = """
    <movie>
      <title>测试电影</title>
      <actor><name>演员A</name><role>角色A</role><tmdbid>101</tmdbid></actor>
      <actor><name>演员B</name></actor>
    </movie>
    """

    actors = parse_nfo_actors(xml)

    assert actors[0].name == "演员A"
    assert actors[0].role == "角色A"
    assert actors[0].provider_ids["tmdb"] == "101"
    assert actors[1].name == "演员B"
