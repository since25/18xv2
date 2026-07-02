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


def test_path_guard_blocks_directory_delete_by_default(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "nested"
    target.mkdir()
    child = target / "a.strm"
    child.write_text("url", encoding="utf-8")

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(target), dry_run=False)

    assert result.status == "blocked"
    assert result.error_message == "directory_delete_not_allowed"
    assert result.entry_type == "dir"
    assert child.exists()


def test_path_guard_blocks_symlink_escape_without_deleting_target(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    outside_target = outside / "a.strm"
    outside_target.write_text("url", encoding="utf-8")
    symlink_path = allowed / "linked.strm"
    symlink_path.symlink_to(outside_target)

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(symlink_path), dry_run=False)

    assert result.status == "blocked"
    assert result.error_message == "path_outside_allowed_roots"
    assert outside_target.exists()
    assert symlink_path.exists()


def test_path_guard_delete_allowed_symlink_unlinks_symlink_and_keeps_target(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "target.strm"
    target.write_text("url", encoding="utf-8")
    symlink_path = allowed / "linked.strm"
    symlink_path.symlink_to(target)

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(symlink_path), dry_run=False)

    assert result.status == "deleted"
    assert not symlink_path.exists()
    assert target.exists()
