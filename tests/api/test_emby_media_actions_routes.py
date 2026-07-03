from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import emby_media_actions as _emby_media_actions  # noqa: F401
from app.models import keywords as _keywords  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMetadataSnapshot
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService


class FakeEmbyClient:
    def __init__(self, items: list[dict], title_responses: dict[str, list[dict]] | None = None) -> None:
        self.items = items
        self.title_responses = title_responses
        self.get_item_calls: list[str] = []
        self.find_items_by_title_calls: list[str] = []

    def get_item(self, item_id: str) -> dict:
        self.get_item_calls.append(item_id)
        for item in self.items:
            if item.get("Id") == item_id:
                return item
        raise LookupError(item_id)

    def find_items_by_title(self, title: str) -> list[dict]:
        self.find_items_by_title_calls.append(title)
        if self.title_responses is not None:
            return self.title_responses.get(title, [])
        return self.items


@pytest.fixture
def api_context(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_STRM_ROOTS", str(tmp_path))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_SOURCE_ROOTS", str(tmp_path / "source"))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS", str(tmp_path / "organized"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api import deps

    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    fake_115 = Fake115Client()
    _main.app.dependency_overrides[deps.get_db] = override_get_db
    _main.app.state.client_115 = fake_115
    if hasattr(_main.app.state, "emby_client"):
        delattr(_main.app.state, "emby_client")
    try:
        yield SimpleNamespace(
            client=TestClient(_main.app, raise_server_exceptions=False),
            session_factory=Factory,
            fake_115=fake_115,
            tmp_path=tmp_path,
        )
    finally:
        _main.app.dependency_overrides.clear()
        if hasattr(_main.app.state, "emby_client"):
            delattr(_main.app.state, "emby_client")
        get_settings.cache_clear()
        engine.dispose()


@pytest.fixture
def client(api_context):
    return api_context.client


def _snapshot(api_context, snapshot_id: int) -> EmbyMetadataSnapshot:
    with api_context.session_factory() as db:
        snapshot = db.get(EmbyMetadataSnapshot, snapshot_id)
        assert snapshot is not None
        return snapshot


def _add_remote_node(fake_115: Fake115Client, file_id: str) -> None:
    fake_115.add_node(
        NodePayload(
            id=file_id,
            name=f"{file_id}.mkv",
            path=f"/{file_id}.mkv",
            parent_id="0",
            is_file=True,
        )
    )


def _draft_delete_plan(api_context) -> tuple[int, Path, Path]:
    source_root = api_context.tmp_path / "source"
    organized_root = api_context.tmp_path / "organized"
    source_root.mkdir()
    organized_root.mkdir()
    source_file = source_root / "item-1.source.strm"
    organized_file = organized_root / "item-1.organized.strm"
    source_file.write_text("url", encoding="utf-8")
    organized_file.write_text("url", encoding="utf-8")
    _add_remote_node(api_context.fake_115, "remote-1")
    with api_context.session_factory() as db:
        mapping = _emby_media_actions.EmbyMediaMapping(
            emby_item_id="item-1",
            emby_item_type="Movie",
            emby_title="测试电影",
            alist_url="http://example.test/d/115_OPEN/remote-1.mkv",
            alist_mount_name="115_OPEN",
            remote_provider="115",
            remote_path="/remote-1.mkv",
            remote_file_id="remote-1",
        )
        mapping.paths.extend(
            [
                _emby_media_actions.EmbyMediaMappingPath(
                    path_role="source_strm",
                    path=str(source_file),
                    root_name="source",
                    root_path=str(source_root),
                ),
                _emby_media_actions.EmbyMediaMappingPath(
                    path_role="organized_strm",
                    path=str(organized_file),
                    root_name="organized",
                    root_path=str(organized_root),
                ),
            ]
        )
        db.add(mapping)
        db.commit()
        plan = EmbyDeletePlanService(
            db,
            client_115=api_context.fake_115,
            allowed_roots=[str(source_root), str(organized_root)],
        ).create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="route_test")
        return plan.id, source_file, organized_file


def test_metadata_candidate_apply_route(client: TestClient) -> None:
    created = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": "/media/a.strm",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "source": "api",
            "nfo_xml": "<movie><actor><name>演员A</name></actor></movie>",
            "actors": [{"name": "演员A", "role": None, "provider_ids": {}}],
        },
    )

    assert created.status_code == 200
    candidate_id = created.json()["metadata_candidate"]["id"]

    applied = client.post(
        f"/emby-media-actions/metadata-candidates/{candidate_id}/apply",
        json={"actors": ["演员A"], "note": "确认"},
    )

    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"


