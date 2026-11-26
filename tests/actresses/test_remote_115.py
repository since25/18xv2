from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import ActressDeleteCandidate
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.archive_service import ActressError
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses.delete_guard import PathMapper
from app.services.actresses.remote_115 import Remote115, resolve_115
from app.services.client_115.client import Client115Error
from app.services.client_115.schemas import NodePayload

BASE = "http://openlist.test/d/115_OPEN/AV/"


@pytest.fixture
def client(fake_client):
    fake_client.add_node(NodePayload(id="d1", name="AV", path="/AV", parent_id="0", is_file=False))
    fake_client.add_node(
        NodePayload(id="f1", name="ABC-001.mp4", path="/AV/ABC-001.mp4", parent_id="d1", is_file=True)
    )
    return fake_client


class _RaisingClient:
    """get_file 总是抛给定异常的 115 客户端。"""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        raise self.exc


# 真实 115 对不存在的目录的报错原文（2026-11-26 只读核实）
MISSING_ERROR = (
    "[Errno 2] {'state': False, 'message': '文件（夹）不存在或已删除。', 'code': 430004, "
    "'data': [], 'errno': 430004, 'error': '文件（夹）不存在或已删除。'}"
)


class _StubClient:
    """按路径返回文件；没有的路径抛真实 115 的 430004 报错。"""

    def __init__(self, files: dict[str, str]) -> None:
        # 115 路径 → file_id
        self.files = files

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        if path not in self.files:
            raise Client115Error(MISSING_ERROR)
        return {"state": True, "data": {"file_id": self.files[path], "file_category": "1"}}


class _PayloadClient:
    """get_file 总是返回给定内容的 115 客户端。"""

    def __init__(self, payload) -> None:
        self.payload = payload

    def get_file(self, file_id: str | None = None, path: str | None = None):
        return self.payload


def test_resolve_found(client):
    assert resolve_115(client, BASE + "ABC-001.mp4") == Remote115(
        state="found", file_id="f1", remote_path="/AV/ABC-001.mp4", note=None
    )
    # 地址里的转义、协议和主机大小写不影响
    result = resolve_115(client, "HTTP://OpenList.Test/d/115_OPEN/AV/%41BC-001.mp4")
    assert (result.state, result.file_id) == ("found", "f1")


def test_resolve_missing():
    result = resolve_115(_StubClient({}), BASE + "ABC-002.mp4")

    assert result.state == "missing"
    assert result.file_id is None
    assert result.remote_path == "/AV/ABC-002.mp4"
    assert "430004" in result.note


@pytest.mark.parametrize("data", [[], {}, None])
def test_resolve_empty_result_is_missing(data):
    # 目录还在、文件已没了时 115 不报错，返回成功和空结果（2026-11-26 只读核实）
    result = resolve_115(_PayloadClient({"state": True, "code": 0, "data": data}), BASE + "ABC-002.mp4")

    assert result.state == "missing"
    assert result.file_id is None
    assert result.remote_path == "/AV/ABC-002.mp4"
    assert "空" in result.note


@pytest.mark.parametrize(
    "message",
    ["文件不存在", "access_token 不存在", "用户不存在", "[Errno 2] {'code': 40140116, 'message': '令牌不存在'}"],
)
def test_resolve_bare_chinese_not_exist_is_error(message):
    # 只认 430004：鉴权类报错里也可能有「不存在」，误判成已不存在会让本地文件被删而 115 原文件还在
    result = resolve_115(_RaisingClient(Client115Error(message)), BASE + "ABC-001.mp4")
    assert result.state == "error"
    assert result.file_id is None


def test_resolve_dict_without_file_id_is_error():
    result = resolve_115(_PayloadClient({"state": True, "data": {"file_name": "x"}}), BASE + "ABC-001.mp4")
    assert result.state == "error"
    assert result.note == "115 没有返回 file_id"


@pytest.mark.parametrize("message", ["Node not found", "404 Not Found", "HTTP Error 404: NOT FOUND"])
def test_resolve_english_not_found_is_error(message):
    # 英文 not found 可能是接口地址错误，没核实前不能当成「115 上已不存在」
    result = resolve_115(_RaisingClient(Client115Error(message)), BASE + "ABC-001.mp4")
    assert result.state == "error"
    assert result.file_id is None


def test_fake_client_missing_node_is_error(client):
    # Fake115Client 对找不到的路径抛 "Node not found"
    result = resolve_115(client, BASE + "ABC-002.mp4")
    assert result.state == "error"
    assert "Node not found" in result.note


