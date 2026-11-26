from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.actresses import Actress, ActressAlias
from app.services.actresses.avatar_service import AvatarService
from app.services.actresses.gfriends import GfriendsError
from app.services.actresses.names import normalize_actress_name
from app.services.jellyfin.client import JellyfinError

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


class _Index:
    """名字 → Gfriends 相对路径的桩。"""

    def __init__(self, hits: dict[str, str], used_name_map: bool = True) -> None:
        self.hits = hits
        self.used_name_map = used_name_map
        self.queries: list[list[str]] = []

    def find(self, names: list[str]) -> str | None:
        self.queries.append(list(names))
        return next((self.hits[name] for name in names if name in self.hits), None)


class _Client:
    """Jellyfin 桩：persons 是 名字 → (人物 id, 是否已有主图)。"""

    def __init__(self, persons: dict[str, tuple[str, bool]], upload_error: Exception | None = None) -> None:
        self.persons = persons
        self.upload_error = upload_error
        self.uploads: list[tuple[str, bytes, str]] = []

    def get_person(self, name: str):
        if name not in self.persons:
            return None
        person_id, has_primary = self.persons[name]
        return {"id": person_id, "has_primary": has_primary}

    def upload_person_image(self, person_id: str, content: bytes, content_type: str) -> None:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((person_id, content, content_type))


class _Fetch:
    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.errors = errors or {}
        self.urls: list[str] = []

    def __call__(self, url: str) -> tuple[bytes, str]:
        self.urls.append(url)
        for key, error in self.errors.items():
            if key in url:
                raise error
        return b"img:" + url.encode(), "image/jpeg"


def _actress(db, name: str, *, film_count: int = 1, aliases: tuple[str, ...] = (), **fields) -> Actress:
    actress = Actress(canonical_name=name, canonical_name_normalized=normalize_actress_name(name), film_count=film_count)
    for key, value in fields.items():
        setattr(actress, key, value)
    for alias in aliases:
        actress.aliases.append(ActressAlias(alias=alias, alias_normalized=normalize_actress_name(alias)))
    db.add(actress)
    db.commit()
    return actress