def test_metadata_candidate_detail_includes_snapshot_actor_choices(client: TestClient) -> None:
    created = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": "/media/a.strm",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "source": "api",
            "actors": [
                {"name": "演员A", "role": "主角", "provider_ids": {"Tmdb": "101"}},
                {"name": "演员B", "role": None, "provider_ids": {}},
            ],
        },
    )
    assert created.status_code == 200
    candidate_id = created.json()["metadata_candidate"]["id"]

    detail = client.get(f"/emby-media-actions/metadata-candidates/{candidate_id}")

    assert detail.status_code == 200
    data = detail.json()
    assert data["snapshot_title"] == "测试电影"
    assert data["snapshot_nfo_path"] is None
    assert data["snapshot_actors"] == [
        {"name": "演员A", "role": "主角", "provider_ids": {"Tmdb": "101"}},
        {"name": "演员B", "role": None, "provider_ids": {}},
    ]


def test_metadata_candidate_intake_preserves_full_emby_snapshot(api_context) -> None:
    playback_path = "/media/playback/movie.strm"
    nfo_path = str(api_context.tmp_path / "source" / "movie.nfo")

    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": playback_path,
            "nfo_path": nfo_path,
            "title": "测试剧集",
            "emby_item_id": "episode-1",
            "emby_payload": {
                "Id": "episode-1",
                "Name": "测试剧集",
                "ProviderIds": {"Tmdb": "123", "Imdb": "tt123"},
                "SeriesId": "series-1",
                "SeasonId": "season-1",
                "ParentIndexNumber": 1,
                "IndexNumber": 2,
            },
            "actors": [{"name": "演员A", "role": None, "provider_ids": {}}],
        },
    )

    assert created.status_code == 200
    snapshot = _snapshot(api_context, created.json()["metadata_candidate"]["snapshot_id"])
    emby_json = json.loads(snapshot.emby_json)
    assert emby_json["ProviderIds"] == {"Tmdb": "123", "Imdb": "tt123"}
    assert emby_json["SeriesId"] == "series-1"
    assert emby_json["SeasonId"] == "season-1"
    assert snapshot.nfo_path == nfo_path
    assert snapshot.nfo_path != playback_path


def test_metadata_candidate_intake_uses_minimal_snapshot_and_null_nfo_path_when_absent(api_context) -> None:
    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_whitelist",
            "path": "/media/playback/movie.strm",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "source": "api",
            "actors": [{"name": "演员A", "role": None, "provider_ids": {}}],
        },
    )

    assert created.status_code == 200
    snapshot = _snapshot(api_context, created.json()["metadata_candidate"]["snapshot_id"])
    assert json.loads(snapshot.emby_json) == {"Id": "item-1", "Name": "测试电影"}
    assert snapshot.nfo_path is None


@pytest.mark.parametrize(
    ("action", "target_list"),
    [
        ("metadata_blacklist", "emby_blacklist"),
        ("metadata_whitelist", "emby_whitelist"),
    ],
)
def test_shortcut_metadata_intake_preserves_minimal_snapshot_without_resolved_emby_context(
    api_context,
    action: str,
    target_list: str,
) -> None:
    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": action,
            "path": "/media/playback/shortcut.strm",
            "title": "快捷指令电影",
            "emby_item_id": "shortcut-item-1",
            "source": "shortcut",
        },
    )

    assert created.status_code == 200
    candidate = created.json()["metadata_candidate"]
    assert candidate["target_list"] == target_list
    snapshot = _snapshot(api_context, candidate["snapshot_id"])
    assert snapshot.emby_item_id == "shortcut-item-1"
    assert json.loads(snapshot.emby_json) == {"Id": "shortcut-item-1", "Name": "快捷指令电影"}


def test_metadata_whitelist_intake_omitted_source_preserves_minimal_snapshot_without_resolved_emby_context(api_context) -> None:
    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_whitelist",
            "path": "/media/playback/api-default.strm",
            "title": "接口默认电影",
            "emby_item_id": "api-default-item-1",
        },
    )

    assert created.status_code == 200
    snapshot = _snapshot(api_context, created.json()["metadata_candidate"]["snapshot_id"])
    assert snapshot.emby_item_id == "api-default-item-1"
    assert json.loads(snapshot.emby_json) == {"Id": "api-default-item-1", "Name": "接口默认电影"}


