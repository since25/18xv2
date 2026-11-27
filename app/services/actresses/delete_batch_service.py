"""女优删片批次：把网页上确认删除的片子（必须仍在待删清单里）建成批次，再按 115 → STRM → 番号目录的顺序删除。

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
from app.services.actresses.leftovers import plan_dir
from app.services.actresses.openlist import OpenListClient, openlist_dir_for
from app.services.actresses.remote_115 import MISSING_ERROR_CODE, Remote115, resolve_115
from app.services.actresses.rules import RuleContext, skip_reason
from app.services.client_115.client import Client115Error, Fake115Client, Real115Client
from app.services.emby_media_actions.strm_mapping_service import decode_115_open_path, normalize_stream_url

# 已经做完、续跑时不再重做的文件行状态
_DONE_FILE_STATUSES = ("deleted", "missing")


@dataclass
class BatchSummary:
    """一次执行后整个批次的片子计数。"""

    batch_id: int
    deleted: int
    failed: int
    skipped: int


@dataclass
class LeftoverAction:
    """补跑清理时要展示（或已经执行）的一条动作。"""

    group: str
    target: str
    whole_dir: bool


def _lookup_115(
    client: Real115Client | Fake115Client, path: str, *, expect_dir: bool
) -> tuple[str, str | None, str | None]:
    """按路径查 115 节点，返回 `(state, file_id, note)`，state 为 found / missing / error。

    不存在只认 430004 和「查询成功但空结果」；类型不是期望的文件夹 / 文件一律算 error，不交给删除。
    """
    try:
        payload = client.get_file(path=path)
    except Client115Error as exc:
        text = str(exc)
        if MISSING_ERROR_CODE.search(text):
            return "missing", None, f"115 上已不存在：{text}"
        return "error", None, f"115 查询失败：{text}"
    except Exception as exc:  # noqa: BLE001 — 查询失败只记在这一行，不影响片子
        return "error", None, f"115 查询失败：{exc}"

    data = payload.get("data") if isinstance(payload, dict) else None
    # 目录还在、文件已没了时 115 不报错，返回成功和空结果
    if isinstance(payload, dict) and payload.get("state") is True and not data:
        return "missing", None, "115 上已不存在：按路径查询返回空结果"
    file_id = str(data.get("file_id") or "") if isinstance(data, dict) else ""
    if not file_id:
        return "error", None, "115 没有返回 file_id"
    expected = "0" if expect_dir else "1"
    if str(data.get("file_category")) != expected:
        return "error", None, "115 上这个路径不是文件夹" if expect_dir else "115 上这个路径不是文件"
    return "found", file_id, None


class CandidateListChanged(ActressError):
    """网页确认的片子里有已不在待删清单里的（页面过期），接口层转成 409。"""


class _FilmFailed(Exception):
    """这部片某一步失败，停在这里；消息写进片子的 error。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _check_root(root: str) -> str | None:
    """根目录不是可读可写目录时返回中文原因，正常返回 None。"""
    if not os.path.isdir(root):
        return f"删除根目录不存在或不是目录：{root}"
    if not os.access(root, os.R_OK | os.X_OK):
        return f"删除根目录读不了：{root}"
    # 只读挂载时 115 删完、本地删不掉，所以开始前就要确认能写
    if not os.access(root, os.W_OK):
        return f"删除根目录写不了：{root}"
    return None


def recover_interrupted_batches(db: Session) -> int:
    """服务启动时把停在执行中 / 待开始的删除批次标为中断（不 commit），返回改了几个。

    进程退出后这些批次不会再有人执行，标为中断后网页上可以点「重试失败的」续跑。
    """
    batches = db.scalars(select(ActressDeleteBatch).where(ActressDeleteBatch.status.in_(("running", "pending")))).all()
    for batch in batches:
        batch.status = "interrupted"
        batch.note = "服务重启时中断"
        batch.finished_at = _now()
    return len(batches)


