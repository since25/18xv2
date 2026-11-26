from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import ActressDeleteBatch, ActressDeleteCandidate, JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.archive_service import ActressError, ArchiveService
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses import delete_batch_service
from app.services.actresses.delete_batch_service import BatchSummary, CandidateListChanged, DeleteBatchService
from app.services.actresses.delete_guard import FilmDeleteGuard, PathMapper
from app.services.actresses.names import normalize_actress_name
from app.services.client_115.client import Client115Error
from app.services.client_115.schemas import ClientActionResult, NodePayload

BASE = "http://openlist.test/d/115_OPEN/AV/"


class _Env:
    """一次测试的目录、数据库和 115 环境。"""

    def __init__(self, db_session, tmp_path: Path, client) -> None:
        self.db = db_session
        self.tmp = tmp_path
        self.client = client
        # 扫描路径（只读挂载，不真实存在），删除时换到 organized
        self.scan_root = tmp_path / "scan"
        self.source = tmp_path / "source"
        self.organized = tmp_path / "organized"
        self.source.mkdir()
        self.organized.mkdir()
        self.mapper = PathMapper([(str(self.scan_root), str(self.organized))])
        self.guard = FilmDeleteGuard(str(self.source), str(self.organized))
        self.progress_calls: list[tuple[str, int, int]] = []

    @property
    def strm_roots(self) -> list[str]:
        return [str(self.scan_root)]

    def add_film(self, number: str, actors: tuple[str, ...], *, actor_dir: str = "甲", node_id: str | None = None) -> str:
        """建一部单段片：扫描条目、演员行、本地番号目录、porn_tv1 STRM，以及 115 节点（给了 node_id 时）。"""
        url = BASE + f"{number}.mp4"
        film_dir = self.scan_root / actor_dir / number
        item = JellyfinMediaItem(source="strm_115", path=str(film_dir / f"{number}.strm"), active=True)
        self.db.add(item)
        self.db.flush()
        for position, name in enumerate(actors):
            self.db.add(
                JellyfinMediaActor(
                    media_item_id=item.id,
                    position=position,
                    raw_name=name,
                    name_normalized=normalize_actress_name(name),
                )
            )
        self.db.commit()
        local = self.organized / actor_dir / number
        local.mkdir(parents=True)
        (local / f"{number}.strm").write_text(url + "\n", encoding="utf-8")
        (local / f"{number}.nfo").write_text("<movie/>", encoding="utf-8")
        (self.source / "AV").mkdir(exist_ok=True)
        (self.source / "AV" / f"{number}.strm").write_text(url + "\n", encoding="utf-8")
        if node_id is not None:
            self.client.add_node(
                NodePayload(id=node_id, name=f"{number}.mp4", path=f"/AV/{number}.mp4", parent_id="d1", is_file=True)
            )
        return str(film_dir)

    def set_status(self, name: str, status: str) -> None:
        actress = ArchiveService().ensure_actresses(self.db, [name])[0]
        ArchiveService().set_status(self.db, [actress.id], status, source="web")

    def reconcile(self) -> None:
        CandidateService().reconcile(self.db, strm_roots=self.strm_roots, added_by="mark")

    def candidate_dirs(self) -> list[str]:
        """当前待删清单里的全部番号目录，相当于网页上全选后确认。"""
        return list(self.db.scalars(select(ActressDeleteCandidate.film_dir)))

    def run(self, batch_id: int, *, client=None, guard=None, mapper=None) -> BatchSummary:
        return DeleteBatchService().run(
            self.db,
            batch_id,
            client_115=client or self.client,
            guard=guard or self.guard,
            mapper=mapper or self.mapper,
            strm_roots=self.strm_roots,
            progress=lambda message, done, total: self.progress_calls.append((message, done, total)),
        )


@pytest.fixture
def env(db_session, tmp_path, fake_client) -> _Env:
    fake_client.add_node(NodePayload(id="d1", name="AV", path="/AV", parent_id="0", is_file=False))
    return _Env(db_session, tmp_path, fake_client)


