from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.actresses import (
    ActressDeleteBatch,
    ActressDeleteBatchFile,
    ActressDeleteCandidate,
    JellyfinMediaActor,
)
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

    def add_film(
        self,
        number: str,
        actors: tuple[str, ...],
        *,
        actor_dir: str = "甲",
        node_id: str | None = None,
        url: str | None = None,
        remote_parent: str = "d1",
    ) -> str:
        """建一部单段片：扫描条目、演员行、本地番号目录、porn_tv1 STRM，以及 115 节点（给了 node_id 时）。"""
        url = url or BASE + f"{number}.mp4"
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
            remote_path = "/AV/" + url.removeprefix(BASE)
            self.client.add_node(
                NodePayload(
                    id=node_id,
                    name=Path(remote_path).name,
                    path=remote_path,
                    parent_id=remote_parent,
                    is_file=True,
                )
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

    def run(self, batch_id: int, *, client=None, guard=None, mapper=None, openlist=None) -> BatchSummary:
        return DeleteBatchService().run(
            self.db,
            batch_id,
            client_115=client or self.client,
            guard=guard or self.guard,
            mapper=mapper or self.mapper,
            strm_roots=self.strm_roots,
            progress=lambda message, done, total: self.progress_calls.append((message, done, total)),
            openlist=openlist,
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
        ("remote_leftover", "skipped"),
        ("source_leftover", "deleted"),
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


# 真实 115 对不存在路径的报错（430004）
MISSING_ERROR = "[Errno 2] {'state': False, 'message': '文件（夹）不存在或已删除。', 'code': 430004}"


class _StubClient:
    """按路径返回文件；没有的路径抛 115 的 430004 报错，删除时记录调用。"""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.deleted: list[str] = []

    def get_file(self, file_id: str | None = None, path: str | None = None) -> dict:
        if path not in self.files:
            raise Client115Error(MISSING_ERROR)
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
        ("remote_leftover", "skipped"),
        ("source_leftover", "deleted"),
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
        ("remote_leftover", "skipped"),
        ("source_leftover", "deleted"),
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
    organized_row = next(file for file in film.files if file.group == "organized_dir")
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
    assert not (env.source / "AV").exists()
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


def test_symlinked_strm_blocks_before_115(env, monkeypatch):
    """换算后的 STRM 本身是符号链接：这部片判失败，不调用任何 115 接口，什么都不删。"""
    batch_id = _prepare(env)
    calls: list[str] = []

    def no_115(*args, **kwargs):
        calls.append("115")
        raise AssertionError("不应调用 115")

    monkeypatch.setattr(env.client, "get_file", no_115)
    monkeypatch.setattr(env.client, "delete_node", no_115)
    real = env.tmp / "real" / "ABC-001.strm"
    real.parent.mkdir()
    real.write_text(BASE + "ABC-001.mp4\n", encoding="utf-8")
    link = env.organized / "甲" / "ABC-001" / "ABC-001.strm"
    link.unlink()
    link.symlink_to(real)

    summary = env.run(batch_id)

    assert summary.failed == 1
    assert calls == []
    assert "f1" in env.client.nodes
    assert (env.source / "AV" / "ABC-001.strm").exists()
    assert link.is_symlink()
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "failed"
    assert "符号链接" in film.error
    assert film.files == []


def test_unwritable_root_fails_batch_before_any_115_call(env, monkeypatch):
    """删除根目录可读但不可写：整批失败，不调用任何 115 接口。"""
    batch_id = _prepare(env)
    calls: list[str] = []

    def no_115(*args, **kwargs):
        calls.append("115")
        raise AssertionError("不应调用 115")

    monkeypatch.setattr(env.client, "get_file", no_115)
    monkeypatch.setattr(env.client, "delete_node", no_115)
    real_access = delete_batch_service.os.access
    organized = str(env.organized)

    def fake_access(path, mode, *args, **kwargs):
        if str(path) == organized and mode & delete_batch_service.os.W_OK:
            return False
        return real_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(delete_batch_service.os, "access", fake_access)

    summary = env.run(batch_id)

    assert summary == BatchSummary(batch_id=batch_id, deleted=0, failed=0, skipped=0)
    assert calls == []
    _assert_untouched(env)
    batch = _batch(env.db, batch_id)
    assert batch.status == "failed"
    assert "写不了" in batch.note
    assert organized in batch.note
    assert [film.status for film in batch.films] == ["pending"]


def test_source_strm_not_found_records_missing_row(env):
    """porn_tv1 里按地址找不到对应 STRM：记一条 source_strm / missing 文件行，片子照常删完。"""
    batch_id = _prepare(env)
    (env.source / "AV" / "ABC-001.strm").unlink()

    summary = env.run(batch_id)

    assert summary.deleted == 1
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "deleted"
    assert [(file.group, file.status) for file in film.files] == [
        ("remote_115", "deleted"),
        ("source_strm", "missing"),
        ("organized_dir", "deleted"),
        ("remote_leftover", "skipped"),
    ]
    missing_row = film.files[1]
    assert missing_row.target == BASE + "ABC-001.mp4"
    assert "porn_tv1 里没找到对应 STRM" in missing_row.error


def test_new_part_added_after_scan_blocks_before_115(env, monkeypatch):
    """番号目录里有扫描结果里没有的 STRM（扫描后新加的分段）：这部片判失败，不调用任何 115 接口。"""
    batch_id = _prepare(env)
    calls: list[str] = []

    def no_115(*args, **kwargs):
        calls.append("115")
        raise AssertionError("不应调用 115")

    monkeypatch.setattr(env.client, "get_file", no_115)
    monkeypatch.setattr(env.client, "delete_node", no_115)
    extra = env.organized / "甲" / "ABC-001" / "ABC-001-CD2.strm"
    extra.write_text(BASE + "ABC-001-CD2.mp4\n", encoding="utf-8")

    summary = env.run(batch_id)

    assert summary.failed == 1
    assert calls == []
    _assert_untouched(env)
    assert extra.exists()
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "failed"
    assert "番号目录里有扫描之后新加的分段，请等下次扫描" in film.error
    assert film.files == []


class _FakeOpenList:
    """记录刷新、列目录调用的 OpenList 客户端；同时记下刷新那一刻 STRM / 115 节点的状态。"""

    def __init__(
        self,
        env: _Env,
        *,
        errors: list[Exception] | None = None,
        entries: dict[str, list[tuple[str, bool]]] | None = None,
        list_errors: list[Exception] | None = None,
    ) -> None:
        self.env = env
        self.errors = list(errors or [])
        self.entries = dict(entries or {})
        self.list_errors = list(list_errors or [])
        self.calls: list[tuple[str, bool]] = []
        self.listed: list[str] = []
        self.node_states: list[bool] = []

    def refresh_dir(self, path: str) -> None:
        self.calls.append((path, (self.env.source / "AV" / "ABC-001.strm").exists()))
        self.node_states.append("d2" in self.env.client.nodes)
        if self.errors:
            raise self.errors.pop(0)

    def list_dir(self, path: str) -> list[tuple[str, bool]]:
        self.listed.append(path)
        if self.list_errors:
            raise self.list_errors.pop(0)
        # 默认模拟「目录里只有刚删掉的那部片」：不能因此判成整个目录可删
        return list(self.entries.get(path, [("ABC-001.mp4", False)]))


class _BusyDirGuard(FilmDeleteGuard):
    """删番号目录总是失败的守卫，用来制造「115 已删、本地失败」的续跑场景。"""

    def delete_film_dir(self, path: str) -> str:
        raise OSError("目录正被占用")


def _blacklisted_batch(env: _Env, *, node_id: str | None = "f1") -> int:
    env.add_film("ABC-001", ("甲",), node_id=node_id)
    env.set_status("甲", "blacklist")
    env.reconcile()
    return DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs()).id


def test_refreshes_openlist_dir_after_115_before_local(env):
    batch_id = _blacklisted_batch(env)
    openlist = _FakeOpenList(env)

    summary = env.run(batch_id, openlist=openlist)

    assert summary.deleted == 1
    # 115 删完后、删本地 STRM 之前刷新 OpenList 里这部片所在的目录，避免按旧缓存重新生成 STRM
    assert openlist.calls == [("/115_OPEN/AV", True)]
    film = _batch(env.db, batch_id).films[0]
    assert [(file.group, file.target, file.status) for file in film.files] == [
        ("remote_115", BASE + "ABC-001.mp4", "deleted"),
        ("openlist_dir", "/115_OPEN/AV", "refreshed"),
        ("source_strm", str(env.source / "AV" / "ABC-001.strm"), "deleted"),
        ("organized_dir", str(env.organized / "甲" / "ABC-001"), "deleted"),
        ("source_leftover", str(env.source / "AV"), "deleted"),
    ]


def test_without_openlist_client_no_refresh_row(env):
    batch_id = _blacklisted_batch(env)

    assert env.run(batch_id).deleted == 1

    film = _batch(env.db, batch_id).films[0]
    assert [(file.group, file.status) for file in film.files] == [
        ("remote_115", "deleted"),
        ("source_strm", "deleted"),
        ("organized_dir", "deleted"),
        ("remote_leftover", "skipped"),
        ("source_leftover", "deleted"),
    ]


def test_refreshes_openlist_when_115_already_missing(env):
    batch_id = _blacklisted_batch(env, node_id=None)
    openlist = _FakeOpenList(env)

    summary = env.run(batch_id, client=_StubClient({}), openlist=openlist)

    # 115 上已不存在时 OpenList 缓存里也可能还有它，照样刷新
    assert summary.deleted == 1
    assert openlist.calls == [("/115_OPEN/AV", True)]


def test_openlist_refresh_failure_does_not_fail_film(env):
    batch_id = _blacklisted_batch(env)
    openlist = _FakeOpenList(env, errors=[RuntimeError("虚构：OpenList 连不上")])

    summary = env.run(batch_id, openlist=openlist)

    assert summary == BatchSummary(batch_id=batch_id, deleted=1, failed=0, skipped=0)
    assert not (env.organized / "甲" / "ABC-001").exists()
    batch = _batch(env.db, batch_id)
    assert batch.status == "completed"
    row = next(file for file in batch.films[0].files if file.group == "openlist_dir")
    assert row.status == "failed"
    assert "OpenList 连不上" in row.error


def test_resume_refreshes_openlist_again_if_last_refresh_failed(env):
    batch_id = _blacklisted_batch(env)
    failing = _FakeOpenList(env, errors=[RuntimeError("虚构：超时")])

    first = env.run(batch_id, guard=_BusyDirGuard(str(env.source), str(env.organized)), openlist=failing)
    assert first.failed == 1
    assert len(failing.calls) == 1

    retry = _FakeOpenList(env)
    assert env.run(batch_id, openlist=retry).deleted == 1
    assert [path for path, _ in retry.calls] == ["/115_OPEN/AV"]
    row = next(file for file in _batch(env.db, batch_id).films[0].files if file.group == "openlist_dir")
    assert (row.status, row.error) == ("refreshed", None)


def test_resume_does_not_refresh_openlist_twice(env):
    batch_id = _blacklisted_batch(env)
    first = _FakeOpenList(env)
    env.run(batch_id, guard=_BusyDirGuard(str(env.source), str(env.organized)), openlist=first)
    assert len(first.calls) == 1

    second = _FakeOpenList(env)
    assert env.run(batch_id, openlist=second).deleted == 1
    assert second.calls == []


def _subdir_film(env: _Env, *, dir_is_file: bool = False) -> int:
    """建一部放在 115 子目录 /AV/ABC-001/ 里的片子，返回批次 id。"""
    env.client.add_node(
        NodePayload(id="d2", name="ABC-001", path="/AV/ABC-001", parent_id="d1", is_file=dir_is_file)
    )
    env.add_film(
        "ABC-001",
        ("甲",),
        node_id="f2",
        url=BASE + "ABC-001/ABC-001.mp4",
        remote_parent="d2",
    )
    env.set_status("甲", "blacklist")
    env.reconcile()
    return DeleteBatchService().create_batch(env.db, strm_roots=env.strm_roots, film_dirs=env.candidate_dirs()).id


def test_remote_leftover_shared_dir_deletes_only_same_name_sidecars(env):
    batch_id = _blacklisted_batch(env)
    env.client.add_node(
        NodePayload(id="n1", name="ABC-001.nfo", path="/AV/ABC-001.nfo", parent_id="d1", is_file=True)
    )
    env.client.add_node(
        NodePayload(id="f9", name="ABC-009.mp4", path="/AV/ABC-009.mp4", parent_id="d1", is_file=True)
    )
    openlist = _FakeOpenList(
        env,
        entries={"/115_OPEN/AV": [("ABC-001.nfo", False), ("ABC-009.mp4", False)]},
    )

    summary = env.run(batch_id, openlist=openlist)

    assert summary.deleted == 1
    # 集合目录里还有别的片子：只删同名 nfo，目录和别的视频都不动
    assert "n1" not in env.client.nodes
    assert "d1" in env.client.nodes
    assert "f9" in env.client.nodes
    assert openlist.listed == ["/115_OPEN/AV"]
    film = _batch(env.db, batch_id).films[0]
    assert ("remote_leftover", "/AV/ABC-001.nfo", "deleted") in [
        (file.group, file.target, file.status) for file in film.files
    ]


def test_remote_leftover_whole_dir(env):
    batch_id = _subdir_film(env)
    env.client.add_node(
        NodePayload(
            id="n1", name="ABC-001.nfo", path="/AV/ABC-001/ABC-001.nfo", parent_id="d2", is_file=True
        )
    )
    env.client.add_node(
        NodePayload(
            id="n2",
            name="ABC-001-poster.jpg",
            path="/AV/ABC-001/ABC-001-poster.jpg",
            parent_id="d2",
            is_file=True,
        )
    )
    openlist = _FakeOpenList(
        env,
        entries={
            "/115_OPEN/AV/ABC-001": [
                ("ABC-001.nfo", False),
                ("ABC-001-poster.jpg", False),
            ]
        },
    )

    summary = env.run(batch_id, openlist=openlist)

    assert summary.deleted == 1
    assert "d2" not in env.client.nodes
    # 先刷新片子所在目录；整个删掉后再刷新上级目录
    assert [path for path, _ in openlist.calls] == ["/115_OPEN/AV/ABC-001", "/115_OPEN/AV"]
    assert openlist.node_states == [True, False]
    film = _batch(env.db, batch_id).films[0]
    assert ("remote_leftover", "/AV/ABC-001", "deleted") in [
        (file.group, file.target, file.status) for file in film.files
    ]


def test_remote_leftover_skipped_when_refresh_failed(env):
    batch_id = _blacklisted_batch(env)
    openlist = _FakeOpenList(env, errors=[RuntimeError("虚构：超时")])

    summary = env.run(batch_id, openlist=openlist)

    assert summary.deleted == 1
    film = _batch(env.db, batch_id).films[0]
    assert film.status == "deleted"
    row = next(file for file in film.files if file.group == "remote_leftover")
    assert (row.target, row.status) == ("/AV", "skipped")
    assert "OpenList 没刷新成功" in row.error
    assert openlist.listed == []


def test_remote_leftover_skipped_without_openlist(env):
    batch_id = _blacklisted_batch(env)

    summary = env.run(batch_id)

    assert summary.deleted == 1
    film = _batch(env.db, batch_id).films[0]
    row = next(file for file in film.files if file.group == "remote_leftover")
    assert (row.target, row.status) == ("/AV", "skipped")
    assert "没配置 OpenList" in row.error


def test_remote_leftover_rejects_wrong_category(env):
    batch_id = _subdir_film(env, dir_is_file=True)
    env.client.add_node(
        NodePayload(
            id="n1", name="ABC-001.nfo", path="/AV/ABC-001/ABC-001.nfo", parent_id="d2", is_file=True
        )
    )
    openlist = _FakeOpenList(env, entries={"/115_OPEN/AV/ABC-001": [("ABC-001.nfo", False)]})

    summary = env.run(batch_id, openlist=openlist)

    assert summary.deleted == 1
    # 期望是文件夹却查到文件：不删，记失败
    assert "d2" in env.client.nodes
    assert "n1" in env.client.nodes
    film = _batch(env.db, batch_id).films[0]
    row = next(file for file in film.files if file.group == "remote_leftover")
    assert (row.target, row.status) == ("/AV/ABC-001", "failed")
    assert "不是文件夹" in row.error


def test_source_leftover_whole_dir(env):
    batch_id = _blacklisted_batch(env)
    folder = env.source / "AV" / "ABC-001"
    folder.mkdir()
    (env.source / "AV" / "ABC-001.strm").rename(folder / "ABC-001.strm")
    (folder / "ABC-001.nfo").write_text("<movie/>", encoding="utf-8")
    (folder / "ABC-001-fanart.jpg").write_text("x", encoding="utf-8")

    summary = env.run(batch_id)

    assert summary.deleted == 1
    assert not folder.exists()
    film = _batch(env.db, batch_id).films[0]
    assert ("source_leftover", str(folder), "deleted") in [
        (file.group, file.target, file.status) for file in film.files
    ]


def test_source_leftover_shared_dir(env):
    batch_id = _blacklisted_batch(env)
    nfo = env.source / "AV" / "ABC-001.nfo"
    nfo.write_text("<movie/>", encoding="utf-8")
    other = env.source / "AV" / "ABC-002.strm"
    other.write_text(BASE + "ABC-002.mp4\n", encoding="utf-8")

    summary = env.run(batch_id)

    assert summary.deleted == 1
    assert not nfo.exists()
    assert other.exists()
    assert (env.source / "AV").is_dir()
    film = _batch(env.db, batch_id).films[0]
    assert ("source_leftover", str(nfo), "deleted") in [
        (file.group, file.target, file.status) for file in film.files
    ]


class _BrokenLeftoverGuard(FilmDeleteGuard):
    """删源目录总是失败的守卫，用来确认清理失败不影响片子结果。"""

    def delete_source_dir(self, path: str) -> str:
        raise OSError("虚构：目录正被占用")


def test_leftover_failure_keeps_film_deleted(env):
    batch_id = _blacklisted_batch(env)
    guard = _BrokenLeftoverGuard(str(env.source), str(env.organized))

    summary = env.run(batch_id, guard=guard)

    assert summary == BatchSummary(batch_id=batch_id, deleted=1, failed=0, skipped=0)
    assert (env.source / "AV").is_dir()
    batch = _batch(env.db, batch_id)
    assert batch.status == "completed"
    film = batch.films[0]
    assert film.status == "deleted"
    row = next(file for file in film.files if file.group == "source_leftover")
    assert row.status == "failed"
    assert "目录正被占用" in row.error


class _CleanupBlockedGuard(FilmDeleteGuard):
    """源目录清理总是失败的守卫，用来制造「片子已删、配套文件还在」的补跑场景。"""

    def delete_source_dir(self, path: str) -> str:
        raise OSError("虚构：清理失败")

    def delete_source_sidecar(self, path: str) -> str:
        raise OSError("虚构：清理失败")


def _deleted_batch_with_leftovers(env: _Env) -> int:
    """跑完一个批次，115 端当时没配 OpenList、本地清理又失败，留下可补跑的残留。"""
    batch_id = _blacklisted_batch(env)
    guard = _CleanupBlockedGuard(str(env.source), str(env.organized))
    assert env.run(batch_id, guard=guard).deleted == 1
    # 补跑时 115 目录里还有同名 nfo（批次运行时没配 OpenList，没动过它）
    env.client.add_node(
        NodePayload(id="n1", name="ABC-001.nfo", path="/AV/ABC-001.nfo", parent_id="d1", is_file=True)
    )
    return batch_id


def test_clean_leftovers_preview_does_not_delete(env):
    batch_id = _deleted_batch_with_leftovers(env)
    env.db.expire_all()
    before = len(env.db.scalars(select(ActressDeleteBatchFile)).all())
    openlist = _FakeOpenList(
        env,
        entries={"/115_OPEN/AV": [("ABC-001.nfo", False), ("ABC-009.mp4", False)]},
    )

    actions = DeleteBatchService().clean_leftovers(
        env.db, batch_id, client_115=env.client, guard=env.guard, openlist=openlist, apply=False
    )

    assert {(action.group, action.whole_dir) for action in actions} == {
        ("remote_leftover", False),
        ("source_leftover", True),
    }
    assert {action.target for action in actions} == {
        "/AV/ABC-001.nfo",
        str(env.source / "AV"),
    }
    # 只预览：文件都还在，也不写新的文件行
    assert "n1" in env.client.nodes
    assert (env.source / "AV").is_dir()
    env.db.expire_all()
    assert len(env.db.scalars(select(ActressDeleteBatchFile)).all()) == before
    # 预览也会刷新 OpenList 缓存，但不删东西
    assert [path for path, _ in openlist.calls] == ["/115_OPEN/AV"]


def test_clean_leftovers_apply_deletes(env):
    batch_id = _deleted_batch_with_leftovers(env)
    openlist = _FakeOpenList(
        env,
        entries={"/115_OPEN/AV": [("ABC-001.nfo", False), ("ABC-009.mp4", False)]},
    )

    actions = DeleteBatchService().clean_leftovers(
        env.db, batch_id, client_115=env.client, guard=env.guard, openlist=openlist, apply=True
    )

    assert {action.target for action in actions} == {
        "/AV/ABC-001.nfo",
        str(env.source / "AV"),
    }
    assert "n1" not in env.client.nodes
    assert not (env.source / "AV").exists()
    film = _batch(env.db, batch_id).films[0]
    rows = {(file.group, file.target): file.status for file in film.files}
    assert rows[("remote_leftover", "/AV/ABC-001.nfo")] == "deleted"
    assert rows[("source_leftover", str(env.source / "AV"))] == "deleted"


def test_clean_leftovers_twice_is_noop(env):
    batch_id = _deleted_batch_with_leftovers(env)
    entries = {"/115_OPEN/AV": [("ABC-001.nfo", False), ("ABC-009.mp4", False)]}
    first = _FakeOpenList(env, entries=entries)
    DeleteBatchService().clean_leftovers(
        env.db, batch_id, client_115=env.client, guard=env.guard, openlist=first, apply=True
    )

    second = _FakeOpenList(env, entries=entries)
    actions = DeleteBatchService().clean_leftovers(
        env.db, batch_id, client_115=env.client, guard=env.guard, openlist=second, apply=True
    )

    assert actions == []
    # 第二次仍会刷新 OpenList 缓存，但不会再调删除
    assert [path for path, _ in second.calls] == ["/115_OPEN/AV"]


def test_clean_leftovers_unknown_batch(env):
    with pytest.raises(ActressError):
        DeleteBatchService().clean_leftovers(
            env.db, 99999, client_115=env.client, guard=env.guard, openlist=None, apply=False
        )
