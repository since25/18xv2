from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.jellyfin import JellyfinMediaItem, JellyfinMediaKeyword
from app.services.emby_media_actions.nfo_parser import parse_nfo_actors
from app.services.jellyfin.matcher import build_keyword_index, match_local_folder, match_strm_item


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".ts",
    ".m2ts",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".rmvb",
    ".iso",
}


class MediaScanError(Exception):
    """媒体根目录无效或扫描过程中无法读取文件。"""


class MediaScanService:
    """扫描本地视频和 115 STRM 文件，并保存当前匹配结果。"""

    def scan(
        self,
        db: Session,
        *,
        local_roots: list[str],
        strm_roots: list[str],
        job_id: str | None = None,
        batch_size: int = 500,
    ) -> dict:
        """扫描配置根目录，返回本次扫描的统计信息。"""
        scan_job_id = job_id or str(uuid.uuid4())
        commit_size = max(1, batch_size)
        result = {
            "local_files": 0,
            "strm_files": 0,
            "matched": 0,
            "unmatched": 0,
            "nfo_error": 0,
            "deactivated": 0,
        }
        keyword_index = build_keyword_index(db)
        pending = 0

        for configured_root in local_roots:
            media_count = 0
            for path, folder_name in self._iter_local_media(configured_root):
                media_count += 1
                matches = match_local_folder(folder_name, keyword_index) if folder_name is not None else []
                match_state = "matched" if matches else "unmatched"
                self._save_item(
                    db,
                    source="local",
                    path=path,
                    job_id=scan_job_id,
                    match_state=match_state,
                    matches=[(keyword_id, raw_term, "folder_segment") for keyword_id, raw_term in matches],
                )
                result["local_files"] += 1
                result[match_state] += 1
                pending += 1
                if pending >= commit_size:
                    db.commit()
                    pending = 0
            if media_count == 0:
                raise MediaScanError(f"媒体根目录不存在、不可读或为空: {configured_root}")
            if pending:
                db.commit()
                pending = 0

        for configured_root in strm_roots:
            media_count = 0
            for path, folder_name in self._iter_strm_media(configured_root):
                media_count += 1
                matches, match_state = self._match_strm_file(path, folder_name, keyword_index)
                self._save_item(
                    db,
                    source="strm_115",
                    path=path,
                    job_id=scan_job_id,
                    match_state=match_state,
                    matches=matches,
                )
                result["strm_files"] += 1
                result[match_state] += 1
                pending += 1
                if pending >= commit_size:
                    db.commit()
                    pending = 0
            if media_count == 0:
                raise MediaScanError(f"媒体根目录不存在、不可读或为空: {configured_root}")
            if pending:
                db.commit()
                pending = 0

        roots_by_source = {
            "local": local_roots,
            "strm_115": strm_roots,
        }
        result["deactivated"] = self._deactivate_missing(db, scan_job_id, roots_by_source)
        db.commit()
        return result

    def _iter_local_media(self, configured_root: str) -> Iterator[tuple[str, str | None]]:
        root = self._validate_root(configured_root)
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._walk_video_files(entry.path, entry.name)
                    elif entry.is_file(follow_symlinks=False) and self._is_video_file(entry.name):
                        yield os.path.normpath(entry.path), None
        except OSError as exc:
            raise MediaScanError(f"无法读取媒体根目录: {configured_root}") from exc

    def _iter_strm_media(self, configured_root: str) -> Iterator[tuple[str, str | None]]:
        root = self._validate_root(configured_root)
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._walk_strm_files(entry.path, entry.name)
                    elif entry.is_file(follow_symlinks=False) and self._is_strm_file(entry.name):
                        yield os.path.normpath(entry.path), None
        except OSError as exc:
            raise MediaScanError(f"无法读取媒体根目录: {configured_root}") from exc

    def _walk_video_files(self, directory: str, folder_name: str) -> Iterator[tuple[str, str]]:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._walk_video_files(entry.path, folder_name)
                    elif entry.is_file(follow_symlinks=False) and self._is_video_file(entry.name):
                        yield os.path.normpath(entry.path), folder_name
        except OSError as exc:
            raise MediaScanError(f"无法读取媒体目录: {directory}") from exc

    def _walk_strm_files(self, directory: str, folder_name: str) -> Iterator[tuple[str, str]]:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._walk_strm_files(entry.path, folder_name)
                    elif entry.is_file(follow_symlinks=False) and self._is_strm_file(entry.name):
                        yield os.path.normpath(entry.path), folder_name
        except OSError as exc:
            raise MediaScanError(f"无法读取媒体目录: {directory}") from exc

    @staticmethod
    def _validate_root(configured_root: str) -> str:
        if not configured_root:
            raise MediaScanError("媒体根目录为空")
        root = os.path.abspath(os.fspath(configured_root))
        try:
            if not os.path.isdir(root) or not os.access(root, os.R_OK | os.X_OK):
                raise MediaScanError(f"媒体根目录不存在、不可读或不是目录: {configured_root}")
            with os.scandir(root):
                pass
        except MediaScanError:
            raise
        except OSError as exc:
            raise MediaScanError(f"媒体根目录不存在、不可读或不是目录: {configured_root}") from exc
        return root

    @staticmethod
    def _is_video_file(name: str) -> bool:
        return Path(name).suffix.lower() in VIDEO_EXTENSIONS

    @staticmethod
    def _is_strm_file(name: str) -> bool:
        return Path(name).suffix.lower() == ".strm"

    def _match_strm_file(
        self,
        path: str,
        folder_name: str | None,
        keyword_index: dict[str, int],
    ) -> tuple[list[tuple[int, str, str]], str]:
        actor_names: list[str] | None
        nfo_path = str(Path(path).with_suffix(".nfo"))
        if not os.path.isfile(nfo_path):
            actor_names = []
        else:
            try:
                xml_text = Path(nfo_path).read_text(encoding="utf-8")
                actor_names = [actor.name for actor in parse_nfo_actors(xml_text)]
            except Exception:
                actor_names = None
        return match_strm_item(actor_names, folder_name or "", keyword_index)

    @staticmethod
    def _save_item(
        db: Session,
        *,
        source: str,
        path: str,
        job_id: str,
        match_state: str,
        matches: list[tuple[int, str, str]],
    ) -> None:
        try:
            stat = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise MediaScanError(f"无法读取媒体文件属性: {path}") from exc
        item = db.scalar(
            select(JellyfinMediaItem).where(
                JellyfinMediaItem.source == source,
                JellyfinMediaItem.path == path,
            )
        )
        if item is None:
            item = JellyfinMediaItem(source=source, path=path)
            db.add(item)
            db.flush()
        item.file_ext = Path(path).suffix.lower() or None
        item.size = stat.st_size
        item.mtime = stat.st_mtime
        item.last_seen_at = datetime.now(timezone.utc)
        item.last_seen_job_id = job_id
        item.active = True
        item.match_state = match_state
        item.match_note = None
        db.execute(delete(JellyfinMediaKeyword).where(JellyfinMediaKeyword.media_item_id == item.id))
        db.expire(item, ["keyword_links"])
        for keyword_entry_id, raw_term, match_source in matches:
            db.add(
                JellyfinMediaKeyword(
                    media_item_id=item.id,
                    keyword_entry_id=keyword_entry_id,
                    match_source=match_source,
                    raw_term=raw_term,
                )
            )

    @staticmethod
    def _deactivate_missing(
        db: Session,
        job_id: str,
        roots_by_source: dict[str, list[str]],
    ) -> int:
        sources = [source for source, roots in roots_by_source.items() if roots]
        if not sources:
            return 0
        items = db.scalars(
            select(JellyfinMediaItem).where(
                JellyfinMediaItem.source.in_(sources),
                JellyfinMediaItem.active.is_(True),
            )
        ).all()
        deactivated = 0
        for item in items:
            if item.last_seen_job_id == job_id:
                continue
            roots = roots_by_source[item.source]
            if any(MediaScanService._path_is_under(item.path, root) for root in roots):
                item.active = False
                deactivated += 1
        return deactivated

    @staticmethod
    def _path_is_under(path: str, root: str) -> bool:
        try:
            return os.path.commonpath([os.path.abspath(path), os.path.abspath(os.fspath(root))]) == os.path.abspath(
                os.fspath(root)
            )
        except ValueError:
            return False