def _batch(db_session, batch_id: int) -> ActressDeleteBatch:
    db_session.expire_all()
    return db_session.get(ActressDeleteBatch, batch_id)


def test_create_batch_uses_only_confirmed_dirs(env):
    first = env.add_film("ABC-001", ("甲",), node_id="f1")
    second = env.add_film("ABC-002", ("甲",), node_id="f2")
    env.set_status("甲", "blacklist")
    env.reconcile()
    # 服务端的勾选标记不决定删哪些：没勾选的也能按网页确认的清单建批次
    CandidateService().set_selected(env.db, [first], False)

    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=[first + "/", first])

    batch = _batch(env.db, batch.id)
    assert batch.status == "pending"
    assert [(film.film_dir, film.number, film.status) for film in batch.films] == [(first, "ABC-001", "pending")]
    # 网页没确认的片子留在清单里
    assert second in env.candidate_dirs()


def test_create_batch_rejects_empty_list(env):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()

    with pytest.raises(ActressError, match="没有勾选的片子"):
        DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=[])
    assert env.db.scalars(select(ActressDeleteBatch)).all() == []


def test_create_batch_rejects_dirs_no_longer_in_candidates(env):
    first = env.add_film("ABC-001", ("甲",), node_id="f1")
    second = env.add_film("ABC-002", ("乙",), actor_dir="乙", node_id="f2")
    env.set_status("甲", "blacklist")
    env.set_status("乙", "blacklist")
    env.reconcile()
    # 网页打开之后乙被移出黑名单，ABC-002 已移出清单
    env.set_status("乙", "none")
    env.reconcile()

    with pytest.raises(CandidateListChanged, match="清单有变化"):
        DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=[first, second])
    assert env.db.scalars(select(ActressDeleteBatch)).all() == []


def test_run_deletes_115_then_local(env):
    film_dir = env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())

    summary = env.run(batch.id)

    assert summary == BatchSummary(batch_id=batch.id, deleted=1, failed=0, skipped=0)
    assert "f1" not in env.client.nodes
    assert not (env.source / "AV" / "ABC-001.strm").exists()
    assert not (env.organized / "甲" / "ABC-001").exists()
    # 演员目录变空后删掉，根目录保留
    assert not (env.organized / "甲").exists()
    assert env.organized.is_dir()
    assert env.db.scalars(select(JellyfinMediaItem.active)).all() == [False]
    assert env.db.scalars(select(ActressDeleteCandidate)).all() == []
    batch = _batch(env.db, batch.id)
    assert batch.status == "completed"
    assert (batch.deleted_films, batch.failed_films, batch.skipped_films) == (1, 0, 0)
    assert batch.finished_at is not None
    film = batch.films[0]
    assert film.status == "deleted"
    assert [(file.group, file.status) for file in film.files] == [
        ("remote_115", "deleted"),
        ("source_strm", "deleted"),
        ("organized_dir", "deleted"),
    ]
    assert film.files[0].remote_file_id == "f1"
    assert env.progress_calls[0] == ("删除中 ABC-001", 0, 1)
    assert film_dir == film.film_dir


def test_115_failure_keeps_local_files(env, monkeypatch):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())

    def boom(file_id, dry_run=True):
        raise Client115Error("删除接口出错")

    monkeypatch.setattr(env.client, "delete_node", boom)

    summary = env.run(batch.id)

    assert summary == BatchSummary(batch_id=batch.id, deleted=0, failed=1, skipped=0)
    assert (env.source / "AV" / "ABC-001.strm").exists()
    assert (env.organized / "甲" / "ABC-001" / "ABC-001.strm").exists()
    assert env.db.scalars(select(JellyfinMediaItem.active)).all() == [True]
    assert len(env.db.scalars(select(ActressDeleteCandidate)).all()) == 1
    batch = _batch(env.db, batch.id)
    assert batch.status == "failed"
    film = batch.films[0]
    assert film.status == "failed"
    assert "删除接口出错" in film.error
    assert [(file.group, file.status) for file in film.files] == [("remote_115", "failed")]