def test_resolve_rejects_non_115_url(client):
    for url in (
        "http://openlist.test/d/other/AV/ABC-001.mp4",
        "http://openlist.test/AV/ABC-001.mp4",
        "/mnt/AV/ABC-001.mp4",
    ):
        result = resolve_115(client, url)
        assert result.state == "error"
        assert result.note == "不是 115_OPEN 地址"
        assert result.file_id is None


def test_resolve_other_failures_are_error(client):
    # 不认识的报错一律当失败，不当成「115 上已不存在」
    for exc in (Client115Error("ACCESS_TOKEN is not configured"), RuntimeError("boom")):
        result = resolve_115(_RaisingClient(exc), BASE + "ABC-001.mp4")
        assert result.state == "error"
        assert result.file_id is None
    # 解析到的是文件夹，不能当成要删的文件
    folder = resolve_115(client, "http://openlist.test/d/115_OPEN/AV")
    assert folder.state == "error"
    assert folder.file_id is None


def _add_film(db_session, scan_root: Path, local_root: Path, number: str, parts: dict[str, str | None]) -> str:
    """插入一部片的扫描条目和清单行，并在本地可写路径写 STRM（内容为 None 的分段不写文件）。"""
    film_dir = scan_root / "甲" / number
    for file_name, content in parts.items():
        db_session.add(JellyfinMediaItem(source="strm_115", path=str(film_dir / file_name), active=True))
        if content is not None:
            local_path = local_root / "甲" / number / file_name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(content + "\n", encoding="utf-8")
    db_session.add(ActressDeleteCandidate(film_dir=str(film_dir), selected=True, added_by="mark"))
    db_session.commit()
    return str(film_dir)


def test_check_remote_marks_mixed_as_error(db_session, tmp_path):
    scan_root = tmp_path / "scan"
    local_root = tmp_path / "local"
    client = _StubClient({"/AV/ABC-001.mp4": "f1", "/AV/ABC-002-CD1.mp4": "f2"})
    found = _add_film(db_session, scan_root, local_root, "ABC-001", {"ABC-001.strm": BASE + "ABC-001.mp4"})
    mixed = _add_film(
        db_session,
        scan_root,
        local_root,
        "ABC-002",
        {"ABC-002-CD1.strm": BASE + "ABC-002-CD1.mp4", "ABC-002-CD2.strm": BASE + "ABC-002-CD2.mp4"},
    )
    missing = _add_film(db_session, scan_root, local_root, "ABC-003", {"ABC-003.strm": BASE + "ABC-003.mp4"})
    unreadable = _add_film(db_session, scan_root, local_root, "ABC-004", {"ABC-004.strm": None})
    untouched = _add_film(db_session, scan_root, local_root, "ABC-005", {"ABC-005.strm": BASE + "ABC-001.mp4"})
    mapper = PathMapper([(str(scan_root), str(local_root))])

    processed = CandidateService().check_remote(
        db_session,
        [found, mixed, missing, unreadable + "/", str(scan_root / "甲" / "ABC-009")],
        client,
        strm_roots=[str(scan_root)],
        mapper=mapper,
    )

    assert processed == 4
    rows = {row.film_dir: row for row in db_session.scalars(select(ActressDeleteCandidate))}
    assert (rows[found].remote_state, rows[found].remote_note) == ("found", None)
    assert rows[mixed].remote_state == "error"
    assert "/AV/ABC-002-CD2.mp4" in rows[mixed].remote_note
    assert rows[missing].remote_state == "missing"
    assert "/AV/ABC-003.mp4" in rows[missing].remote_note
    assert rows[unreadable].remote_state == "error"
    assert str(local_root / "甲" / "ABC-004" / "ABC-004.strm") in rows[unreadable].remote_note
    for film_dir in (found, mixed, missing, unreadable):
        assert rows[film_dir].remote_checked_at is not None
    assert (rows[untouched].remote_state, rows[untouched].remote_checked_at) == ("unchecked", None)


def test_check_remote_requires_strm_roots(db_session, tmp_path, client):
    film_dir = _add_film(db_session, tmp_path / "scan", tmp_path / "local", "ABC-001", {"ABC-001.strm": None})

    with pytest.raises(ActressError):
        CandidateService().check_remote(db_session, [film_dir], client, strm_roots=[""], mapper=PathMapper([]))
    row = db_session.scalars(select(ActressDeleteCandidate)).one()
    assert row.remote_state == "unchecked"
