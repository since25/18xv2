from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.actresses import (
    Actress,
    ActressAlias,
    ActressDeleteBatch,
    ActressDeleteBatchFile,
    ActressDeleteBatchFilm,
    ActressDeleteCandidate,
    ActressMark,
    JellyfinMediaActor,
)
from app.models.background_jobs import BackgroundJob
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.archive_service import ArchiveService
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses.job_runner import refresh_work
from app.services.actresses.names import normalize_actress_name
from app.services.client_115.client import Fake115Client
from app.services.job_runner import JobAlreadyRunning

# 每个测试开始时清掉，避免外部环境里的值影响判断
_CLEARED_ENV = (
    "JELLYFIN_BASE_URL",
    "JELLYFIN_API_KEY",
    "ACTRESS_SOURCE_ROOT",
    "ACTRESS_ORGANIZED_ROOT",
    "ACTRESS_PATH_MAP",
)
_ROUTES = "app.api.routes.actresses"


@pytest.fixture
def strm_root(tmp_path) -> Path:
    return tmp_path / "strm"


@pytest.fixture
def client(db_session, monkeypatch, strm_root):
    """女优功能开启（Jellyfin 扫描开启、115 番号库根目录已配置），Jellyfin 同步和删除根目录未配置。"""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("JELLYFIN_ENABLED", "true")
    monkeypatch.setenv("ACTRESS_ENABLED", "true")
    monkeypatch.setenv("MEDIA_LIBRARY_STRM_ROOTS", str(strm_root))
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    had_client = hasattr(app.state, "client_115")
    previous_client = getattr(app.state, "client_115", None)
    app.state.client_115 = Fake115Client()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        if had_client:
            app.state.client_115 = previous_client
        else:
            del app.state.client_115


