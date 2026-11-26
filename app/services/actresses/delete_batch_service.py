"""女优删片批次：把待删清单里勾选的片子快照成批次，再按 115 → STRM → 番号目录的顺序删除。

一部片任何一步失败就停在这部片（后面的步骤不执行），记失败原因，继续下一部。
每部片处理完 commit 一次；115 每删成功一个文件也立刻 commit，
中途崩溃后续跑时已删 / 已不存在的文件行不再重做，同一个 115 文件不会删两次。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import os

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.actresses import (
    ActressDeleteBatch,
    ActressDeleteBatchFile,
    ActressDeleteBatchFilm,
    ActressDeleteCandidate,
)
from app.models.jellyfin import JellyfinMediaItem
from app.services.actresses.archive_service import ActressError, require_strm_roots
from app.services.actresses.delete_guard import (
    FilmDeleteGuard,
    GuardError,
    PathMapper,
    build_url_index,
    read_strm_url,
)
from app.services.actresses.films import Film, load_films
from app.services.actresses.remote_115 import Remote115, resolve_115
from app.services.actresses.rules import RuleContext, skip_reason
from app.services.client_115.client import Fake115Client, Real115Client
from app.services.emby_media_actions.strm_mapping_service import normalize_stream_url

# 已经做完、续跑时不再重做的文件行状态
_DONE_FILE_STATUSES = ("deleted", "missing")


@dataclass
class BatchSummary:
    """一次执行后整个批次的片子计数。"""

    batch_id: int
    deleted: int
    failed: int
    skipped: int


class _FilmFailed(Exception):
    """这部片某一步失败，停在这里；消息写进片子的 error。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _check_root(root: str) -> str | None:
    """根目录不是可读目录时返回中文原因，正常返回 None。"""
    if not os.path.isdir(root):
        return f"删除根目录不存在或不是目录：{root}"
    if not os.access(root, os.R_OK | os.X_OK):
        return f"删除根目录读不了：{root}"
    return None


