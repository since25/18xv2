from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest
from PIL import Image, ImageFilter, ImageStat

from app.models.jellyfin import JellyfinMediaItem
from app.services.jellyfin import cover_service
from app.services.jellyfin.cover_service import CoverService


UTC = timezone.utc


class FakeCommands:
    def __init__(self, frame_kinds: list[str], *, duration: float = 100.0):
        self.frame_kinds = frame_kinds
        self.duration = duration
        self.calls: list[list[str]] = []
        self.frame_index = 0

    def __call__(self, args: list[str], timeout: float):
        self.calls.append(args)
        if "ffprobe" in args:
            return subprocess.CompletedProcess(args, 0, stdout=f"{self.duration}\n", stderr="")
        if "ffmpeg" not in args:
            raise AssertionError(args)
        output = Path(args[-1])
        kind = self.frame_kinds[min(self.frame_index, len(self.frame_kinds) - 1)]
        self.frame_index += 1
        _write_frame(output, kind)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def _write_frame(path: Path, kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (32, 32), 128)
    pixels = image.load()
    if kind == "dark":
        image = Image.new("L", (32, 32), 20)
    elif kind == "bright":
        image = Image.new("L", (32, 32), 240)
    elif kind == "flat":
        image = Image.new("L", (32, 32), 120)
    elif kind == "soft":
        for y in range(32):
            for x in range(32):
                pixels[x, y] = 35 + int(180 * x / 31)
    elif kind == "sharp":
        for y in range(32):
            for x in range(32):
                pixels[x, y] = 20 if (x + y) % 2 else 235
    image.save(path, format="JPEG")


def _video(root: Path, name: str = "movie.mp4") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def _service(fake: FakeCommands, now: datetime | None = None) -> CoverService:
    return CoverService(command_runner=fake, now_fn=lambda: now or datetime(2026, 1, 1, 2, 0, tzinfo=UTC))