def _configure(monkeypatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def _delete_ready(monkeypatch, tmp_path: Path) -> None:
    """配好两个可写根目录，删除就绪。"""
    _configure(
        monkeypatch,
        ACTRESS_SOURCE_ROOT=str(tmp_path / "source"),
        ACTRESS_ORGANIZED_ROOT=str(tmp_path / "organized"),
    )


def _capture_jobs(monkeypatch) -> list[tuple[str, object]]:
    """替换后台执行：只记录提交的（任务编号, 干活函数），不真的起线程。"""
    submitted: list[tuple[str, object]] = []
    monkeypatch.setattr(f"{_ROUTES}.submit_job", lambda job_id, work: submitted.append((job_id, work)))
    return submitted


def _fake_jellyfin(monkeypatch, image: tuple[bytes, str] | None) -> list[str]:
    """替换 Jellyfin 客户端：取图返回给定结果，记录构造和取图的名字。"""
    calls: list[str] = []

    class FakeJellyfinClient:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("init")

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def get_person_image(self, name: str):
            calls.append(name)
            return image

    monkeypatch.setattr(f"{_ROUTES}.JellyfinClient", FakeJellyfinClient)
    return calls


def _add_film(
    db_session,
    root: Path,
    number: str,
    actors: tuple[str, ...],
    *,
    actor_dir: str = "甲",
    jellyfin_item_id: str | None = None,
) -> str:
    """插入一部单段片子（一个 115 STRM 条目和它的 NFO 演员行），返回番号目录。"""
    film_dir = root / actor_dir / number
    item = JellyfinMediaItem(
        source="strm_115",
        path=str(film_dir / f"{number}.strm"),
        active=True,
        jellyfin_item_id=jellyfin_item_id,
        resolve_state="resolved" if jellyfin_item_id else "pending",
    )
    db_session.add(item)
    db_session.flush()
    for position, name in enumerate(actors):
        db_session.add(
            JellyfinMediaActor(
                media_item_id=item.id,
                position=position,
                raw_name=name,
                name_normalized=normalize_actress_name(name),
            )
        )
    db_session.commit()
    return str(film_dir)


def _actress(db_session, name: str, status: str = "none") -> int:
    actress = ArchiveService().ensure_actresses(db_session, [name])[0]
    if status != "none":
        ArchiveService().set_status(db_session, [actress.id], status, source="web")
    return actress.id


def _reconcile(db_session, strm_root: Path) -> None:
    CandidateService().reconcile(db_session, strm_roots=[str(strm_root)], added_by="mark")


def _add_candidate(db_session, film_dir: str, *, selected: bool) -> None:
    db_session.add(ActressDeleteCandidate(film_dir=film_dir, selected=selected, added_by="mark"))
    db_session.commit()


def test_list_filters_and_counts(client, db_session, strm_root):
    black = _actress(db_session, "甲", "blacklist")
    white = _actress(db_session, "乙", "whitelist")
    plain = _actress(db_session, "丙")
    ArchiveService().add_alias(db_session, plain, "丁")
    for actress_id, film_count in ((black, 3), (white, 5), (plain, 1)):
        db_session.get(Actress, actress_id).film_count = film_count
    db_session.commit()
    _add_film(db_session, strm_root, "ABC-001", ("甲",))
    _add_film(db_session, strm_root, "ABC-002", ("甲", "丙"))
    # 乙是白名单，这部受保护，不进清单
    _add_film(db_session, strm_root, "ABC-003", ("甲", "乙"))
    _reconcile(db_session, strm_root)

    response = client.get("/actresses")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["counts"] == {"none": 1, "blacklist": 1, "whitelist": 1}
    # 默认按片数倒序
    assert [item["canonical_name"] for item in body["items"]] == ["乙", "甲", "丙"]
    by_name = {item["canonical_name"]: item for item in body["items"]}
    assert by_name["甲"]["candidate_count"] == 2
    # 丙在清单片里，但不是因为她才删
    assert by_name["丙"]["candidate_count"] == 0
    assert by_name["丙"]["aliases"] == ["丁"]
    assert by_name["乙"]["status"] == "whitelist"

    blacklisted = client.get("/actresses", params={"status": "blacklist"}).json()
    assert [item["id"] for item in blacklisted["items"]] == [black]
    assert blacklisted["total"] == 1
    # 三个计数不受筛选影响
    assert blacklisted["counts"] == body["counts"]

    by_alias = client.get("/actresses", params={"q": " 丁 "}).json()
    assert [item["id"] for item in by_alias["items"]] == [plain]

    page = client.get("/actresses", params={"sort": "name", "page": 2, "page_size": 1}).json()
    assert page["total"] == 3
    assert [item["canonical_name"] for item in page["items"]] == ["乙"]

    assert client.get("/actresses", params={"page_size": 201}).status_code == 422


def test_status_change_returns_candidate_counts(client, db_session, strm_root):
    _add_film(db_session, strm_root, "ABC-001", ("甲", "乙"))
    _add_film(db_session, strm_root, "ABC-002", ("甲",))
    _add_film(db_session, strm_root, "ABC-003", ("乙",), actor_dir="乙")
    black = _actress(db_session, "甲")

    response = client.post(
        "/actresses/status", json={"actress_ids": [black], "status": "blacklist", "source": "web"}
    )

    assert response.status_code == 200
    assert response.json() == {"changed": 1, "candidates_added": 2, "candidates_removed": 0}
    rows = db_session.scalars(select(ActressDeleteCandidate)).all()
    assert len(rows) == 2 and all(row.added_by == "mark" for row in rows)

    response = client.post("/actresses/status", json={"actress_ids": [black], "status": "none", "source": "web"})

    assert response.json() == {"changed": 1, "candidates_added": 0, "candidates_removed": 2}


def test_player_mark_records_source_and_media(client, db_session, strm_root):
    _add_film(db_session, strm_root, "ABC-001", ("甲",))
    item_id = db_session.scalar(select(JellyfinMediaItem.id))
    actress_id = _actress(db_session, "甲")

    response = client.post(
        "/actresses/status",
        json={"actress_ids": [actress_id], "status": "whitelist", "source": "player", "media_item_id": item_id},
    )

    assert response.status_code == 200
    mark = db_session.scalar(select(ActressMark).where(ActressMark.actress_id == actress_id))
    assert (mark.source, mark.media_item_id, mark.to_status) == ("player", item_id, "whitelist")
    detail = client.get(f"/actresses/{actress_id}").json()
    assert [(m["source"], m["media_item_id"]) for m in detail["marks"]] == [("player", item_id)]

    missing_item = client.post(
        "/actresses/status",
        json={"actress_ids": [actress_id], "status": "none", "source": "player", "media_item_id": item_id + 100},
    )
    assert missing_item.status_code == 400
    assert db_session.get(Actress, actress_id).status == "whitelist"

    bad_source = client.post(
        "/actresses/status", json={"actress_ids": [actress_id], "status": "none", "source": "import"}
    )
    assert bad_source.status_code == 422


def test_by_media_lookup_creates_missing_archive_entries(client, db_session, strm_root):
    film_dir = _add_film(db_session, strm_root, "ABC-001", ("甲", "乙"), jellyfin_item_id="jf-1")
    _actress(db_session, "甲", "blacklist")
    _reconcile(db_session, strm_root)

    response = client.get("/actresses/by-media", params={"jellyfin_item_id": "jf-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["film_dir"] == film_dir
    assert body["number"] == "ABC-001"
    assert body["in_candidates"] is True
    assert body["media_item_id"] == db_session.scalar(select(JellyfinMediaItem.id))
    assert [(actor["name"], actor["status"]) for actor in body["actors"]] == [("甲", "blacklist"), ("乙", "none")]
    created = db_session.scalar(select(Actress).where(Actress.canonical_name == "乙"))
    assert created is not None and body["actors"][1]["actress_id"] == created.id

    # 用 STRM 路径查到的是同一部片
    by_path = client.get("/actresses/by-media", params={"path": f"{film_dir}/ABC-001.strm"})
    assert by_path.status_code == 200
    assert by_path.json() == body
    # 用番号目录查时取这部片第一个条目
    by_dir = client.get("/actresses/by-media", params={"path": film_dir})
    assert by_dir.json() == body

    assert client.get("/actresses/by-media", params={"jellyfin_item_id": "jf-unknown"}).status_code == 404
    assert client.get("/actresses/by-media").status_code == 400
    both = client.get("/actresses/by-media", params={"jellyfin_item_id": "jf-1", "path": film_dir})
    assert both.status_code == 400


def test_static_paths_not_shadowed_by_actress_id(client):
    for path in ("/actresses/candidates", "/actresses/kept", "/actresses/delete-batches"):
        assert client.get(path).status_code == 200, path

    assert client.get("/actresses/candidates").json() == {"items": [], "total": 0, "selected": 0}


def test_candidate_select_keep_and_unkeep(client, db_session, strm_root):
    first = _add_film(db_session, strm_root, "ABC-001", ("甲", "乙"))
    second = _add_film(db_session, strm_root, "ABC-002", ("甲",))
    _actress(db_session, "甲", "blacklist")
    _reconcile(db_session, strm_root)

    body = client.get("/actresses/candidates").json()
    assert (body["total"], body["selected"]) == (2, 2)
    item = next(item for item in body["items"] if item["film_dir"] == first)
    assert item["number"] == "ABC-001"
    assert item["black_names"] == ["甲"]
    assert item["other_actors"] == [{"name": "乙", "status": "none"}]
    assert item["remote_state"] == "unchecked"

    selected = client.post("/actresses/candidates/select", json={"film_dirs": [first], "selected": False})
    assert selected.json() == {"count": 1}
    assert client.get("/actresses/candidates").json()["selected"] == 1

    assert client.post("/actresses/candidates/keep", json={"film_dirs": [second]}).json() == {"count": 1}
    kept = client.get("/actresses/kept").json()["items"]
    assert [(row["film_dir"], row["number"]) for row in kept] == [(second, "ABC-002")]
    assert client.get("/actresses/candidates").json()["total"] == 1

    assert client.post("/actresses/kept/remove", json={"film_dirs": [second]}).json() == {"count": 1}
    assert client.get("/actresses/kept").json()["items"] == []
    assert client.get("/actresses/candidates").json()["total"] == 2


def test_check_remote_writes_state_and_limits_batch_size(client, db_session, strm_root):
    film_dir = _add_film(db_session, strm_root, "ABC-001", ("甲",))
    _actress(db_session, "甲", "blacklist")
    _reconcile(db_session, strm_root)

    response = client.post("/actresses/candidates/check-remote", json={"film_dirs": [film_dir]})

    assert response.status_code == 200
    assert response.json() == {"count": 1}
    # 测试里没有 STRM 文件，读不到地址
    assert db_session.scalar(select(ActressDeleteCandidate)).remote_state == "error"

    too_many = [f"/虚构/甲/ABC-{n:03d}" for n in range(51)]
    response = client.post("/actresses/candidates/check-remote", json={"film_dirs": too_many})
    assert response.status_code == 400
    assert "50" in response.json()["detail"]


def _seed_for_switch(db_session) -> dict[str, int]:
    """总开关测试用：两位女优（甲带别名乙）、一部清单里的片、一个失败批次。"""
    actress = _actress(db_session, "甲")
    other = _actress(db_session, "丙")
    alias = ArchiveService().add_alias(db_session, actress, "乙")
    _add_candidate(db_session, "/虚构/甲/ABC-001", selected=True)
    batch = ActressDeleteBatch(status="failed")
    db_session.add(batch)
    db_session.commit()
    return {"actress": actress, "other": other, "alias": alias.id, "batch": batch.id}


def _write_requests(ids: dict[str, int]) -> dict[str, tuple[str, str, dict | None]]:
    film_dir = "/虚构/甲/ABC-001"
    return {
        "by-media": ("GET", "/actresses/by-media?jellyfin_item_id=jf-1", None),
        "status": (
            "POST",
            "/actresses/status",
            {"actress_ids": [ids["actress"]], "status": "blacklist", "source": "web"},
        ),
        "refresh": ("POST", "/actresses/refresh", None),
        "select": ("POST", "/actresses/candidates/select", {"film_dirs": [film_dir], "selected": False}),
        "keep": ("POST", "/actresses/candidates/keep", {"film_dirs": [film_dir]}),
        "check-remote": ("POST", "/actresses/candidates/check-remote", {"film_dirs": [film_dir]}),
        "kept-remove": ("POST", "/actresses/kept/remove", {"film_dirs": [film_dir]}),
        "create-batch": ("POST", "/actresses/delete-batches", {"film_dirs": [film_dir]}),
        "resume": ("POST", f"/actresses/delete-batches/{ids['batch']}/resume", None),
        "add-alias": ("POST", f"/actresses/{ids['actress']}/aliases", {"alias": "丁"}),
        "remove-alias": ("DELETE", f"/actresses/{ids['actress']}/aliases/{ids['alias']}", None),
        "merge": ("POST", f"/actresses/{ids['other']}/merge", {"into_id": ids["actress"]}),
    }


@pytest.mark.parametrize("name", list(_write_requests({"actress": 0, "other": 0, "alias": 0, "batch": 0})))
def test_write_routes_return_409_when_actress_disabled(client, db_session, monkeypatch, tmp_path, name):
    ids = _seed_for_switch(db_session)
    submitted = _capture_jobs(monkeypatch)
    # 只关总开关，删除根目录等其余配置都齐
    _delete_ready(monkeypatch, tmp_path)
    _configure(monkeypatch, ACTRESS_ENABLED="false")
    method, path, body = _write_requests(ids)[name]

    response = client.request(method, path, json=body)

    assert response.status_code == 409, response.text
    assert "女优" in response.json()["detail"]
    assert submitted == []
    assert db_session.scalars(select(BackgroundJob)).all() == []
    assert [batch.id for batch in db_session.scalars(select(ActressDeleteBatch))] == [ids["batch"]]
    assert db_session.get(Actress, ids["other"]) is not None
    assert db_session.get(Actress, ids["actress"]).status == "none"


@pytest.mark.parametrize(
    "path",
    [
        "/actresses",
        "/actresses/{actress}",
        "/actresses/candidates",
        "/actresses/kept",
        "/actresses/delete-batches",
        "/actresses/delete-batches/{batch}",
    ],
)
def test_read_routes_work_when_actress_disabled(client, db_session, monkeypatch, path):
    ids = _seed_for_switch(db_session)
    _configure(monkeypatch, ACTRESS_ENABLED="false")

    response = client.get(path.format(**ids))

    assert response.status_code == 200, response.text


def test_refresh_returns_400_without_strm_roots(client, db_session, monkeypatch):
    submitted = _capture_jobs(monkeypatch)
    monkeypatch.delenv("MEDIA_LIBRARY_STRM_ROOTS")
    get_settings.cache_clear()

    response = client.post("/actresses/refresh")

    assert response.status_code == 400
    assert "根目录" in response.json()["detail"]
    assert db_session.scalars(select(BackgroundJob)).all() == []
    assert submitted == []


def test_refresh_submits_job(client, db_session, monkeypatch):
    submitted = _capture_jobs(monkeypatch)

    response = client.post("/actresses/refresh")

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert submitted == [(job_id, refresh_work)]
    assert db_session.get(BackgroundJob, job_id).job_type == "actress:refresh"
    # 上一个刷新任务还没结束
    assert client.post("/actresses/refresh").status_code == 409


def test_create_batch_returns_409_when_disabled(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    film_dir = "/虚构/甲/ABC-001"
    _add_candidate(db_session, film_dir, selected=True)
    _delete_ready(monkeypatch, tmp_path)
    _configure(monkeypatch, ACTRESS_ENABLED="false")

    assert client.post("/actresses/delete-batches", json={"film_dirs": [film_dir]}).status_code == 409

    # 功能开启但没配 302porn_tv1 的可写根目录：删除未就绪
    _configure(monkeypatch, ACTRESS_ENABLED="true")
    monkeypatch.delenv("ACTRESS_ORGANIZED_ROOT")
    get_settings.cache_clear()

    response = client.post("/actresses/delete-batches", json={"film_dirs": [film_dir]})

    assert response.status_code == 409
    assert db_session.scalars(select(ActressDeleteBatch)).all() == []
    assert submitted == []


def test_create_batch_returns_400_when_nothing_selected(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    _add_candidate(db_session, "/虚构/甲/ABC-001", selected=True)

    response = client.post("/actresses/delete-batches", json={"film_dirs": []})

    assert response.status_code == 400
    assert "没有勾选" in response.json()["detail"]
    assert db_session.scalars(select(ActressDeleteBatch)).all() == []
    assert db_session.scalars(select(BackgroundJob)).all() == []
    assert submitted == []


def test_create_batch_returns_409_when_delete_job_running(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    film_dir = "/虚构/甲/ABC-001"
    _add_candidate(db_session, film_dir, selected=True)
    db_session.add(BackgroundJob(job_id="running-delete", job_type="actress:delete", done=False, stage="删除中"))
    db_session.commit()

    response = client.post("/actresses/delete-batches", json={"film_dirs": [film_dir]})

    assert response.status_code == 409
    # 不留下没人执行的待执行批次
    assert db_session.scalars(select(ActressDeleteBatch)).all() == []
    assert submitted == []


def test_create_batch_uses_only_confirmed_films(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    shown = "/虚构/甲/ABC-001"
    _add_candidate(db_session, shown, selected=True)
    # 网页打开之后，每日任务又往清单里加了一部（默认勾选），网页上没见过
    added_later = "/虚构/甲/ABC-002"
    _add_candidate(db_session, added_later, selected=True)

    response = client.post("/actresses/delete-batches", json={"film_dirs": [shown]})

    assert response.status_code == 202
    body = response.json()
    batch = db_session.get(ActressDeleteBatch, body["batch_id"])
    assert [film.film_dir for film in batch.films] == [shown]
    assert batch.status == "pending"
    assert batch.job_id == body["job_id"]
    assert [job_id for job_id, _work in submitted] == [body["job_id"]]
    assert db_session.get(BackgroundJob, body["job_id"]).job_type == "actress:delete"
    # 没确认的片子留在清单里
    assert added_later in set(db_session.scalars(select(ActressDeleteCandidate.film_dir)))


def test_create_batch_returns_409_when_candidates_changed(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    _add_candidate(db_session, "/虚构/甲/ABC-001", selected=True)

    # ABC-002 在网页打开之后已移出清单
    response = client.post(
        "/actresses/delete-batches", json={"film_dirs": ["/虚构/甲/ABC-001", "/虚构/乙/ABC-002"]}
    )

    assert response.status_code == 409
    assert "清单有变化，请刷新后再确认" in response.json()["detail"]
    assert db_session.scalars(select(ActressDeleteBatch)).all() == []
    assert db_session.scalars(select(BackgroundJob)).all() == []
    assert submitted == []


def test_create_batch_drops_batch_when_delete_job_starts_meanwhile(client, db_session, monkeypatch, tmp_path):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    film_dir = "/虚构/甲/ABC-001"
    _add_candidate(db_session, film_dir, selected=True)

    def job_already_running(_db, job_type, **_kwargs):
        raise JobAlreadyRunning(job_type)

    # 建批次之后、建任务之前，另一个删除任务启动了
    monkeypatch.setattr(f"{_ROUTES}.create_job", job_already_running)

    response = client.post("/actresses/delete-batches", json={"film_dirs": [film_dir]})

    assert response.status_code == 409
    assert db_session.scalars(select(ActressDeleteBatch)).all() == []
    assert submitted == []


@pytest.mark.parametrize(
    ("batch_status", "expected"),
    [("failed", 202), ("interrupted", 202), ("running", 202), ("pending", 400), ("completed", 400)],
)
def test_resume_status_rules(client, db_session, monkeypatch, tmp_path, batch_status, expected):
    submitted = _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    batch = ActressDeleteBatch(status=batch_status)
    db_session.add(batch)
    db_session.commit()

    response = client.post(f"/actresses/delete-batches/{batch.id}/resume")

    assert response.status_code == expected, response.text
    if expected == 202:
        assert response.json() == {"batch_id": batch.id, "job_id": batch.job_id}
        assert [job_id for job_id, _work in submitted] == [batch.job_id]
    else:
        assert batch.job_id is None
        assert submitted == []
        assert db_session.scalars(select(BackgroundJob)).all() == []


def test_resume_rejects_missing_batch_and_running_job(client, db_session, monkeypatch, tmp_path):
    _capture_jobs(monkeypatch)
    _delete_ready(monkeypatch, tmp_path)
    stopped = ActressDeleteBatch(status="interrupted")
    db_session.add(stopped)
    db_session.commit()

    assert client.post("/actresses/delete-batches/9999/resume").status_code == 404
    assert client.post(f"/actresses/delete-batches/{stopped.id}/resume").status_code == 202
    # 这个删除任务还没结束，不能再续跑
    assert client.post(f"/actresses/delete-batches/{stopped.id}/resume").status_code == 409


def test_batch_list_and_detail_tolerate_interrupted_batch(client, db_session):
    batch = ActressDeleteBatch(status="interrupted", note="删除中断：测试", finished_at=datetime.now(UTC))
    film = ActressDeleteBatchFilm(film_dir="/虚构/甲/ABC-001", number="ABC-001", status="failed", error="115 删除失败")
    film.files = [ActressDeleteBatchFile(group="remote_115", target="/虚构/ABC-001.mp4", status="failed", error="失败")]
    batch.films = [film]
    db_session.add(batch)
    db_session.commit()

    listing = client.get("/actresses/delete-batches")

    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["id"] == batch.id
    assert item["status"] == "interrupted"
    assert item["jellyfin_refresh"] is None
    assert item["finished_at"] is not None

    detail = client.get(f"/actresses/delete-batches/{batch.id}")

    assert detail.status_code == 200
    films = detail.json()["films"]
    assert [(row["number"], row["status"], row["error"]) for row in films] == [("ABC-001", "failed", "115 删除失败")]
    assert [(row["group"], row["status"]) for row in films[0]["files"]] == [("remote_115", "failed")]
    assert client.get("/actresses/delete-batches/9999").status_code == 404


def test_alias_changes_rerun_candidates_and_return_detail(client, db_session, strm_root):
    _add_film(db_session, strm_root, "ABC-001", ("戊",), actor_dir="戊")
    black = _actress(db_session, "甲", "blacklist")

    response = client.post(f"/actresses/{black}/aliases", json={"alias": "戊"})

    assert response.status_code == 200
    detail = response.json()
    assert detail["aliases"] == ["戊"]
    assert detail["candidate_count"] == 1
    assert [(film["number"], film["in_candidates"], film["protected"]) for film in detail["films"]] == [
        ("ABC-001", True, False)
    ]
    assert detail["films"][0]["actors"] == [{"name": "戊", "status": "blacklist"}]

    # 详情带别名 id，网页用它调删除接口
    alias_id = db_session.scalar(select(ActressAlias.id))
    assert detail["alias_items"] == [{"id": alias_id, "alias": "戊"}]

    duplicate = client.post(f"/actresses/{black}/aliases", json={"alias": "戊"})
    assert duplicate.status_code == 400

    response = client.delete(f"/actresses/{black}/aliases/{detail['alias_items'][0]['id']}")

    assert response.status_code == 200
    assert response.json()["aliases"] == []
    assert response.json()["alias_items"] == []
    assert response.json()["films"] == []
    assert db_session.scalars(select(ActressDeleteCandidate)).all() == []
    assert client.get("/actresses/9999").status_code == 404


def test_merge_conflict_returns_400(client, db_session):
    black = _actress(db_session, "甲", "blacklist")
    white = _actress(db_session, "乙", "whitelist")
    plain = _actress(db_session, "丙")

    response = client.post(f"/actresses/{black}/merge", json={"into_id": white})

    assert response.status_code == 400
    assert "先改状态" in response.json()["detail"]
    assert db_session.get(Actress, black) is not None

    merged = client.post(f"/actresses/{plain}/merge", json={"into_id": black})

    assert merged.status_code == 200
    assert merged.json()["id"] == black
    assert merged.json()["aliases"] == ["丙"]
    assert db_session.get(Actress, plain) is None


def test_image_returns_404_when_jellyfin_unavailable(client, db_session, monkeypatch):
    actress_id = _actress(db_session, "甲")
    calls = _fake_jellyfin(monkeypatch, None)

    # Jellyfin 没配置：直接 404，不连 Jellyfin
    assert client.get(f"/actresses/{actress_id}/image").status_code == 404
    assert calls == []

    # 配置了但连不上（客户端取不到图返回 None）
    _configure(monkeypatch, JELLYFIN_BASE_URL="http://jellyfin.test", JELLYFIN_API_KEY="test-key")

    assert client.get(f"/actresses/{actress_id}/image").status_code == 404
    assert calls == ["init", "甲"]


def test_image_returns_jellyfin_bytes(client, db_session, monkeypatch):
    actress_id = _actress(db_session, "甲")
    _fake_jellyfin(monkeypatch, (b"image-bytes", "image/jpeg"))
    _configure(monkeypatch, JELLYFIN_BASE_URL="http://jellyfin.test", JELLYFIN_API_KEY="test-key")

    response = client.get(f"/actresses/{actress_id}/image")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert client.get("/actresses/9999/image").status_code == 404