def test_metadata_candidate_intake_resolves_path_title_context_from_emby_client(api_context) -> None:
    playback_path = str(api_context.tmp_path / "source" / "s01e03.strm")
    emby_payload = {
        "Id": "episode-3",
        "Name": "第三集",
        "Type": "Episode",
        "Path": playback_path,
        "SeriesId": "series-1",
        "SeasonId": "season-1",
        "ProviderIds": {"Tvdb": "333"},
        "People": [
            {"Name": "演员A", "Type": "Actor", "Role": "主角", "ProviderIds": {"Tmdb": "101"}},
            {"Name": "导演A", "Type": "Director"},
        ],
    }
    api_context.client.app.state.emby_client = FakeEmbyClient([emby_payload])

    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": playback_path,
            "title": "第三集",
            "source": "iina_lua",
        },
    )

    assert created.status_code == 200
    snapshot = _snapshot(api_context, created.json()["metadata_candidate"]["snapshot_id"])
    assert snapshot.emby_item_id == "episode-3"
    assert json.loads(snapshot.emby_json) == emby_payload
    assert json.loads(snapshot.actors_json) == [{"name": "演员A", "role": "主角", "provider_ids": {"Tmdb": "101"}}]


def test_iina_metadata_intake_resolves_filename_title_with_stem_candidate(api_context) -> None:
    playback_path = str(api_context.tmp_path / "source" / "s01e03.strm")
    emby_payload = {
        "Id": "episode-3",
        "Name": "第三集",
        "Type": "Episode",
        "Path": playback_path,
        "SeriesId": "series-1",
        "SeasonId": "season-1",
        "ProviderIds": {"Tvdb": "333"},
        "People": [{"Name": "演员A", "Type": "Actor", "Role": "主角", "ProviderIds": {"Tmdb": "101"}}],
    }
    emby_client = FakeEmbyClient([], title_responses={"s01e03": [emby_payload]})
    api_context.client.app.state.emby_client = emby_client

    created = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": playback_path,
            "title": "s01e03.strm",
            "source": "iina_lua",
        },
    )

    assert created.status_code == 200
    assert emby_client.find_items_by_title_calls == ["s01e03.strm", "s01e03"]
    snapshot = _snapshot(api_context, created.json()["metadata_candidate"]["snapshot_id"])
    assert snapshot.emby_item_id == "episode-3"
    assert json.loads(snapshot.emby_json) == emby_payload


def test_iina_metadata_intake_without_payload_or_resolvable_emby_client_returns_400(api_context) -> None:
    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": "/media/playback/movie.strm",
            "title": "测试电影",
            "source": "iina_lua",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "emby_payload or resolvable Emby item is required"


def test_metadata_candidate_intake_rejects_malformed_nfo_xml(client: TestClient) -> None:
    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "source": "api",
            "nfo_xml": "<movie><actor><name>演员A</name></actor>",
        },
    )

    assert response.status_code == 400
    assert "nfo_xml" in response.json()["detail"]


@pytest.mark.parametrize(
    ("emby_payload", "title"),
    [
        pytest.param({"Name": "bad-no-id"}, "bad-no-id", id="missing-id"),
        pytest.param({}, "empty-payload", id="empty-payload"),
    ],
)
def test_metadata_candidate_intake_rejects_invalid_emby_payload(client: TestClient, emby_payload: dict, title: str) -> None:
    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "title": title,
            "emby_payload": emby_payload,
        },
    )

    assert response.status_code == 400
    assert "emby_payload" in response.json()["detail"]


def test_delete_plan_intake_requires_emby_item_id(client: TestClient) -> None:
    response = client.post("/emby-media-actions/intake", json={"action": "delete_plan"})

    assert response.status_code == 400
    assert response.json()["detail"] == "emby_item_id is required"


def test_delete_plan_intake_rejects_malformed_stream_url(client: TestClient) -> None:
    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": "http://example.test/not-alist/a.mkv",
            "title": "测试电影",
            "emby_item_id": "item-1",
        },
    )

    assert response.status_code == 400
    assert "stream URL" in response.json()["detail"]