def test_missing_local_dir_blocks_before_115(env):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())
    # 路径换算配错：换到一个不存在的目录
    wrong = PathMapper([(str(env.scan_root), str(env.tmp / "nowhere"))])

    summary = env.run(batch.id, mapper=wrong)

    assert summary.failed == 1
    assert "f1" in env.client.nodes
    assert (env.source / "AV" / "ABC-001.strm").exists()
    film = _batch(env.db, batch.id).films[0]
    assert film.status == "failed"
    assert "本地番号目录不存在" in film.error
    assert str(env.tmp / "nowhere" / "甲" / "ABC-001") in film.error
    assert film.files == []


def test_missing_root_fails_batch_before_any_115_call(env):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())
    guard = FilmDeleteGuard(str(env.tmp / "no-source"), str(env.organized))

    summary = env.run(batch.id, guard=guard)

    assert summary == BatchSummary(batch_id=batch.id, deleted=0, failed=0, skipped=0)
    assert "f1" in env.client.nodes
    assert (env.organized / "甲" / "ABC-001").is_dir()
    batch = _batch(env.db, batch.id)
    assert batch.status == "failed"
    assert str(env.tmp / "no-source") in batch.note
    assert [film.status for film in batch.films] == ["pending"]


class _StubClient:
    """按路径返回文件；没有的路径抛「文件不存在」，删除时记录调用。"""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.deleted: list[str] = []

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        if path not in self.files:
            raise Client115Error("文件不存在")
        return {"state": True, "data": {"file_id": self.files[path], "file_category": "1"}}

    def delete_node(self, file_id: str, dry_run: bool = True):
        self.deleted.append(file_id)
        raise AssertionError("不应调用删除")


def test_115_already_missing_still_deletes_local(env):
    env.add_film("ABC-001", ("甲",))
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())
    client = _StubClient({})

    summary = env.run(batch.id, client=client)

    assert summary.deleted == 1
    assert client.deleted == []
    assert not (env.source / "AV" / "ABC-001.strm").exists()
    assert not (env.organized / "甲" / "ABC-001").exists()
    film = _batch(env.db, batch.id).films[0]
    assert film.status == "deleted"
    assert [(file.group, file.status) for file in film.files] == [
        ("remote_115", "missing"),
        ("source_strm", "deleted"),
        ("organized_dir", "deleted"),
    ]


def test_skips_film_protected_after_batch_created(env):
    env.add_film("ABC-001", ("甲", "乙"), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())
    env.set_status("乙", "whitelist")

    summary = env.run(batch.id)

    assert summary == BatchSummary(batch_id=batch.id, deleted=0, failed=0, skipped=1)
    assert "f1" in env.client.nodes
    assert (env.organized / "甲" / "ABC-001").is_dir()
    batch = _batch(env.db, batch.id)
    assert batch.status == "completed"
    film = batch.films[0]
    assert film.status == "skipped"
    assert "乙" in film.reason


def test_resume_retries_failed_without_redoing_done_files(env, monkeypatch):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())
    calls: list[str] = []
    original_delete = env.client.delete_node

    def counting_delete(file_id, dry_run=True):
        calls.append(file_id)
        return original_delete(file_id, dry_run=dry_run)

    monkeypatch.setattr(env.client, "delete_node", counting_delete)

    class _FlakyGuard(FilmDeleteGuard):
        def delete_film_dir(self, path: str) -> str:
            raise OSError("目录正被占用")

    first = env.run(batch.id, guard=_FlakyGuard(str(env.source), str(env.organized)))

    assert first.failed == 1
    assert _batch(env.db, batch.id).status == "failed"
    assert (env.organized / "甲" / "ABC-001").is_dir()
    assert not (env.source / "AV" / "ABC-001.strm").exists()

    second = env.run(batch.id)

    assert second == BatchSummary(batch_id=batch.id, deleted=1, failed=0, skipped=0)
    assert calls == ["f1"]
    assert not (env.organized / "甲" / "ABC-001").exists()
    batch = _batch(env.db, batch.id)
    assert batch.status == "completed"
    film = batch.films[0]
    assert film.status == "deleted"
    assert film.error is None
    assert sorted((file.group, file.status) for file in film.files) == [
        ("organized_dir", "deleted"),
        ("remote_115", "deleted"),
        ("source_strm", "deleted"),
    ]