def test_cover_generation_skips_existing_video_and_empty_since(db_session, tmp_path):
    root = tmp_path / "media"
    old_video = _video(root, "old.mp4")
    empty_since_fake = FakeCommands(["sharp"] * 12)
    empty_summary = _service(empty_since_fake).run(db_session, [str(root)], since="")
    assert empty_summary["generated"] == 0
    assert not old_video.with_name("old-poster.jpg").exists()

    db_session.add(
        JellyfinMediaItem(
            source="local",
            path=str(old_video),
            first_seen_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    db_session.commit()
    existing_fake = FakeCommands(["sharp"] * 12)
    summary = _service(existing_fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")
    assert summary["generated"] == 0
    assert summary["existing_video_skipped"] == 1
    assert existing_fake.calls == []


def test_cover_generation_skips_adjacent_cover_and_never_overwrites_target(db_session, tmp_path):
    root = tmp_path / "media"
    covered = _video(root, "covered.mkv")
    covered.with_name("covered.JpG").write_bytes(b"cover")
    target = _video(root, "target.mp4").with_name("target-poster.jpg")
    target.write_bytes(b"original")
    target_video = target.with_name("target.mp4")
    fake = FakeCommands(["sharp"] * 12)

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["existing_cover_skipped"] == 2
    assert summary["generated"] == 0
    assert target.read_bytes() == b"original"
    assert target_video.exists()
    assert fake.calls == []


@pytest.mark.parametrize("cover_suffix", [".jpeg", ".PNG", ".webp", ".JPG"])
def test_cover_generation_skips_all_adjacent_cover_names(db_session, tmp_path, cover_suffix):
    root = tmp_path / "media"
    video = _video(root)
    video.with_name(f"movie-thumb{cover_suffix}").write_bytes(b"cover")
    fake = FakeCommands(["sharp"] * 12)

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["existing_cover_skipped"] == 1
    assert summary["generated"] == 0
    assert fake.calls == []


def test_cover_generation_excludes_iso(db_session, tmp_path):
    root = tmp_path / "media"
    _video(root, "disc.iso")
    fake = FakeCommands(["sharp"] * 12)

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["candidates"] == 0
    assert fake.calls == []


def test_cover_generation_filters_frames_and_cleans_temp_files(db_session, tmp_path):
    root = tmp_path / "media"
    video = _video(root)
    fake = FakeCommands(["dark", "bright", "flat", "soft"] + ["sharp"] * 9)

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    output = video.with_name("movie-poster.jpg")
    assert summary["generated"] == 1
    assert summary["fallback_middle_frames"] == 0
    assert output.exists()
    assert Image.open(output).size[0] == 32
    assert not list(root.glob(".*.tmp"))
    assert all("ffprobe" in call or "ffmpeg" in call for call in fake.calls)
    assert all("-ss" in call for call in fake.calls if "ffmpeg" in call)


def test_cover_generation_falls_back_to_middle_frame_when_all_filtered(db_session, tmp_path):
    root = tmp_path / "media"
    video = _video(root)
    fake = FakeCommands(["dark"] * 12 + ["soft"])

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["generated"] == 1
    assert summary["fallback_middle_frames"] == 1
    assert abs(Image.open(video.with_name("movie-poster.jpg")).getpixel((0, 0))[0] - 35) <= 1


def test_cover_generation_failure_does_not_stop_other_videos(db_session, tmp_path):
    root = tmp_path / "media"
    first = _video(root, "first.mp4")
    second = _video(root, "second.mp4")

    class FailingFirst(FakeCommands):
        def __call__(self, args, timeout):
            if "ffprobe" in args and str(first) in args:
                raise subprocess.CalledProcessError(1, args)
            return super().__call__(args, timeout)

    fake = FailingFirst(["sharp"] * 24)
    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["failed"] == 1
    assert summary["generated"] == 1
    assert second.with_name("second-poster.jpg").exists()


def test_cover_generation_honors_deadline_before_starting_next_video(db_session, tmp_path):
    root = tmp_path / "media"
    _video(root, "first.mp4")
    second = _video(root, "second.mp4")
    times = iter(
        [
            datetime(2026, 1, 1, 2, 24, tzinfo=UTC),
            datetime(2026, 1, 1, 2, 24, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 2, 26, tzinfo=UTC),
        ]
    )
    fake = FakeCommands(["sharp"] * 12)
    summary = CoverService(command_runner=fake, now_fn=lambda: next(times)).run(
        db_session,
        [str(root)],
        since="2025-01-01T00:00:00+00:00",
        deadline_minute=25,
    )

    assert summary["generated"] == 1
    assert summary["deadline_remaining"] == 1
    assert not second.with_name("second-poster.jpg").exists()


def test_cover_generation_deadline_is_absolute_across_hour_boundary(db_session, tmp_path):
    root = tmp_path / "media"
    first = _video(root, "first.mp4")
    second = _video(root, "second.mp4")
    times = iter(
        [
            datetime(2026, 1, 1, 2, 24, 59, tzinfo=UTC),
            datetime(2026, 1, 1, 2, 24, 59, tzinfo=UTC),
            datetime(2026, 1, 1, 3, 0, 1, tzinfo=UTC),
        ]
    )
    fake = FakeCommands(["sharp"] * 12)
    summary = CoverService(command_runner=fake, now_fn=lambda: next(times)).run(
        db_session,
        [str(root)],
        since="2025-01-01T00:00:00+00:00",
        deadline_minute=25,
    )

    assert summary["generated"] == 1
    assert summary["deadline_remaining"] == 1
    assert first.with_name("first-poster.jpg").exists()
    assert not second.with_name("second-poster.jpg").exists()


def test_cover_generation_does_not_start_when_deadline_already_passed(db_session, tmp_path):
    root = tmp_path / "media"
    _video(root, "first.mp4")
    _video(root, "second.mp4")
    fake = FakeCommands(["sharp"] * 12)

    summary = _service(fake, datetime(2026, 1, 1, 2, 26, tzinfo=UTC)).run(
        db_session,
        [str(root)],
        since="2025-01-01T00:00:00+00:00",
        deadline_minute=25,
    )

    assert summary["generated"] == 0
    assert summary["deadline_remaining"] == 2
    assert fake.calls == []


def test_cover_generation_processes_eligible_videos_in_path_order(db_session, tmp_path, monkeypatch):
    root = tmp_path / "media"
    first = _video(root, "first.mp4")
    second = _video(root, "second.mp4")
    fake = FakeCommands(["sharp"] * 24)
    service = _service(fake)
    monkeypatch.setattr(service, "_iter_videos", lambda _roots: iter([second, first]))

    service.run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    ffprobe_calls = [call for call in fake.calls if "ffprobe" in call]
    assert [call[-1] for call in ffprobe_calls] == [str(first), str(second)]


def test_cover_generation_allows_target_name_of_255_bytes(db_session, tmp_path):
    root = tmp_path / "media"
    video = _video(root, "x" * 244 + ".mp4")
    target = video.with_name(f"{video.stem}-poster.jpg")
    assert len(target.name.encode()) == 255
    fake = FakeCommands(["sharp"] * 12)

    summary = _service(fake).run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["generated"] == 1
    assert target.exists()


def test_laplacian_variance_uses_pillow_kernel(monkeypatch):
    image = Image.new("L", (5, 5), 100)
    image.putpixel((2, 2), 200)
    calls = []
    original_kernel = ImageFilter.Kernel

    def recording_kernel(*args, **kwargs):
        calls.append((args, kwargs))
        return original_kernel(*args, **kwargs)

    monkeypatch.setattr(cover_service.ImageFilter, "Kernel", recording_kernel)
    actual = CoverService._laplacian_variance(image)
    expected = ImageStat.Stat(
        image.filter(
            original_kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128)
        )
    ).var[0]

    assert calls
    assert actual == expected


def test_run_command_replaces_invalid_output_encoding(monkeypatch):
    seen = {}

    def fake_run(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(cover_service.subprocess, "run", fake_run)
    cover_service._run_command(["ffprobe"], 3.0)

    assert seen["kwargs"]["errors"] == "replace"


def test_cover_generation_rejects_outside_root_and_long_filename(db_session, tmp_path, monkeypatch):
    root = tmp_path / "media"
    outside = _video(tmp_path / "outside", "outside.mp4")
    long_path = root / ("x" * 250 + ".mp4")
    root.mkdir(parents=True, exist_ok=True)
    fake = FakeCommands(["sharp"] * 24)
    service = _service(fake)
    monkeypatch.setattr(service, "_iter_videos", lambda _roots: iter([outside, long_path]))

    summary = service.run(db_session, [str(root)], since="2025-01-01T00:00:00+00:00")

    assert summary["failed"] == 1
    assert summary["filename_too_long_skipped"] == 1
    assert outside.with_name("outside-poster.jpg").exists() is False