@pytest.mark.parametrize(
    ("emby_payload", "title"),
    [
        pytest.param({"Name": "bad-no-id"}, "bad-no-id", id="missing-id"),
        pytest.param({}, "empty-payload", id="empty-payload"),
    ],
)
def test_delete_plan_intake_rejects_invalid_emby_payload(client: TestClient, emby_payload: dict, title: str) -> None:
    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/bad-no-id.mkv",
            "title": title,
            "emby_item_id": "bad-no-id",
            "emby_payload": emby_payload,
        },
    )

    assert response.status_code == 400
    assert "emby_payload" in response.json()["detail"]


def test_delete_plan_intake_resolves_url_and_persists_remote_file_id(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv"
    (source / "a.strm").write_text(url, encoding="utf-8")
    (organized / "a.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-1", name="a.mkv", path="/电影/a.mkv", parent_id="0", is_file=True))

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "测试电影",
            "emby_item_id": "item-1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["status"] == "draft"
    assert data["delete_plan"]["total_items"] == 3
    assert data["delete_plan"]["scope"] == "movie"
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="item-1").one()
        assert mapping.remote_file_id == "remote-1"
        assert mapping.emby_item_type == "Unknown"


def test_delete_plan_intake_reads_url_from_strm_path(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/path-only.mkv"
    strm_path = source / "path-only.strm"
    strm_path.write_text(url, encoding="utf-8")
    (organized / "path-only.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-2", name="path-only.mkv", path="/电影/path-only.mkv", parent_id="0", is_file=True))

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "path": str(strm_path),
            "title": "测试电影",
            "emby_item_id": "item-path",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["status"] == "draft"
    assert data["delete_plan"]["total_items"] == 3
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="item-path").one()
        assert mapping.remote_file_id == "remote-2"
        assert mapping.alist_url == url


def test_delete_plan_intake_uses_episode_scope_and_type_from_emby_payload(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E5%89%A7%E9%9B%86/s01e01.mkv"
    (source / "s01e01.strm").write_text(url, encoding="utf-8")
    (organized / "s01e01.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-episode-1", name="s01e01.mkv", path="/剧集/s01e01.mkv", parent_id="0", is_file=True))

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "第一集",
            "emby_item_id": "episode-1",
            "emby_payload": {"Id": "episode-1", "Name": "第一集", "Type": "Episode"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["scope"] == "episode"
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="episode-1").one()
        assert mapping.emby_item_type == "Episode"
        assert mapping.remote_file_id == "remote-episode-1"


def test_delete_plan_intake_persists_episode_hierarchy_ids_for_broader_scopes(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E5%89%A7%E9%9B%86/s01e02.mkv"
    (source / "s01e02.strm").write_text(url, encoding="utf-8")
    (organized / "s01e02.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-episode-2", name="s01e02.mkv", path="/剧集/s01e02.mkv", parent_id="0", is_file=True))

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "第二集",
            "emby_item_id": "episode-2",
            "emby_payload": {
                "Id": "episode-2",
                "Name": "第二集",
                "Type": "Episode",
                "SeriesId": "series-1",
                "SeasonId": "season-1",
            },
        },
    )

    assert response.status_code == 200
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="episode-2").one()
        assert mapping.emby_series_id == "series-1"
        assert mapping.emby_season_id == "season-1"
        assert mapping.emby_episode_id == "episode-2"

        service = EmbyDeletePlanService(
            db,
            client_115=api_context.fake_115,
            allowed_roots=[str(source), str(organized)],
        )
        season_plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="season", source="route_test")
        series_plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="series", source="route_test")

        assert season_plan.status == "draft"
        assert season_plan.scope == "season"
        assert series_plan.status == "draft"
        assert series_plan.scope == "series"


