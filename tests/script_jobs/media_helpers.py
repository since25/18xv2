"""MOVE / DEL 真实子进程测试的公用工具：假 chown、目录树快照、运行环境。"""

from __future__ import annotations

import os
from pathlib import Path
import stat


def fake_bin(tmp_path: Path) -> tuple[Path, Path]:
    """在 PATH 前面放一个假 chown：只把参数追加写进记录文件，不真的改归属。返回（bin 目录，记录文件）。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    calls = tmp_path / "chown_calls.txt"
    script = bin_dir / "chown"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, calls


def env_with(bin_dir: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra)
    return env


def snapshot(root: Path) -> list[tuple[str, int | None]]:
    """目录树快照：相对路径 + 文件大小（目录记 None）。"""
    entries: list[tuple[str, int | None]] = []
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        entries.append((rel, None if path.is_dir() else path.stat().st_size))
    return entries


def write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