def _run(db, *, index, client, fetch=None, limit=300, actress_ids=None, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return AvatarService().run(
        db,
        index=index,
        client=client,
        fetch_image=fetch or _Fetch(),
        now=NOW,
        limit=limit,
        actress_ids=actress_ids,
        sleep=sleeps.append,
    )


def test_uploads_to_persons_without_primary(db_session):
    actress = _actress(db_session, "甲", aliases=("乙",))
    client = _Client({"甲": ("p-甲", True), "乙": ("p-乙", False)})
    fetch = _Fetch()

    summary = _run(db_session, index=_Index({"甲": "a-源/甲.jpg"}), client=client, fetch=fetch)

    assert summary["uploaded"] == 1 and summary["processed"] == 1
    assert [person_id for person_id, _, _ in client.uploads] == ["p-乙"]
    assert len(fetch.urls) == 1 and fetch.urls[0].endswith("/Content/a-源/甲.jpg")
    db_session.refresh(actress)
    assert (actress.avatar_state, actress.avatar_source) == ("uploaded", "a-源/甲.jpg")
    assert actress.avatar_checked_at is not None


def test_present_when_all_persons_have_primary(db_session):
    actress = _actress(db_session, "甲")
    client = _Client({"甲": ("p-甲", True)})
    fetch = _Fetch()

    summary = _run(db_session, index=_Index({"甲": "a-源/甲.jpg"}), client=client, fetch=fetch)

    assert summary["present"] == 1
    assert fetch.urls == [] and client.uploads == []
    db_session.refresh(actress)
    assert actress.avatar_state == "present"


def test_not_found_and_no_person(db_session):
    missing = _actress(db_session, "甲")
    nobody = _actress(db_session, "乙")

    summary = _run(db_session, index=_Index({"乙": "a-源/乙.jpg"}), client=_Client({}))

    assert (summary["not_found"], summary["no_person"]) == (1, 1)
    db_session.refresh(missing)
    db_session.refresh(nobody)
    assert missing.avatar_state == "not_found"
    assert (nobody.avatar_state, nobody.avatar_source) == ("no_person", "a-源/乙.jpg")
    assert missing.avatar_checked_at.replace(tzinfo=UTC) == NOW


def test_names_are_canonical_then_aliases_by_id(db_session):
    _actress(db_session, "甲", aliases=("乙", "丙"))
    index = _Index({})

    _run(db_session, index=index, client=_Client({}))

    assert index.queries == [["甲", "乙", "丙"]]


def test_bad_image_marks_error_and_continues(db_session):
    first = _actress(db_session, "甲", film_count=9)
    second = _actress(db_session, "乙", film_count=1)
    client = _Client({"甲": ("p-甲", False), "乙": ("p-乙", False)})
    fetch = _Fetch({"甲.jpg": GfriendsError("头像地址返回的不是图片")})

    summary = _run(db_session, index=_Index({"甲": "a-源/甲.jpg", "乙": "a-源/乙.jpg"}), client=client, fetch=fetch)

    assert (summary["error"], summary["uploaded"]) == (1, 1)
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.avatar_state == "error" and "不是图片" in first.avatar_note
    assert second.avatar_state == "uploaded"


def test_upload_error_marks_error(db_session):
    actress = _actress(db_session, "甲")
    client = _Client({"甲": ("p-甲", False)}, upload_error=JellyfinError("Jellyfin 请求失败（HTTP 400）"))

    summary = _run(db_session, index=_Index({"甲": "a-源/甲.jpg"}), client=client)

    assert summary["error"] == 1
    db_session.refresh(actress)
    assert actress.avatar_state == "error" and "HTTP 400" in actress.avatar_note


def test_selection_rules_and_order(db_session):
    _actress(db_session, "已传", film_count=99, avatar_state="uploaded")
    _actress(db_session, "本有", film_count=98, avatar_state="present")
    _actress(db_session, "近查", film_count=97, avatar_state="not_found", avatar_checked_at=NOW - timedelta(days=6))
    _actress(db_session, "久查", film_count=3, avatar_state="not_found", avatar_checked_at=NOW - timedelta(days=8))
    _actress(db_session, "无人", film_count=4, avatar_state="no_person", avatar_checked_at=NOW - timedelta(days=8))
    _actress(db_session, "待办", film_count=5)
    _actress(db_session, "出错", film_count=2, avatar_state="error")
    index = _Index({})

    summary = _run(db_session, index=index, client=_Client({}), limit=3)

    assert summary["processed"] == 3
    assert [names[0] for names in index.queries] == ["待办", "无人", "久查"]


def test_actress_ids_forces_rerun(db_session):
    done = _actress(db_session, "甲", avatar_state="uploaded")
    _actress(db_session, "乙")
    index = _Index({})

    summary = _run(db_session, index=index, client=_Client({}), actress_ids=[done.id])

    assert summary["processed"] == 1
    assert index.queries == [["甲"]]
    db_session.refresh(done)
    assert done.avatar_state == "not_found"


def test_sleeps_between_downloads(db_session):
    _actress(db_session, "甲", film_count=2)
    _actress(db_session, "乙", film_count=1)
    client = _Client({"甲": ("p-甲", False), "乙": ("p-乙", False)})
    sleeps: list[float] = []

    _run(db_session, index=_Index({"甲": "a/甲.jpg", "乙": "a/乙.jpg"}), client=client, sleeps=sleeps)

    assert sleeps == [0.5]
    assert len(client.uploads) == 2


def test_summary_reports_name_map_usage(db_session):
    _actress(db_session, "甲")

    assert _run(db_session, index=_Index({}, used_name_map=False), client=_Client({}))["used_name_map"] == 0
    assert _run(db_session, index=_Index({}, used_name_map=True), client=_Client({}), actress_ids=None)[
        "used_name_map"
    ] == 1
