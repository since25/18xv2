"""运行记录：运行目录里的 translations.jsonl、apply.jsonl、report.html、backup/，以及跨运行的已写入记录 applied.jsonl。

都是 JSONL，一条记录一行；读的时候跳过中断留下的半行，不整次报错。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import contextlib
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
import stat
import tempfile
from typing import Any

# 运行编号格式：年月日-时分秒
RUN_ID_FORMAT = "%Y%m%d-%H%M%S"
_TRANSLATIONS = "translations.jsonl"
_APPLY = "apply.jsonl"
_REPORT = "report.html"
_BACKUP = "backup"
_LEDGER = "applied.jsonl"


@dataclass
class TranslationRecord:
    """一部片一个字段的翻译结果；targets 是要写的 NFO 路径 → 它在 translate 时的 sha256。"""

    group_key: str
    field: str
    num: str
    actors: list[str]
    source_text: str
    old_text: str
    new_text: str | None
    error: str | None
    targets: dict[str, str]


def latest_translations(records: Sequence[TranslationRecord]) -> list[TranslationRecord]:
    """同一部片同一字段有多条记录（续跑补翻）时只留最后一条；按这部片这个字段第一次出现的位置排列。

    报告和 apply 都用它，报告里看到的就是实际写进去的。
    """
    latest = {(rec.group_key, rec.field): rec for rec in records}
    return list(latest.values())


@dataclass(frozen=True)
class LedgerEntry:
    """一个 NFO 的已写入记录：写入后的文件哈希、写了哪些字段、用的模型。"""

    sha256_after: str
    fields: frozenset[str]
    model: str


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    """追加一行 JSON；上次中断留下没换行的半行时先补换行，免得新记录接在坏行后面一起作废。"""
    line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "a+b") as fh:
        if fh.seek(0, os.SEEK_END) > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                line = b"\n" + line
        fh.write(line)


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    """逐行读 JSONL；文件不存在返回空列表，空行和坏行（含截断的多字节字符）跳过。"""
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


class RunDir:
    """一次运行的目录 base_dir/<运行编号>/。"""

    def __init__(self, base_dir: str, run_id: str) -> None:
        self.run_id = run_id
        self.path = os.path.join(base_dir, run_id)
        self.backup_dir = os.path.join(self.path, _BACKUP)
        self.report_path = os.path.join(self.path, _REPORT)
        self._translations_path = os.path.join(self.path, _TRANSLATIONS)
        self._apply_path = os.path.join(self.path, _APPLY)

    @classmethod
    def create(cls, base_dir: str) -> RunDir:
        """按当前时间建新的运行目录；同一秒内已有同名目录时抛 FileExistsError，不混用两次运行。"""
        run = cls(base_dir, datetime.now().strftime(RUN_ID_FORMAT))
        os.makedirs(base_dir, exist_ok=True)
        os.mkdir(run.path)
        return run

    @classmethod
    def open(cls, base_dir: str, run_id: str) -> RunDir:
        """打开已有的运行目录；不存在时抛 FileNotFoundError。"""
        run = cls(base_dir, run_id)
        if not os.path.isdir(run.path):
            raise FileNotFoundError(f"运行编号不存在：{run_id}")
        return run

    def append_translation(self, rec: TranslationRecord) -> None:
        """追加一条翻译记录；调用方负责串行（translate_all 的回调已加锁）。"""
        _append_jsonl(self._translations_path, asdict(rec))

    def load_translations(self) -> list[TranslationRecord]:
        """按写入顺序读回全部翻译记录，跳过坏行。"""
        return [TranslationRecord(**row) for row in _read_jsonl(self._translations_path)]

    def done_group_keys(self) -> set[str]:
        """已有记录的组键。"""
        return {rec.group_key for rec in self.load_translations()}

    def append_apply(self, entry: dict[str, Any]) -> None:
        """追加一条写入结果。"""
        _append_jsonl(self._apply_path, entry)

    def load_apply(self) -> list[dict[str, Any]]:
        """按写入顺序读回全部写入结果，跳过坏行。"""
        return _read_jsonl(self._apply_path)


def _ledger_path(base_dir: str) -> str:
    return os.path.join(base_dir, _LEDGER)


def load_ledger(base_dir: str) -> dict[str, LedgerEntry]:
    """读已写入记录：NFO 路径 → 记录；同一路径以最后一行为准。"""
    ledger: dict[str, LedgerEntry] = {}
    for row in _read_jsonl(_ledger_path(base_dir)):
        ledger[row["path"]] = LedgerEntry(
            sha256_after=row["sha256_after"], fields=frozenset(row["fields"]), model=row["model"]
        )
    return ledger


def append_ledger(base_dir: str, path: str, entry: LedgerEntry) -> None:
    """追加一个 NFO 的已写入记录。"""
    row = {"path": path, "sha256_after": entry.sha256_after, "fields": sorted(entry.fields), "model": entry.model}
    _append_jsonl(_ledger_path(base_dir), row)


def drop_ledger(base_dir: str, paths: Iterable[str]) -> None:
    """删掉这些 NFO 路径的全部记录：其余行写进临时文件后原子替换。"""
    ledger_path = _ledger_path(base_dir)
    rows = _read_jsonl(ledger_path)
    if not rows:
        return
    dropped = set(paths)
    fd, tmp_path = tempfile.mkstemp(dir=base_dir, prefix=".applied-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                if row["path"] not in dropped:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        # mkstemp 建的是 0600，沿用原文件权限
        os.chmod(tmp_path, stat.S_IMODE(os.stat(ledger_path).st_mode))
        os.replace(tmp_path, ledger_path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp_path)
        raise