class DeleteBatchService:
    """删除批次的创建与执行。"""

    def create_batch(self, db: Session, *, strm_roots: list[str]) -> ActressDeleteBatch:
        """把清单里勾选的片子快照成一个待执行批次；一部都没勾时抛 ActressError。"""
        require_strm_roots(strm_roots, "建删除批次")
        film_dirs = db.scalars(
            select(ActressDeleteCandidate.film_dir)
            .where(ActressDeleteCandidate.selected.is_(True))
            .order_by(ActressDeleteCandidate.film_dir)
        ).all()
        if not film_dirs:
            raise ActressError("没有勾选的片子")
        batch = ActressDeleteBatch(status="pending")
        batch.films = [
            ActressDeleteBatchFilm(film_dir=film_dir, number=os.path.basename(film_dir), status="pending")
            for film_dir in film_dirs
        ]
        db.add(batch)
        db.commit()
        return batch

    def run(
        self,
        db: Session,
        batch_id: int,
        *,
        client_115: Real115Client | Fake115Client,
        guard: FilmDeleteGuard,
        mapper: PathMapper,
        strm_roots: list[str],
        progress: Callable[[str, int, int], None],
    ) -> BatchSummary:
        """执行（或续跑）批次：处理待执行和上次失败的片子，返回整个批次的计数。

        开始前先确认两个删除根目录都在、并建好 porn_tv1 的地址索引；
        做不到就把批次置为失败、不动任何片子，也不调用任何 115 接口。
        """
        require_strm_roots(strm_roots, "执行删除")
        batch = db.get(ActressDeleteBatch, batch_id)
        if batch is None:
            raise ActressError(f"删除批次不存在：{batch_id}")

        problem = _check_root(guard.source_root) or _check_root(guard.organized_root)
        url_index: dict[str, list[str]] = {}
        if problem is None:
            try:
                url_index = build_url_index(guard.source_root)
            except OSError as exc:
                problem = f"读取 {guard.source_root} 建 STRM 地址索引失败：{exc}"
        if problem is not None:
            batch.status = "failed"
            batch.note = f"未开始删除：{problem}"
            batch.finished_at = _now()
            db.commit()
            return self._summary(batch)

        batch.status = "running"
        batch.started_at = _now()
        batch.note = None
        db.commit()

        todo = [film for film in batch.films if film.status in ("pending", "failed")]
        for done, batch_film in enumerate(todo):
            progress(f"删除中 {batch_film.number}", done, len(todo))
            self._process_film(
                db,
                batch_film,
                client_115=client_115,
                guard=guard,
                mapper=mapper,
                strm_roots=strm_roots,
                url_index=url_index,
            )
            batch_film.finished_at = _now()
            db.commit()

        summary = self._summary(batch)
        batch.deleted_films = summary.deleted
        batch.failed_films = summary.failed
        batch.skipped_films = summary.skipped
        batch.status = "failed" if summary.failed else "completed"
        batch.finished_at = _now()
        db.commit()
        return summary

    @staticmethod
    def _summary(batch: ActressDeleteBatch) -> BatchSummary:
        statuses = [film.status for film in batch.films]
        return BatchSummary(
            batch_id=batch.id,
            deleted=statuses.count("deleted"),
            failed=statuses.count("failed"),
            skipped=statuses.count("skipped"),
        )

    def _process_film(
        self,
        db: Session,
        batch_film: ActressDeleteBatchFilm,
        *,
        client_115: Real115Client | Fake115Client,
        guard: FilmDeleteGuard,
        mapper: PathMapper,
        strm_roots: list[str],
        url_index: dict[str, list[str]],
    ) -> None:
        """处理一部片，结果写在 batch_film 上（不 commit）。"""
        batch_film.reason = None
        batch_film.error = None

        films = load_films(db, strm_roots=strm_roots, film_dirs={batch_film.film_dir})
        if not films:
            batch_film.status = "skipped"
            batch_film.reason = "片子已不在扫描结果中"
            return
        film = films[0]
        verdict = RuleContext.load(db).verdict(film)
        if not verdict.deletable:
            batch_film.status = "skipped"
            batch_film.reason = skip_reason(verdict)
            return

        try:
            local_dir = self._check_local(film, mapper, guard)
            urls = self._read_urls(film, mapper, local_dir)
            self._delete_remote(db, batch_film, client_115, urls)
            self._delete_source_strm(batch_film, guard, url_index, urls)
            self._delete_film_dir(batch_film, guard, local_dir)
        except _FilmFailed as exc:
            batch_film.status = "failed"
            batch_film.error = str(exc)
            return

        db.execute(
            update(JellyfinMediaItem)
            .where(JellyfinMediaItem.id.in_(film.media_item_ids))
            .values(active=False)
        )
        db.execute(delete(ActressDeleteCandidate).where(ActressDeleteCandidate.film_dir == batch_film.film_dir))
        batch_film.status = "deleted"

    @staticmethod
    def _check_local(film: Film, mapper: PathMapper, guard: FilmDeleteGuard) -> str:
        """换算后的本地番号目录必须存在、且按删除守卫的规则可删；否则说明路径换算不对，此时一个 115 文件都不能删。

        没换算成功时得到的是只读挂载的扫描路径，它真实存在，所以光看「存在」不够，必须用守卫同一套规则校验。
        """
        local_dir = mapper.map(film.film_dir)
        if not os.path.isdir(local_dir):
            raise _FilmFailed(f"本地番号目录不存在：{local_dir}（检查路径换算）")
        try:
            return guard.check_film_dir(local_dir)
        except GuardError as exc:
            raise _FilmFailed(f"本地番号目录不能删除：{exc}（检查路径换算）") from exc

    @staticmethod
    def _read_urls(film: Film, mapper: PathMapper, local_dir: str) -> list[str]:
        """读每个分段 STRM 的地址，任一读不到就失败；没有分段也算失败。

        换算后的 STRM 必须是已校验番号目录 local_dir 的直接子文件，否则失败。
        """
        if not film.strm_paths:
            raise _FilmFailed("片子没有 STRM 文件")
        urls: list[str] = []
        for strm_path in film.strm_paths:
            local_path = mapper.map(strm_path)
            if os.path.dirname(os.path.abspath(local_path)) != local_dir:
                raise _FilmFailed(f"STRM 不在本地番号目录里：{local_path}（检查路径换算）")
            url = read_strm_url(local_path)
            if url is None:
                raise _FilmFailed(f"读不到 STRM 地址：{local_path}")
            urls.append(url)
        return urls

    @staticmethod
    def _file_row(batch_film: ActressDeleteBatchFilm, group: str, target: str) -> ActressDeleteBatchFile:
        """取这部片同组同目标的文件行，没有就新建一行（pending）。"""
        for row in batch_film.files:
            if row.group == group and row.target == target:
                return row
        row = ActressDeleteBatchFile(group=group, target=target, status="pending")
        batch_film.files.append(row)
        return row

    def _delete_remote(
        self,
        db: Session,
        batch_film: ActressDeleteBatchFilm,
        client_115: Real115Client | Fake115Client,
        urls: list[str],
    ) -> None:
        """先把全部地址解析完，有一个解析失败就一个都不删；再逐个删 115 文件。"""
        pending: list[tuple[ActressDeleteBatchFile, Remote115]] = []
        for url in dict.fromkeys(urls):
            row = self._file_row(batch_film, "remote_115", url)
            # 续跑：已删 / 已不存在的不再解析，更不会再删一次
            if row.status in _DONE_FILE_STATUSES:
                continue
            result = resolve_115(client_115, url)
            if result.state == "error":
                row.status = "failed"
                row.error = result.note
                raise _FilmFailed(f"115 文件解析失败：{url}：{result.note}")
            pending.append((row, result))

        for row, result in pending:
            row.executed_at = _now()
            if result.state == "missing":
                row.status = "missing"
                row.error = result.note
                continue
            row.remote_file_id = result.file_id
            try:
                outcome = client_115.delete_node(result.file_id, dry_run=False)
            except Exception as exc:  # noqa: BLE001 — 任何删除异常都只让这部片失败
                row.status = "failed"
                row.error = str(exc)
                raise _FilmFailed(f"115 删除失败：{result.remote_path}：{exc}") from exc
            if not getattr(outcome, "success", False):
                row.status = "failed"
                row.error = getattr(outcome, "message", None) or "115 删除没有成功"
                raise _FilmFailed(f"115 删除失败：{result.remote_path}：{row.error}")
            row.status = "deleted"
            row.error = None
            # 立刻落库：之后崩溃也不会再删同一个 115 文件
            db.commit()

    def _delete_source_strm(
        self,
        batch_film: ActressDeleteBatchFilm,
        guard: FilmDeleteGuard,
        url_index: dict[str, list[str]],
        urls: list[str],
    ) -> None:
        """删 porn_tv1 里地址相同的 STRM。"""
        paths = sorted({path for url in urls for path in url_index.get(normalize_stream_url(url), [])})
        for path in paths:
            row = self._file_row(batch_film, "source_strm", path)
            if row.status in _DONE_FILE_STATUSES:
                continue
            row.executed_at = _now()
            try:
                row.status = guard.delete_source_strm(path)
                row.error = None
            except (GuardError, OSError) as exc:
                row.status = "failed"
                row.error = str(exc)
                raise _FilmFailed(f"删除 STRM 失败：{path}：{exc}") from exc

    def _delete_film_dir(self, batch_film: ActressDeleteBatchFilm, guard: FilmDeleteGuard, local_dir: str) -> None:
        """删番号目录，再删变空的演员目录；演员目录删不掉不影响这部片。"""
        row = self._file_row(batch_film, "organized_dir", local_dir)
        if row.status not in _DONE_FILE_STATUSES:
            row.executed_at = _now()
            try:
                row.status = guard.delete_film_dir(local_dir)
                row.error = None
            except (GuardError, OSError) as exc:
                row.status = "failed"
                row.error = str(exc)
                raise _FilmFailed(f"删除番号目录失败：{local_dir}：{exc}") from exc
        actor_dir = os.path.dirname(local_dir)
        try:
            guard.remove_actor_dir_if_empty(actor_dir)
        except (GuardError, OSError) as exc:
            row.error = f"演员目录未删除：{actor_dir}：{exc}"