def test_delete_plan_scope_route_creates_new_draft_plan_for_season(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    created_mapping_ids: list[int] = []
    for index in (1, 2):
        source_file = source / f"s01e{index:02d}.strm"
        organized_file = organized / f"s01e{index:02d}.strm"
        source_file.write_text("url", encoding="utf-8")
        organized_file.write_text("url", encoding="utf-8")
        _add_remote_node(api_context.fake_115, f"remote-season-{index}")
        with api_context.session_factory() as db:
            mapping = _emby_media_actions.EmbyMediaMapping(
                emby_item_id=f"episode-{index}",
                emby_item_type="Episode",
                emby_title=f"第 {index} 集",
                emby_series_id="series-1",
                emby_season_id="season-1",
                emby_episode_id=f"episode-{index}",
                alist_url=f"http://example.test/d/115_OPEN/s01e{index:02d}.mkv",
                alist_mount_name="115_OPEN",
                remote_provider="115",
                remote_path=f"/剧集/s01e{index:02d}.mkv",
                remote_file_id=f"remote-season-{index}",
            )
            mapping.paths.extend(
                [
                    _emby_media_actions.EmbyMediaMappingPath(
                        path_role="source_strm",
                        path=str(source_file),
                        root_name="source",
                        root_path=str(source),
                    ),
                    _emby_media_actions.EmbyMediaMappingPath(
                        path_role="organized_strm",
                        path=str(organized_file),
                        root_name="organized",
                        root_path=str(organized),
                    ),
                ]
            )
            db.add(mapping)
            db.commit()
            created_mapping_ids.append(mapping.id)

    with api_context.session_factory() as db:
        first_plan = EmbyDeletePlanService(
            db,
            client_115=api_context.fake_115,
            allowed_roots=[str(source), str(organized)],
        ).create_plan_from_mapping(mapping_id=created_mapping_ids[0], scope="episode", source="route_test")
        first_plan_id = first_plan.id

    response = api_context.client.post(f"/emby-media-actions/delete-plans/{first_plan_id}/scope", json={"scope": "season"})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] != first_plan_id
    assert data["scope"] == "season"
    assert data["status"] == "draft"
    assert data["total_items"] == 6
    with api_context.session_factory() as db:
        assert db.get(EmbyDeletePlan, first_plan_id).status == "draft"
        assert all(node_id in api_context.fake_115.nodes for node_id in ("remote-season-1", "remote-season-2"))


def test_delete_plan_path_title_intake_resolves_episode_context_from_emby_client(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E5%89%A7%E9%9B%86/s01e04.mkv"
    strm_path = source / "s01e04.strm"
    strm_path.write_text(url, encoding="utf-8")
    (organized / "s01e04.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-episode-4", name="s01e04.mkv", path="/剧集/s01e04.mkv", parent_id="0", is_file=True))
    api_context.client.app.state.emby_client = FakeEmbyClient(
        [
            {
                "Id": "episode-4",
                "Name": "第四集",
                "Type": "Episode",
                "SeriesId": "series-1",
                "SeasonId": "season-1",
                "MediaSources": [{"Path": str(strm_path)}],
            }
        ]
    )

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "path": str(strm_path),
            "title": "第四集",
            "source": "iina_lua",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["emby_item_id"] == "episode-4"
    assert data["delete_plan"]["scope"] == "episode"
    assert data["delete_plan"]["total_items"] == 3
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="episode-4").one()
        assert mapping.emby_item_type == "Episode"
        assert mapping.emby_title == "第四集"
        assert mapping.emby_series_id == "series-1"
        assert mapping.emby_season_id == "season-1"
        assert mapping.emby_episode_id == "episode-4"
        assert mapping.remote_file_id == "remote-episode-4"
        assert mapping.alist_url == url


def test_delete_plan_intake_is_idempotent_for_same_item_and_url(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/repeat.mkv"
    (source / "repeat.strm").write_text(url, encoding="utf-8")
    (organized / "repeat.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-repeat", name="repeat.mkv", path="/电影/repeat.mkv", parent_id="0", is_file=True))
    payload = {
        "action": "delete_plan",
        "url": url,
        "title": "重复电影",
        "emby_item_id": "movie-repeat",
        "emby_payload": {"Id": "movie-repeat", "Name": "重复电影", "Type": "Movie"},
    }

    first = api_context.client.post("/emby-media-actions/intake", json=payload)
    second = api_context.client.post("/emby-media-actions/intake", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["delete_plan"]["status"] == "draft"
    assert second.json()["delete_plan"]["status"] == "draft"
    with api_context.session_factory() as db:
        mappings = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="movie-repeat", alist_url=url).all()
        assert len(mappings) == 1
        assert mappings[0].remote_file_id == "remote-repeat"
        assert len(mappings[0].paths) == 2


