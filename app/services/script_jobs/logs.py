"""运行目录与日志：每次运行一个目录，日志按字节偏移增量读取。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil


LOG_FILE_NAME = "output.log"
LOG_RETENTION_DAYS = 30


def run_dir(base: Path, job_name: str, run_id: int) -> Path:
    """一次运行的目录：<base>/<脚本名>/<运行 ID>/。"""
    return Path(base) / job_name / str(run_id)


def _complete_utf8_prefix(data: bytes) -> bytes:
    """去掉末尾不完整的 UTF-8 字符；中间的坏字节保留，交给 replace 处理。"""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data":
            return data[: exc.start]
    return data


def read_log(path: Path, offset: int, limit: int = 65536, *, finished: bool) -> tuple[str, int]:
    """从 offset 读取日志增量，返回（文本，新偏移）。

    未结束时只返回到最后一个换行，避免把还在写的半行发给页面；
    任何情况下都不把一个汉字切成两半。
    """
    path = Path(path)
    size = path.stat().st_size
    if offset >= size:
        return "", offset
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(limit)
    reached_end = offset + len(data) >= size

    if not finished:
        newline = data.rfind(b"\n")
        if newline >= 0:
            data = data[: newline + 1]
        elif len(data) >= limit:
            # 一整块里都没有换行（超长行），按字符边界返回，避免永远卡住
            data = _complete_utf8_prefix(data)
        else:
            return "", offset
    elif not reached_end:
        data = _complete_utf8_prefix(data)

    return data.decode("utf-8", errors="replace"), offset + len(data)


def cleanup_old_runs(base: Path, now: datetime, days: int = LOG_RETENTION_DAYS) -> int:
    """删除修改时间早于 days 天前的运行目录，返回删除数量。"""
    base = Path(base)
    if not base.exists():
        return 0
    cutoff = (now - timedelta(days=days)).timestamp()
    removed = 0
    for job_dir in base.iterdir():
        if not job_dir.is_dir():
            continue
        for item in job_dir.iterdir():
            if item.is_dir() and item.stat().st_mtime < cutoff:
                shutil.rmtree(item, ignore_errors=True)
                removed += 1
    return removed
