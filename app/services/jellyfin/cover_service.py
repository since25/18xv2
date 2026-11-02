from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import uuid

from PIL import Image, ImageFilter, ImageStat
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jellyfin import JellyfinMediaItem
from app.services.jellyfin.scan_service import VIDEO_EXTENSIONS


logger = logging.getLogger(__name__)

_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_COVER_VIDEO_EXTENSIONS = VIDEO_EXTENSIONS - {".iso"}
_FRAME_COUNT = 12

CommandRunner = Callable[[list[str], float], subprocess.CompletedProcess]


class CoverGenerationError(Exception):
    """单个视频封面生成失败。"""


@dataclass(frozen=True)
class _FrameScore:
    path: Path
    mean: float
    stddev: float
    laplacian_variance: float


def _run_command(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def _priority_prefix() -> list[str]:
    prefix: list[str] = []
    if shutil.which("nice"):
        prefix.extend(["nice", "-n", "19"])
    if shutil.which("ionice"):
        prefix.extend(["ionice", "-c3"])
    return prefix


def _parse_since(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("JELLYFIN_COVER_SINCE 必须包含时区")
    return parsed.astimezone(UTC)


class CoverService:
    """为本地媒体生成旁路 JPEG 封面。"""

    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        now_fn: Callable[[], datetime] | None = None,
        command_timeout_seconds: float = 120.0,
    ):
        self.command_runner = command_runner or _run_command
        self.now_fn = now_fn or (lambda: datetime.now().astimezone())
        self.command_timeout_seconds = command_timeout_seconds

    def run(
        self,
        db: Session,
        local_roots: list[str],
        *,
        since: str | datetime | None,
        deadline_minute: int = 25,
    ) -> dict[str, int]:
        """扫描新入库视频并生成封面，返回本次任务摘要。"""
        summary = {
            "candidates": 0,
            "generated": 0,
            "existing_cover_skipped": 0,
            "existing_video_skipped": 0,
            "fallback_middle_frames": 0,
            "failed": 0,
            "deadline_remaining": 0,
            "filename_too_long_skipped": 0,
        }
        try:
            cover_since = _parse_since(since)
        except ValueError as exc:
            logger.error("封面任务配置无效，功能关闭: %s", exc)
            return summary
        if cover_since is None:
            return summary
        started_at = self.now_fn()
        deadline_at = self._deadline_at(started_at, deadline_minute)
        deadline_reached_at_start = started_at >= deadline_at

        eligible: list[Path] = []
        for video_path in self._iter_videos(local_roots):
            item = db.scalar(
                select(JellyfinMediaItem).where(
                    JellyfinMediaItem.source == "local",
                    JellyfinMediaItem.path == os.path.normpath(os.fspath(video_path)),
                )
            )
            if item is not None and not self._is_recent_item(item, cover_since):
                summary["existing_video_skipped"] += 1
                continue
            summary["candidates"] += 1
            eligible.append(video_path)
        eligible.sort()

        for index, video_path in enumerate(eligible):
            if deadline_reached_at_start or self._past_deadline(deadline_at):
                summary["deadline_remaining"] += len(eligible) - index
                break
            try:
                outcome = self._process_video(video_path, local_roots)
                if outcome == "generated":
                    summary["generated"] += 1
                elif outcome == "existing_cover":
                    summary["existing_cover_skipped"] += 1
                elif outcome == "filename_too_long":
                    summary["filename_too_long_skipped"] += 1
                elif outcome == "fallback":
                    summary["generated"] += 1
                    summary["fallback_middle_frames"] += 1
            except Exception as exc:  # noqa: BLE001 - 单个媒体失败不影响下一项
                summary["failed"] += 1
                logger.warning("生成视频封面失败 %s: %s", video_path, exc)
        return summary

    def _process_video(self, video_path: Path, roots: list[str]) -> str:
        video_path = Path(video_path)
        target = video_path.with_name(f"{video_path.stem}-poster.jpg")
        if not self._target_is_under_root(target, roots):
            raise CoverGenerationError(f"封面目标路径不在配置根目录内: {target}")
        if len(os.fsencode(target.name)) > 255:
            return "filename_too_long"
        if self._has_adjacent_cover(video_path):
            return "existing_cover"

        with tempfile.TemporaryDirectory(prefix="18x-cover-") as temporary_directory:
            temporary_root = Path(temporary_directory)
            duration = self._probe_duration(video_path)
            frame_paths: list[Path] = []
            for index in range(_FRAME_COUNT):
                ratio = 0.05 + (0.90 - 0.05) * index / (_FRAME_COUNT - 1)
                frame_path = temporary_root / f"frame-{index:02d}.jpg"
                if self._extract_frame(video_path, duration * ratio, frame_path):
                    frame_paths.append(frame_path)

            selected = self._select_best_frame(frame_paths)
            fallback = False
            if selected is None:
                middle_path = temporary_root / "frame-middle.jpg"
                if not self._extract_frame(video_path, duration * 0.50, middle_path):
                    raise CoverGenerationError("无法取得候选帧或中间帧")
                selected = middle_path
                fallback = True
            if not self._write_cover(selected, target):
                return "existing_cover"
            return "fallback" if fallback else "generated"

    def _probe_duration(self, video_path: Path) -> float:
        result = self._call(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                os.fspath(video_path),
            ]
        )
        output = (result.stdout or "").strip()
        try:
            duration = float(output.splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise CoverGenerationError("ffprobe 未返回有效时长") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise CoverGenerationError("视频时长无效")
        return duration

    def _extract_frame(self, video_path: Path, timestamp: float, output_path: Path) -> bool:
        try:
            self._call(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    os.fspath(video_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=720:-2",
                    "-q:v",
                    "2",
                    "-y",
                    os.fspath(output_path),
                ]
            )
            return output_path.is_file() and output_path.stat().st_size > 0
        except Exception as exc:  # noqa: BLE001 - 允许继续尝试其它时间点
            logger.debug("抽帧失败 %s @ %.3fs: %s", video_path, timestamp, exc)
            return False

    def _call(self, command: list[str]) -> subprocess.CompletedProcess:
        args = _priority_prefix() + command
        result = self.command_runner(args, self.command_timeout_seconds)
        if getattr(result, "returncode", 0) != 0:
            raise CoverGenerationError(f"命令失败: {command[0]}")
        return result

    @staticmethod
    def _select_best_frame(frame_paths: list[Path]) -> Path | None:
        scored: list[_FrameScore] = []
        for path in frame_paths:
            try:
                with Image.open(path) as image:
                    grayscale = image.convert("L")
                    stats = ImageStat.Stat(grayscale)
                    scored.append(
                        _FrameScore(
                            path=path,
                            mean=float(stats.mean[0]),
                            stddev=float(stats.stddev[0]),
                            laplacian_variance=CoverService._laplacian_variance(grayscale),
                        )
                    )
            except (OSError, ValueError):
                continue

        usable = [
            score
            for score in scored
            if score.mean >= 35 and score.mean <= 225 and score.stddev >= 22
        ]
        if not usable:
            return None
        median = statistics.median(score.laplacian_variance for score in usable)
        sharp_enough = [score for score in usable if score.laplacian_variance >= median * 0.35]
        if not sharp_enough:
            return None
        return max(sharp_enough, key=lambda score: score.laplacian_variance).path

    @staticmethod
    def _laplacian_variance(image: Image.Image) -> float:
        grayscale = image.convert("L")
        filtered = grayscale.filter(
            ImageFilter.Kernel(
                (3, 3),
                (0, 1, 0, 1, -4, 1, 0, 1, 0),
                scale=1,
                offset=128,
            )
        )
        return float(ImageStat.Stat(filtered).var[0])

    def _write_cover(self, frame_path: Path, target: Path) -> bool:
        temporary_path = target.parent / f".18x-cover-{uuid.uuid4().hex}.tmp"
        try:
            with Image.open(frame_path) as image:
                image.convert("RGB").save(temporary_path, format="JPEG", quality=90)
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                return False
            try:
                os.chmod(target, 0o664)
            except OSError:
                logger.warning("无法设置封面权限: %s", target)
            try:
                os.chown(target, 99, 100)
            except (AttributeError, OSError):
                logger.debug("无法设置封面属主: %s", target)
            return True
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("无法清理封面临时文件: %s", temporary_path)

    def _iter_videos(self, local_roots: list[str]) -> Iterator[Path]:
        for configured_root in local_roots:
            if not configured_root:
                continue
            root = Path(configured_root).absolute()
            if not root.is_dir():
                logger.warning("封面任务跳过无效媒体根目录: %s", configured_root)
                continue
            pending = [root]
            while pending:
                directory = pending.pop()
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in _COVER_VIDEO_EXTENSIONS:
                                yield Path(os.path.normpath(entry.path))
                except OSError as exc:
                    logger.warning("封面任务无法读取媒体目录 %s: %s", directory, exc)

    @staticmethod
    def _is_recent_item(item: JellyfinMediaItem, since: datetime) -> bool:
        first_seen = item.first_seen_at
        if first_seen is None:
            return False
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=UTC)
        return first_seen.astimezone(UTC) >= since

    def _past_deadline(self, deadline_at: datetime) -> bool:
        now = self.now_fn()
        return now >= deadline_at

    @staticmethod
    def _deadline_at(started_at: datetime, deadline_minute: int) -> datetime:
        return started_at.replace(minute=int(deadline_minute), second=0, microsecond=0)

    @staticmethod
    def _target_is_under_root(target: Path, roots: list[str]) -> bool:
        target_path = os.path.realpath(os.fspath(target))
        for root in roots:
            if not root:
                continue
            root_path = os.path.realpath(os.fspath(root))
            try:
                if os.path.commonpath([target_path, root_path]) == root_path:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _has_adjacent_cover(video_path: Path) -> bool:
        names = {video_path.stem, f"{video_path.stem}-poster", f"{video_path.stem}-thumb"}
        try:
            entries = video_path.parent.iterdir()
        except OSError:
            return False
        for entry in entries:
            if entry.is_file() and entry.stem in names and entry.suffix.lower() in _COVER_EXTENSIONS:
                return True
        return False