def test_delete_plan_intake_deduplicates_overlapping_strm_root_matches(api_context, monkeypatch) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_STRM_ROOTS", f"{api_context.tmp_path},{source}")
    from app.core.config import get_settings
    get_settings.cache_clear()

    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/overlap.mkv"
    source_path = source / "overlap.strm"
    source_path.write_text(url, encoding="utf-8")
    organized_path = organized / "overlap.strm"
    organized_path.write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-overlap", name="overlap.mkv", path="/电影/overlap.mkv", parent_id="0", is_file=True))

    response = api_context.client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "重叠根目录电影",
            "emby_item_id": "movie-overlap",
        },
    )

    assert response.status_code == 200
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="movie-overlap").one()
        persisted_paths = [path.path for path in mapping.paths]
        assert sorted(persisted_paths) == sorted({str(source_path), str(organized_path)})


def test_delete_plan_intake_preserves_existing_remote_file_id_when_refresh_resolution_fails(api_context) -> None:
    source = api_context.tmp_path / "source"
    organized = api_context.tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/preserve.mkv"
    (source / "preserve.strm").write_text(url, encoding="utf-8")
    (organized / "preserve.strm").write_text(url, encoding="utf-8")
    api_context.fake_115.add_node(NodePayload(id="remote-preserve", name="preserve.mkv", path="/电影/preserve.mkv", parent_id="0", is_file=True))
    payload = {
        "action": "delete_plan",
        "url": url,
        "title": "保留远端 ID",
        "emby_item_id": "movie-preserve",
    }

    first = api_context.client.post("/emby-media-actions/intake", json=payload)
    del api_context.fake_115.nodes["remote-preserve"]
    second = api_context.client.post("/emby-media-actions/intake", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["delete_plan"]["total_items"] == 3
    with api_context.session_factory() as db:
        mapping = db.query(_emby_media_actions.EmbyMediaMapping).filter_by(emby_item_id="movie-preserve", alist_url=url).one()
        assert mapping.remote_file_id == "remote-preserve"


def test_delete_plan_intake_resolves_strm_and_creates_plan(client: TestClient, tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    organized = tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv"
    (source / "a.strm").write_text(url, encoding="utf-8")
    (organized / "a.strm").write_text(url, encoding="utf-8")

    from app.services.client_115.schemas import NodePayload
    fake = client.app.state.client_115
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/电影/a.mkv", parent_id="0", is_file=True))

    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "测试电影",
            "emby_item_id": "item-1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["status"] == "draft"
    assert data["delete_plan"]["total_items"] == 3


def test_confirm_delete_plan_requires_true(api_context) -> None:
    plan_id, source_file, organized_file = _draft_delete_plan(api_context)

    response = api_context.client.post(f"/emby-media-actions/delete-plans/{plan_id}/confirm", json={"confirm": False})

    assert response.status_code == 400
    assert response.json()["detail"] == "confirm must be true"
    assert source_file.exists()
    assert organized_file.exists()
    assert "remote-1" in api_context.fake_115.nodes


def test_unknown_delete_plan_and_metadata_candidate_ids_return_404(client: TestClient) -> None:
    delete_plan = client.get("/emby-media-actions/delete-plans/999")
    confirm_plan = client.post("/emby-media-actions/delete-plans/999/confirm", json={"confirm": True})
    metadata_candidate = client.get("/emby-media-actions/metadata-candidates/999")
    apply_candidate = client.post("/emby-media-actions/metadata-candidates/999/apply", json={"actors": ["演员A"]})

    assert delete_plan.status_code == 404
    assert confirm_plan.status_code == 404
    assert metadata_candidate.status_code == 404
    assert apply_candidate.status_code == 404


def test_confirm_delete_plan_route_executes_draft_plan_with_configured_safety_roots(api_context) -> None:
    plan_id, source_file, organized_file = _draft_delete_plan(api_context)

    response = api_context.client.post(f"/emby-media-actions/delete-plans/{plan_id}/confirm", json={"confirm": True})

    assert response.status_code == 200
    assert response.json() == {"plan_id": plan_id, "total": 3, "deleted": 3, "failed": 0, "blocked": 0}
    assert not source_file.exists()
    assert not organized_file.exists()
    assert "remote-1" not in api_context.fake_115.nodes
    with api_context.session_factory() as db:
        plan = db.get(EmbyDeletePlan, plan_id)
        assert plan is not None
        assert plan.status == "completed"