class DeleteBatchService:
    """删除批次的创建与执行。"""

    def create_batch(self, db: Session, *, strm_roots: list[str], film_dirs: list[str]) -> ActressDeleteBatch:
        """只用网页上确认的这些番号目录建一个待执行批次。

        服务端的勾选标记不决定删哪些：每日任务等会往清单里加默认勾选的新片，用户在网页上没见过。
        清单为空抛 ActressError；其中任何一部已不在待删清单里抛 CandidateListChanged，一部都不建。
        """
        require_strm_roots(strm_roots, "建删除批次")
        dirs = sorted({os.path.normpath(film_dir) for film_dir in film_dirs if film_dir})
        if not dirs:
            raise ActressError("没有勾选的片子")
        listed = set(
            db.scalars(select(ActressDeleteCandidate.film_dir).where(ActressDeleteCandidate.film_dir.in_(dirs)))
        )
        gone = [film_dir for film_dir in dirs if film_dir not in listed]
        if gone:
            raise CandidateListChanged(f"清单有变化，请刷新后再确认（{len(gone)} 部已不在待删清单里）")
        batch = ActressDeleteBatch(status="pending")
        batch.films = [
            ActressDeleteBatchFilm(film_dir=film_dir, number=os.path.basename(film_dir), status="pending")
            for film_dir in dirs
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
        openlist: OpenListClient | None = None,
    ) -> BatchSummary:
        """执行（或续跑）批次：处理待执行和上次失败的片子，返回整个批次的计数。

        开始前先确认两个删除根目录都在、并建好 porn_tv1 的地址索引；
        做不到就把批次置为失败、不动任何片子，也不调用任何 115 接口。
        给了 openlist 时，每部片删完 115 文件后刷新 OpenList 里对应的目录（失败不影响删除）。
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
                openlist=openlist,
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
        openlist: OpenListClient | None = None,
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
            if openlist is not None:
                self._refresh_openlist(batch_film, openlist, urls)
            self._delete_source_strm(batch_film, guard, url_index, urls)
            self._delete_film_dir(batch_film, guard, local_dir)
            source_paths = [
                row.target
                for row in batch_film.files
                if row.group == "source_strm"
                and row.status in _DONE_FILE_STATUSES
                and os.path.isabs(row.target)
            ]
            try:
                self._clean_leftovers(
                    batch_film,
                    client_115=client_115,
                    guard=guard,
                    openlist=openlist,
                    urls=urls,
                    source_paths=source_paths,
                )
            except Exception as exc:  # noqa: BLE001 — 视频已删完，清理出意外也不能打断批次或让这部片失败
                batch_film.reason = f"清理配套文件出错：{exc}"
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

        换算后的 STRM 必须是已校验番号目录 local_dir 的直接子文件、且本身不是符号链接，否则失败。
        番号目录里还有扫描结果之外的 STRM（扫描之后新加的分段）也失败：那一段的 115 文件不会被删，
        本地目录却会整个删掉。
        """
        if not film.strm_paths:
            raise _FilmFailed("片子没有 STRM 文件")
        urls: list[str] = []
        known: set[str] = set()
        for strm_path in film.strm_paths:
            local_path = os.path.abspath(mapper.map(strm_path))
            if os.path.dirname(local_path) != local_dir:
                raise _FilmFailed(f"STRM 不在本地番号目录里：{local_path}（检查路径换算）")
            if os.path.islink(local_path):
                raise _FilmFailed(f"STRM 是符号链接，拒绝删除：{local_path}")
            url = read_strm_url(local_path)
            if url is None:
                raise _FilmFailed(f"读不到 STRM 地址：{local_path}")
            urls.append(url)
            known.add(local_path)
        try:
            names = os.listdir(local_dir)
        except OSError as exc:
            raise _FilmFailed(f"读不了本地番号目录：{local_dir}：{exc}") from exc
        extra = sorted(
            name for name in names if name.lower().endswith(".strm") and os.path.join(local_dir, name) not in known
        )
        if extra:
            raise _FilmFailed(f"番号目录里有扫描之后新加的分段，请等下次扫描：{'、'.join(extra)}")
        return urls

    @staticmethod
    def _find_file_row(
        batch_film: ActressDeleteBatchFilm, group: str, target: str
    ) -> ActressDeleteBatchFile | None:
        """取这部片同组同目标的文件行，没有返回 None。"""
        for row in batch_film.files:
            if row.group == group and row.target == target:
                return row
        return None

    @classmethod
    def _file_row(cls, batch_film: ActressDeleteBatchFilm, group: str, target: str) -> ActressDeleteBatchFile:
        """取这部片同组同目标的文件行，没有就新建一行（pending）。"""
        row = cls._find_file_row(batch_film, group, target)
        if row is not None:
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

    def _refresh_openlist(self, batch_film: ActressDeleteBatchFilm, openlist: OpenListClient, urls: list[str]) -> None:
        """强制刷新 OpenList 里这部片的 115 文件所在目录，避免 alist-strm 按旧缓存把 STRM 生成回来。

        同一目录只刷一次；续跑时已刷新过的目录不再刷。刷新失败只记在这一行上，不让这部片失败。
        """
        dirs = dict.fromkeys(openlist_dir_for(url) for url in urls)
        for path in dirs:
            row = self._file_row(batch_film, "openlist_dir", path)
            if row.status == "refreshed":
                continue
            row.executed_at = _now()
            try:
                openlist.refresh_dir(path)
            except Exception as exc:  # noqa: BLE001 — 刷新失败不影响删除，最坏是片子回来后再删一次本地
                row.status = "failed"
                row.error = str(exc)
                continue
            row.status = "refreshed"
            row.error = None

    def _delete_source_strm(
        self,
        batch_film: ActressDeleteBatchFilm,
        guard: FilmDeleteGuard,
        url_index: dict[str, list[str]],
        urls: list[str],
    ) -> None:
        """删 porn_tv1 里地址相同的 STRM；某个地址一个都没找到时记一条 missing 行（不算失败）。

        missing 行只在第一次走到这一步时记：续跑时上次已删掉的 STRM 本来就找不到，不能再记成没找到。
        """
        first_attempt = not any(row.group == "source_strm" for row in batch_film.files)
        for url in dict.fromkeys(urls):
            if not first_attempt or url_index.get(normalize_stream_url(url)):
                continue
            row = self._file_row(batch_film, "source_strm", url)
            row.executed_at = _now()
            row.status = "missing"
            row.error = "porn_tv1 里没找到对应 STRM"
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

    def _clean_leftovers(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        client_115: Real115Client | Fake115Client,
        guard: FilmDeleteGuard,
        openlist: OpenListClient | None,
        urls: list[str],
        source_paths: list[str],
        require_refreshed: bool = True,
    ) -> list[LeftoverAction]:
        """清理这部片在 115 和 porn_tv1 留下的 nfo、图片、字幕，返回本次确实删掉的动作。

        不抛异常、不 commit：失败只记在对应文件行上，这部片仍算删除成功。
        require_refreshed 为 False 时由调用方（补跑）自己先刷新 OpenList。
        """
        actions: list[LeftoverAction] = []
        self._clean_remote_leftovers(
            batch_film,
            client_115=client_115,
            openlist=openlist,
            urls=urls,
            require_refreshed=require_refreshed,
            actions=actions,
        )
        self._clean_source_leftovers(batch_film, guard=guard, source_paths=source_paths, actions=actions)
        return actions

    def _clean_remote_leftovers(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        client_115: Real115Client | Fake115Client,
        openlist: OpenListClient | None,
        urls: list[str],
        require_refreshed: bool,
        actions: list[LeftoverAction],
    ) -> None:
        """按 115 目录去重清理：整目录条件满足时删目录，否则只删同名配套文件。"""
        directories: dict[tuple[str, str], list[str]] = {}
        for url in dict.fromkeys(urls):
            try:
                decoded = decode_115_open_path(url)
                openlist_dir = openlist_dir_for(url)
            except ValueError:
                continue
            directory = os.path.dirname(decoded.remote_path) or "/"
            directories.setdefault((openlist_dir, directory), []).append(os.path.basename(decoded.remote_path))

        for (openlist_dir, directory), video_names in directories.items():
            directory_row = self._find_file_row(batch_film, "remote_leftover", directory)
            # 续跑：整个目录上次已删或已不存在，不再列目录、也不再删
            if directory_row is not None and directory_row.status in _DONE_FILE_STATUSES:
                continue
            if openlist is None:
                row = self._file_row(batch_film, "remote_leftover", directory)
                row.executed_at = _now()
                row.status = "skipped"
                row.error = "没配置 OpenList，未清理 115 配套文件"
                continue
            if require_refreshed:
                refresh_row = self._find_file_row(batch_film, "openlist_dir", openlist_dir)
                if refresh_row is None or refresh_row.status != "refreshed":
                    row = self._file_row(batch_film, "remote_leftover", directory)
                    row.executed_at = _now()
                    row.status = "skipped"
                    row.error = "OpenList 没刷新成功，未清理 115 配套文件"
                    continue
            try:
                entries = openlist.list_dir(openlist_dir)
            except Exception as exc:  # noqa: BLE001 — 列目录失败只记这一行
                row = self._file_row(batch_film, "remote_leftover", directory)
                row.executed_at = _now()
                row.status = "failed"
                row.error = f"列 115 目录失败：{exc}"
                continue

            plan = plan_dir(video_names, entries)
            if plan.whole_dir:
                if directory == "/":
                    row = self._file_row(batch_film, "remote_leftover", directory)
                    row.executed_at = _now()
                    row.status = "skipped"
                    row.error = "115 根目录不删，未清理配套文件"
                    continue
                action = self._delete_remote_leftover_dir(
                    batch_film,
                    client_115=client_115,
                    openlist=openlist,
                    openlist_dir=openlist_dir,
                    directory=directory,
                    directory_row=directory_row,
                )
                if action is not None:
                    actions.append(action)
                continue

            # 之前列目录失败留下的目录行，这次能列出且不满足整删，不再算失败
            if directory_row is not None:
                directory_row.executed_at = _now()
                directory_row.status = "skipped"
                directory_row.error = "目录里还有别的文件，只清理同名配套文件"
            for name in plan.names:
                self._delete_remote_leftover_file(
                    batch_film,
                    client_115=client_115,
                    directory=directory,
                    name=name,
                    actions=actions,
                )

    def _delete_remote_leftover_dir(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        client_115: Real115Client | Fake115Client,
        openlist: OpenListClient,
        openlist_dir: str,
        directory: str,
        directory_row: ActressDeleteBatchFile | None,
    ) -> LeftoverAction | None:
        """按路径确认是文件夹后整个删掉，再刷新上级目录；任何失败只记在这一行。"""
        row = directory_row or self._file_row(batch_film, "remote_leftover", directory)
        row.executed_at = _now()
        state, file_id, note = _lookup_115(client_115, directory, expect_dir=True)
        if state == "missing":
            row.status = "missing"
            row.error = note
            return None
        if state == "error":
            row.status = "failed"
            row.error = note
            return None
        row.remote_file_id = file_id
        try:
            outcome = client_115.delete_node(file_id, dry_run=False)
        except Exception as exc:  # noqa: BLE001 — 删除失败只记在这一行
            row.status = "failed"
            row.error = str(exc)
            return None
        if not getattr(outcome, "success", False):
            row.status = "failed"
            row.error = getattr(outcome, "message", None) or "115 删除没有成功"
            return None
        row.status = "deleted"
        row.error = None
        parent = os.path.dirname(openlist_dir) or "/"
        try:
            openlist.refresh_dir(parent)
        except Exception as exc:  # noqa: BLE001 — 目录已删掉，刷新失败只追加原因
            row.error = f"目录已删除，但刷新 OpenList 上级目录失败：{exc}"
        return LeftoverAction(group="remote_leftover", target=directory, whole_dir=True)

    def _delete_remote_leftover_file(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        client_115: Real115Client | Fake115Client,
        directory: str,
        name: str,
        actions: list[LeftoverAction],
    ) -> None:
        """按完整路径确认是文件后删除一个同名配套文件。"""
        target = f"/{name}" if directory == "/" else f"{directory}/{name}"
        row = self._file_row(batch_film, "remote_leftover", target)
        if row.status in _DONE_FILE_STATUSES:
            return
        row.executed_at = _now()
        state, file_id, note = _lookup_115(client_115, target, expect_dir=False)
        if state == "missing":
            row.status = "missing"
            row.error = note
            return
        if state == "error":
            row.status = "failed"
            row.error = note
            return
        row.remote_file_id = file_id
        try:
            outcome = client_115.delete_node(file_id, dry_run=False)
        except Exception as exc:  # noqa: BLE001 — 删除失败只记在这一行
            row.status = "failed"
            row.error = str(exc)
            return
        if not getattr(outcome, "success", False):
            row.status = "failed"
            row.error = getattr(outcome, "message", None) or "115 删除没有成功"
            return
        row.status = "deleted"
        row.error = None
        actions.append(LeftoverAction(group="remote_leftover", target=target, whole_dir=False))

    def _clean_source_leftovers(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        guard: FilmDeleteGuard,
        source_paths: list[str],
        actions: list[LeftoverAction],
    ) -> None:
        """按 porn_tv1 源目录去重清理；目录不存在记 missing，不报错。"""
        directories: dict[str, list[str]] = {}
        for path in dict.fromkeys(source_paths):
            directory = os.path.dirname(path)
            if not directory:
                continue
            directories.setdefault(directory, []).append(os.path.basename(path))

        for directory, video_names in directories.items():
            directory_row = self._find_file_row(batch_film, "source_leftover", directory)
            if directory_row is not None and directory_row.status in _DONE_FILE_STATUSES:
                continue
            if not os.path.isdir(directory):
                row = directory_row or self._file_row(batch_film, "source_leftover", directory)
                row.executed_at = _now()
                row.status = "missing"
                row.error = "源目录已不存在"
                continue
            try:
                entries = [
                    (name, os.path.isdir(os.path.join(directory, name))) for name in os.listdir(directory)
                ]
            except OSError as exc:
                row = directory_row or self._file_row(batch_film, "source_leftover", directory)
                row.executed_at = _now()
                row.status = "failed"
                row.error = f"读不了源目录：{exc}"
                continue

            plan = plan_dir(video_names, entries)
            if plan.whole_dir:
                row = directory_row or self._file_row(batch_film, "source_leftover", directory)
                row.executed_at = _now()
                try:
                    row.status = guard.delete_source_dir(directory)
                    row.error = None
                except (GuardError, OSError) as exc:
                    row.status = "failed"
                    row.error = str(exc)
                    continue
                if row.status == "deleted":
                    actions.append(LeftoverAction(group="source_leftover", target=directory, whole_dir=True))
                continue

            # 之前列目录失败留下的目录行，这次能列出且不满足整删，不再算失败
            if directory_row is not None:
                directory_row.executed_at = _now()
                directory_row.status = "skipped"
                directory_row.error = "目录里还有别的文件，只清理同名配套文件"
            for name in plan.names:
                path = os.path.join(directory, name)
                row = self._file_row(batch_film, "source_leftover", path)
                if row.status in _DONE_FILE_STATUSES:
                    continue
                row.executed_at = _now()
                try:
                    row.status = guard.delete_source_sidecar(path)
                    row.error = None
                except (GuardError, OSError) as exc:
                    row.status = "failed"
                    row.error = str(exc)
                    continue
                if row.status == "deleted":
                    actions.append(LeftoverAction(group="source_leftover", target=path, whole_dir=False))

    def clean_leftovers(
        self,
        db: Session,
        batch_id: int,
        *,
        client_115: Real115Client | Fake115Client,
        guard: FilmDeleteGuard,
        openlist: OpenListClient | None,
        apply: bool = False,
    ) -> list[LeftoverAction]:
        """给已完成的批次补跑清理：只处理已删除的片子，默认只预览、不删也不写文件行。

        补跑不要求批次里已有「OpenList 已刷新」行，会先自己刷新每个 115 目录；
        刷新失败的目录这次不清理（宁可少删）。
        """
        batch = db.get(ActressDeleteBatch, batch_id)
        if batch is None:
            raise ActressError(f"删除批次不存在：{batch_id}")

        actions: list[LeftoverAction] = []
        seen: set[tuple[str, str]] = set()
        for batch_film in batch.films:
            if batch_film.status != "deleted":
                continue
            urls = [row.target for row in batch_film.files if row.group == "remote_115"]
            source_paths = [
                row.target
                for row in batch_film.files
                if row.group == "source_strm"
                and row.status in _DONE_FILE_STATUSES
                and os.path.isabs(row.target)
            ]
            if not urls and not source_paths:
                continue
            if openlist is not None:
                urls = self._refresh_for_cleanup(openlist, urls)
            if apply:
                performed = self._clean_leftovers(
                    batch_film,
                    client_115=client_115,
                    guard=guard,
                    openlist=openlist,
                    urls=urls,
                    source_paths=source_paths,
                    require_refreshed=False,
                )
                db.commit()
            else:
                performed = self._preview_leftovers(
                    batch_film,
                    openlist=openlist,
                    urls=urls,
                    source_paths=source_paths,
                )
            for action in performed:
                key = (action.group, action.target)
                if key not in seen:
                    seen.add(key)
                    actions.append(action)
        return actions

    @staticmethod
    def _refresh_for_cleanup(openlist: OpenListClient, urls: list[str]) -> list[str]:
        """刷新每个 115 目录一次，返回刷新成功的那些 URL；失败的目录这次不清理。"""
        states: dict[str, bool] = {}
        refreshed: list[str] = []
        for url in dict.fromkeys(urls):
            try:
                directory = openlist_dir_for(url)
            except ValueError:
                continue
            if directory not in states:
                try:
                    openlist.refresh_dir(directory)
                    states[directory] = True
                except Exception:  # noqa: BLE001 — 刷新失败只表示这次不清理这个目录
                    states[directory] = False
            if states[directory]:
                refreshed.append(url)
        return refreshed

    def _preview_leftovers(
        self,
        batch_film: ActressDeleteBatchFilm,
        *,
        openlist: OpenListClient | None,
        urls: list[str],
        source_paths: list[str],
    ) -> list[LeftoverAction]:
        """只列目录、判断会删什么，不调用任何删除、刷新或写库。"""
        actions: list[LeftoverAction] = []
        directories: dict[tuple[str, str], list[str]] = {}
        for url in dict.fromkeys(urls):
            try:
                decoded = decode_115_open_path(url)
                openlist_dir = openlist_dir_for(url)
            except ValueError:
                continue
            directory = os.path.dirname(decoded.remote_path) or "/"
            directories.setdefault((openlist_dir, directory), []).append(os.path.basename(decoded.remote_path))

        if openlist is not None:
            for (openlist_dir, directory), video_names in directories.items():
                directory_row = self._find_file_row(batch_film, "remote_leftover", directory)
                if directory_row is not None and directory_row.status in _DONE_FILE_STATUSES:
                    continue
                try:
                    entries = openlist.list_dir(openlist_dir)
                except Exception:  # noqa: BLE001 — 预览拿不到列表就不显示这个目录
                    continue
                plan = plan_dir(video_names, entries)
                if plan.whole_dir:
                    if directory != "/":
                        actions.append(LeftoverAction("remote_leftover", directory, True))
                    continue
                for name in plan.names:
                    target = f"/{name}" if directory == "/" else f"{directory}/{name}"
                    row = self._find_file_row(batch_film, "remote_leftover", target)
                    if row is not None and row.status in _DONE_FILE_STATUSES:
                        continue
                    actions.append(LeftoverAction("remote_leftover", target, False))

        source_dirs: dict[str, list[str]] = {}
        for path in dict.fromkeys(source_paths):
            directory = os.path.dirname(path)
            if directory:
                source_dirs.setdefault(directory, []).append(os.path.basename(path))
        for directory, video_names in source_dirs.items():
            directory_row = self._find_file_row(batch_film, "source_leftover", directory)
            if directory_row is not None and directory_row.status in _DONE_FILE_STATUSES:
                continue
            if not os.path.isdir(directory):
                continue
            try:
                entries = [
                    (name, os.path.isdir(os.path.join(directory, name))) for name in os.listdir(directory)
                ]
            except OSError:
                continue
            plan = plan_dir(video_names, entries)
            if plan.whole_dir:
                actions.append(LeftoverAction("source_leftover", directory, True))
                continue
            for name in plan.names:
                path = os.path.join(directory, name)
                row = self._find_file_row(batch_film, "source_leftover", path)
                if row is not None and row.status in _DONE_FILE_STATUSES:
                    continue
                actions.append(LeftoverAction("source_leftover", path, False))
        return actions