def test_actor_dir_race_does_not_fail_film(env):
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs())

    class _RacyGuard(FilmDeleteGuard):
        def remove_actor_dir_if_empty(self, path: str) -> bool:
            raise OSError("目录非空")

    summary = env.run(batch.id, guard=_RacyGuard(str(env.source), str(env.organized)))

    assert summary.deleted == 1
    film = _batch(env.db, batch.id).films[0]
    assert film.status == "deleted"
    organized_row = film.files[-1]
    assert (organized_row.group, organized_row.status) == ("organized_dir", "deleted")
    assert "演员目录未删除" in organized_row.error


def _prepare(env) -> int:
    """建 ABC-001（甲，115 节点 f1）、拉黑甲、建批次，返回批次 id。"""
    env.add_film("ABC-001", ("甲",), node_id="f1")
    env.set_status("甲", "blacklist")
    env.reconcile()
    return DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs()).id


def _assert_untouched(env) -> None:
    """115 节点和本地文件都还在。"""
    assert "f1" in env.client.nodes
    assert (env.source / "AV" / "ABC-001.strm").exists()
    assert (env.organized / "甲" / "ABC-001" / "ABC-001.strm").exists()


@pytest.mark.parametrize("case", ["no_mapping", "outside_organized"])
def test_mapping_outside_organized_blocks_before_115(env, case):
    batch_id = _prepare(env)
    # 换算没命中时得到扫描路径；生产上扫描路径（只读挂载）真实存在
    for root in (env.scan_root, env.tmp / "mirror"):
        film = root / "甲" / "ABC-001"
        film.mkdir(parents=True)
        (film / "ABC-001.strm").write_text(BASE + "ABC-001.mp4\n", encoding="utf-8")
    if case == "no_mapping":
        mapper = PathMapper([])
    else:
        mapper = PathMapper([(str(env.scan_root), str(env.tmp / "mirror"))])

    summary = env.run(batch_id, mapper=mapper)

    assert summary.failed == 1
    _assert_untouched(env)
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "failed"
    assert "本地番号目录不能删除" in film.error
    assert film.files == []


def test_strm_mapped_outside_film_dir_blocks_before_115(env):
    batch_id = _prepare(env)
    elsewhere = env.tmp / "elsewhere" / "ABC-001.strm"
    elsewhere.parent.mkdir()
    elsewhere.write_text(BASE + "ABC-001.mp4\n", encoding="utf-8")
    scan_strm = env.scan_root / "甲" / "ABC-001" / "ABC-001.strm"
    mapper = PathMapper([(str(env.scan_root), str(env.organized)), (str(scan_strm), str(elsewhere))])

    summary = env.run(batch_id, mapper=mapper)

    assert summary.failed == 1
    _assert_untouched(env)
    film = _batch(env.db, batch_id).films[0]
    assert "STRM 不在本地番号目录里" in film.error
    assert film.files == []


