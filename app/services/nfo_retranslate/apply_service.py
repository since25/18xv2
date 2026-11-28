"""把一次运行的译文写回 NFO、用备份还原，并让 Jellyfin 按条目刷新。

apply 只用运行目录里的 translations.jsonl，不再调用模型。每个 NFO：核对哈希 → 备份 → 原子写入 → 记 apply.jsonl
和已写入记录。全部写完后统一刷新 Jellyfin；刷新失败只记录，不回滚 NFO。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jellyfin import JellyfinMediaItem
from app.services.jellyfin.client import JellyfinClient, JellyfinError
from app.services.nfo_retranslate.nfo_file import (
    NfoError,
    atomic_write,
    build_plot,
    build_title,
    read_nfo,
    replace_fields,
    sha256_text,
    split_title,
)
from app.services.nfo_retranslate.runs import (
    LedgerEntry,
    RunDir,
    TranslationRecord,
    append_ledger,
    drop_ledger,
    latest_translations,
    load_ledger,
)

# 刷新函数：输入写过的 NFO 路径，返回 (刷新成功数, [(条目 ID, 原因)], 找不到条目的 NFO 路径)
Refresher = Callable[[list[str]], tuple[int, list[tuple[str, str]], list[str]]]

_FIELD_NAMES = {"title": "标题", "plot": "简介"}


@dataclass
class ApplyResult:
    """一次写回或还原的结果：写成功的 NFO、(NFO 路径, 跳过原因)，以及 Jellyfin 刷新情况。"""

    written: list[str]
    skipped: list[tuple[str, str]]
    refreshed: int
    refresh_failed: list[tuple[str, str]]
    missing_items: list[str]


def _records_by_path(run: RunDir) -> dict[str, dict[str, TranslationRecord]]:
    """按 NFO 路径汇总：路径 → 字段 → 记录；同一部片同一字段以最后一条为准，和报告一致。"""
    by_path: dict[str, dict[str, TranslationRecord]] = {}
    for rec in latest_translations(run.load_translations()):
        for path in rec.targets:
            by_path.setdefault(path, {})[rec.field] = rec
    return by_path


def _write_one(
    run: RunDir,
    path: str,
    records: dict[str, TranslationRecord],
    *,
    base_dir: str,
    root: str,
    model: str,
    previous: LedgerEntry | None,
    skip: Callable[[str, str], None],
) -> bool:
    """写一个 NFO 里有译文的字段；写成功返回 True。整个文件或某个字段不写时调用 skip 记下原因。"""
    rel = os.path.relpath(path, root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        # 备份按相对路径放，根目录外的文件会让备份落到运行目录外面
        skip(path, "不在 NFO 根目录下，不写")
        return False
    try:
        doc = read_nfo(path)
    except NfoError as exc:
        skip(path, str(exc))
        return False
    if any(rec.targets[path] != doc.sha256 for rec in records.values()):
        skip(path, "translate 之后已被改动，不写")
        return False

    title = plot = None
    if "title" in records:
        parts = split_title(doc.title, doc.num)
        if parts is None:
            skip(path, "标题不以番号开头，标题不写")
        else:
            title = build_title(doc.num, records["title"].new_text or "", parts[1])
    if "plot" in records:
        plot = build_plot(records["plot"].new_text or "", model)
    if title is None and plot is None:
        return False

    backup = os.path.join(run.backup_dir, rel)
    try:
        content = replace_fields(doc.raw, title=title, plot=plot)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        # 备份写的是刚核对过哈希的那份内容
        with open(backup, "wb") as fh:
            fh.write(doc.raw.encode("utf-8"))
        atomic_write(path, content)
    except NfoError as exc:
        skip(path, str(exc))
        return False
    except OSError as exc:
        skip(path, f"备份失败：{exc}")
        return False

    fields = sorted(name for name, value in (("title", title), ("plot", plot)) if value is not None)
    sha_after = sha256_text(content)
    run.append_apply({"path": path, "fields": fields, "sha256_after": sha_after, "backup": rel})
    ledger_fields = frozenset(fields)
    if previous is not None and previous.sha256_after == doc.sha256:
        # 上次写入后文件没被别人改过，上次写过的字段仍然算已写入
        ledger_fields |= previous.fields
    append_ledger(base_dir, path, LedgerEntry(sha256_after=sha_after, fields=ledger_fields, model=model))
    return True


def _refresh(refresher: Refresher | None, paths: list[str]) -> tuple[int, list[tuple[str, str]], list[str]]:
    if refresher is None or not paths:
        return 0, [], []
    return refresher(paths)


def apply_run(
    run: RunDir,
    *,
    base_dir: str,
    root: str,
    model: str,
    skip_paths: set[str],
    refresher: Refresher | None,
) -> ApplyResult:
    """把这次运行里通过检查的译文写回 NFO，最后刷新写过的条目。

    root 是 NFO 可写根目录，备份放在 backup/<相对 root 的路径>。译文为空或带错误原因的字段、
    skip_paths 里的文件不写；单个文件出错只记进 skipped，不中断其余文件。
    """
    written: list[str] = []
    skipped: list[tuple[str, str]] = []
    # 这次运行里每个文件最多写一次，开头读一遍以前的已写入记录就够
    ledger = load_ledger(base_dir)

    def skip(path: str, reason: str) -> None:
        skipped.append((path, reason))
        run.append_apply({"path": path, "skipped": reason})

    for path, records in sorted(_records_by_path(run).items()):
        if path in skip_paths:
            skip(path, "在跳过名单里，不写")
            continue
        usable: dict[str, TranslationRecord] = {}
        for field_name, rec in records.items():
            if rec.new_text is None or rec.error:
                skip(path, f"{_FIELD_NAMES.get(field_name, field_name)}没有可写的译文：{rec.error or '译文为空'}")
            else:
                usable[field_name] = rec
        if usable and _write_one(
            run,
            path,
            usable,
            base_dir=base_dir,
            root=root,
            model=model,
            previous=ledger.get(path),
            skip=skip,
        ):
            written.append(path)

    refreshed, refresh_failed, missing = _refresh(refresher, written)
    if refresher is not None and written:
        run.append_apply({"refresh": {"refreshed": refreshed, "failed": refresh_failed, "missing": missing}})
    return ApplyResult(written, skipped, refreshed, refresh_failed, missing)


def restore_run(run: RunDir, *, base_dir: str, refresher: Refresher | None) -> ApplyResult:
    """用备份还原这次运行写过的 NFO，删掉它们的已写入记录，再刷新 Jellyfin。

    以 apply.jsonl 里写成功的条目为准（同一文件写过多次时取最后一次）；当前哈希不等于当时写入后的哈希，
    说明写入后又被改过，跳过不还原。
    """
    entries = {row["path"]: row for row in run.load_apply() if "sha256_after" in row}
    restored: list[str] = []
    skipped: list[tuple[str, str]] = []
    for path, entry in sorted(entries.items()):
        try:
            current = read_nfo(path).sha256
        except NfoError as exc:
            skipped.append((path, str(exc)))
            continue
        if current != entry["sha256_after"]:
            skipped.append((path, "写入后已被改动，不还原"))
            continue
        try:
            with open(os.path.join(run.backup_dir, entry["backup"]), "rb") as fh:
                content = fh.read().decode("utf-8")
            atomic_write(path, content)
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append((path, f"读取备份失败：{exc}"))
            continue
        except NfoError as exc:
            skipped.append((path, str(exc)))
            continue
        restored.append(path)

    if restored:
        drop_ledger(base_dir, restored)
    refreshed, refresh_failed, missing = _refresh(refresher, restored)
    return ApplyResult(restored, skipped, refreshed, refresh_failed, missing)


def item_ids_for(
    db: Session, nfo_paths: Iterable[str], *, root: str, strm_root: str
) -> tuple[dict[str, str], list[str]]:
    """找 NFO 对应的 Jellyfin 条目 ID：换成 strm_root 下同名的 .strm 路径，查 strm_115 来源、仍在库里的条目。

    返回 (NFO 路径 → 条目 ID, 找不到条目的 NFO 路径)。
    """
    found: dict[str, str] = {}
    missing: list[str] = []
    for path in nfo_paths:
        strm = os.path.join(strm_root, os.path.splitext(os.path.relpath(path, root))[0] + ".strm")
        item_id = db.scalar(
            select(JellyfinMediaItem.jellyfin_item_id).where(
                JellyfinMediaItem.source == "strm_115",
                JellyfinMediaItem.path == strm,
                JellyfinMediaItem.active.is_(True),
            )
        )
        if item_id:
            found[path] = item_id
        else:
            missing.append(path)
    return found, missing


def make_refresher(
    db: Session,
    client_factory: Callable[[], JellyfinClient],
    *,
    root: str,
    strm_root: str,
    workers: int = 2,
) -> Refresher:
    """生成刷新函数：NFO 路径换成条目 ID，去重后最多 workers 路并发刷新；单个条目失败只记下，不影响其余条目。"""

    def refresh_one(item_id: str) -> str | None:
        try:
            # 每次用新客户端，各线程不共用 HTTP 连接
            client_factory().refresh_item(item_id)
        except JellyfinError as exc:
            return str(exc)
        return None

    def refresh(nfo_paths: list[str]) -> tuple[int, list[tuple[str, str]], list[str]]:
        ids, missing = item_ids_for(db, nfo_paths, root=root, strm_root=strm_root)
        item_ids = sorted(set(ids.values()))
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            errors = list(pool.map(refresh_one, item_ids))
        finally:
            # Ctrl-C 时取消还没开始的刷新，只等正在请求的那几个
            pool.shutdown(wait=True, cancel_futures=True)
        failed = [(item_id, error) for item_id, error in zip(item_ids, errors, strict=True) if error is not None]
        return len(item_ids) - len(failed), failed, missing

    return refresh
