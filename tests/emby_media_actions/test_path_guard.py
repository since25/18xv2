from __future__ import annotations

from pathlib import Path

from app.services.emby_media_actions.path_guard import PathGuard


def test_path_guard_blocks_outside_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    guard = PathGuard(allowed_roots=[str(allowed)])
    decision = guard.classify(str(outside / "a.strm"))

    assert decision.allowed is False
    assert decision.reason == "path_outside_allowed_roots"


def test_path_guard_dry_run_does_not_delete(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "a.strm"
    target.write_text("url", encoding="utf-8")

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(target), dry_run=True)

    assert result.status == "dry_run"
    assert target.exists()


def test_path_guard_real_delete_removes_file(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "a.strm"
    target.write_text("url", encoding="utf-8")

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(target), dry_run=False)

    assert result.status == "deleted"
    assert not target.exists()