def test_multi_part_resume_deletes_each_115_file_once(env, monkeypatch):
    film_dir = env.scan_root / "甲" / "ABC-001"
    local = env.organized / "甲" / "ABC-001"
    local.mkdir(parents=True)
    (env.source / "AV").mkdir()
    for index, part in enumerate(("CD1", "CD2"), start=1):
        name = f"ABC-001-{part}"
        item = JellyfinMediaItem(source="strm_115", path=str(film_dir / f"{name}.strm"), active=True)
        env.db.add(item)
        env.db.flush()
        env.db.add(
            JellyfinMediaActor(media_item_id=item.id, position=0, raw_name="甲", name_normalized=normalize_actress_name("甲"))
        )
        (local / f"{name}.strm").write_text(BASE + f"{name}.mp4\n", encoding="utf-8")
        (env.source / "AV" / f"{name}.strm").write_text(BASE + f"{name}.mp4\n", encoding="utf-8")
        env.client.add_node(
            NodePayload(id=f"f{index}", name=f"{name}.mp4", path=f"/AV/{name}.mp4", parent_id="d1", is_file=True)
        )
    env.db.commit()
    env.set_status("甲", "blacklist")
    env.reconcile()
    batch_id = DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs()).id
    calls: list[str] = []
    original_delete = env.client.delete_node
    fail_once = {"f2"}

    def flaky_delete(file_id, dry_run=True):
        calls.append(file_id)
        if file_id in fail_once:
            fail_once.discard(file_id)
            raise Client115Error("CD2 删除出错")
        return original_delete(file_id, dry_run=dry_run)

    monkeypatch.setattr(env.client, "delete_node", flaky_delete)

    first = env.run(batch_id)

    assert first.failed == 1
    assert "f1" not in env.client.nodes
    assert "f2" in env.client.nodes
    assert sorted(path.name for path in (env.source / "AV").iterdir()) == ["ABC-001-CD1.strm", "ABC-001-CD2.strm"]
    assert sorted(path.name for path in local.iterdir()) == ["ABC-001-CD1.strm", "ABC-001-CD2.strm"]
    assert _batch(env.db, batch_id).films[0].status == "failed"

    second = env.run(batch_id)

    assert second.deleted == 1
    assert calls.count("f1") == 1
    assert calls.count("f2") == 2
    assert env.client.nodes.keys() == {"d1"}
    assert list((env.source / "AV").iterdir()) == []
    assert not local.exists()


def test_missing_organized_root_fails_batch_before_any_115_call(env):
    batch_id = _prepare(env)
    guard = FilmDeleteGuard(str(env.source), str(env.tmp / "no-organized"))

    summary = env.run(batch_id, guard=guard)

    assert summary == BatchSummary(batch_id=batch_id, deleted=0, failed=0, skipped=0)
    _assert_untouched(env)
    batch = _batch(env.db, batch_id)
    assert batch.status == "failed"
    assert str(env.tmp / "no-organized") in batch.note
    assert [film.status for film in batch.films] == ["pending"]


def test_url_index_failure_fails_batch_before_any_115_call(env, monkeypatch):
    batch_id = _prepare(env)
    calls: list[str] = []

    def no_115(*args, **kwargs):
        calls.append("115")
        raise AssertionError("不应调用 115")

    def broken_index(root):
        raise OSError("权限不够")

    monkeypatch.setattr(env.client, "get_file", no_115)
    monkeypatch.setattr(env.client, "delete_node", no_115)
    monkeypatch.setattr(delete_batch_service, "build_url_index", broken_index)

    summary = env.run(batch_id)

    assert summary.failed == 0
    assert calls == []
    _assert_untouched(env)
    batch = _batch(env.db, batch_id)
    assert batch.status == "failed"
    assert "权限不够" in batch.note
    assert [film.status for film in batch.films] == ["pending"]


def test_delete_node_unsuccessful_keeps_local_files(env, monkeypatch):
    batch_id = _prepare(env)

    def unsuccessful(file_id, dry_run=True):
        return ClientActionResult(success=False, action="delete", message="115 拒绝删除", payload={})

    monkeypatch.setattr(env.client, "delete_node", unsuccessful)

    summary = env.run(batch_id)

    assert summary.failed == 1
    _assert_untouched(env)
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "failed"
    assert "115 拒绝删除" in film.error
    assert [(file.group, file.status) for file in film.files] == [("remote_115", "failed")]
