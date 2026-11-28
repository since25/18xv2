"""
NFO 重新翻译：调用模型重翻 302porn_tv1 里 MDC 生成的 NFO 的标题和简介，先出报告，确认后再写回。

用法（在生产容器内执行，详见 docs/nfo-retranslate.md）：
  python scripts/nfo_retranslate.py translate [--limit N | --sample N] [--fields title,plot]
         [--path-prefix 目录] [--engine Google] [--workers 8] [--resume 运行编号] [--redo] [--force]
  python scripts/nfo_retranslate.py apply --run 运行编号 [--skip 文件] [--no-refresh]
  python scripts/nfo_retranslate.py restore --run 运行编号 [--no-refresh]

退出码：0 成功；1 缺配置、没过前提检查或运行编号不存在；130 手动中断。
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
import random
import sys
import tempfile

from app.core.config import get_settings
from app.db.session import SessionLocal
# 单独运行脚本时 app.models 不会自动导入关键词模型，Jellyfin 条目的关系会配置失败
import app.models.keywords  # noqa: F401
from app.services.jellyfin.client import JellyfinClient
from app.services.nfo_retranslate.apply_service import (
    ApplyResult,
    Refresher,
    apply_run,
    make_refresher,
    restore_run,
)
from app.services.nfo_retranslate.nfo_file import NfoDoc, plot_body, split_title, strip_num
from app.services.nfo_retranslate.prompts import (
    build_user_message,
    known_names,
    load_actor_glossary,
    validate_output,
)
from app.services.nfo_retranslate.report import write_report
from app.services.nfo_retranslate.runs import (
    RUN_ID_FORMAT,
    RunDir,
    TranslationRecord,
    latest_translations,
    load_ledger,
)
from app.services.nfo_retranslate.scope import (
    FilmGroup,
    count_orphans,
    field_in_scope,
    group_films,
    group_matches_engine,
    load_task_sources,
    snapshot_mdc_db,
)
from app.services.nfo_retranslate.translator import TranslateJob, TranslatorClient, translate_all

# 运行记录根目录（容器内相对 /app）
BASE_DIR = "data/nfo_retranslate"
# 运行元数据：只放模型名、运行编号、命令参数、选中的组，不放接口地址和密钥
META_FILE = "run.json"
# 运行目录里的翻译记录文件名（和 runs.py 一致）；报告覆盖的记录指纹按它算
TRANSLATIONS_FILE = "translations.jsonl"
# 找不到 MDC 任务的 NFO 超过这个数，多半是旧版残留还没清
MAX_ORPHANS = 100
# MDC 任务和可写根目录里 302porn_tv1 的目录名，用来从 MEDIA_LIBRARY_STRM_ROOTS 里挑只读根
STRM_ROOT_NAME = "302porn_tv1"
FIELDS = ("title", "plot")
# --sample 用的随机数；测试里换成固定种子
RANDOM = random.Random()
# 每完成这么多个字段打印一次进度
PROGRESS_EVERY = 50
# 续跑时沿用原运行的这些参数；命令行另给了不同的值就拒绝
RESUME_ARGS = ("fields", "path_prefix", "engine", "redo", "limit", "sample", "thinking")


@dataclass
class FieldJob:
    """一组一个字段要翻的内容。"""

    group: FilmGroup
    field: str
    source_doc: NfoDoc
    source_text: str
    old_text: str
    targets: dict[str, str]


def _quiet_http_logs() -> None:
    """httpx 每个请求用 INFO 记完整地址，调到 WARNING，接口地址不进日志。"""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _valid_run_id(run_id: str) -> bool:
    try:
        datetime.strptime(run_id, RUN_ID_FORMAT)
    except ValueError:
        return False
    return True


def _open_run(run_id: str) -> RunDir | None:
    """校验运行编号格式并打开运行目录；不合格或不存在时打印原因返回 None。"""
    if not _valid_run_id(run_id):
        print(f"运行编号格式不对：{run_id}（应为 年月日-时分秒，例如 20261127-153000）")
        return None
    try:
        return RunDir.open(BASE_DIR, run_id)
    except FileNotFoundError:
        print(f"运行编号不存在：{run_id}（{os.path.join(BASE_DIR, run_id)}）")
        return None


def write_run_meta(run: RunDir, meta: dict) -> None:
    """写运行元数据 run.json（整份覆盖）。"""
    tmp = os.path.join(run.path, META_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(run.path, META_FILE))


def read_run_meta(run: RunDir) -> dict | None:
    """读运行元数据；文件不存在或读不出时返回 None。"""
    try:
        with open(os.path.join(run.path, META_FILE), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def fingerprint(data: bytes) -> dict:
    """一份 translations.jsonl 内容的字节数和 sha256。"""
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_translations(run: RunDir) -> tuple[bytes, list[TranslationRecord]]:
    """读一次 translations.jsonl 的字节，返回 (这份字节, 由它解析出的记录)；空行和坏行跳过，文件不存在按空文件算。

    报告、指纹、apply 写回都用同一份字节，读完之后文件再被追加也不影响。
    """
    try:
        with open(os.path.join(run.path, TRANSLATIONS_FILE), "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        data = b""
    records: list[TranslationRecord] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(TranslationRecord(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return data, records


def _meta_model(run: RunDir) -> str | None:
    """取运行元数据里的模型名；缺失时打印原因返回 None。"""
    meta = read_run_meta(run)
    model = meta.get("model") if meta else None
    if not isinstance(model, str) or not model:
        print(f"运行目录里的 {META_FILE} 缺失或读不出模型名，无法确定这次翻译用的模型：{run.path}")
        return None
    return model


def _missing(settings, names: dict[str, str]) -> list[str]:
    return [env_name for attr, env_name in names.items() if not getattr(settings, attr, None)]


def _strm_root(settings) -> str | None:
    """MEDIA_LIBRARY_STRM_ROOTS 里目录名是 302porn_tv1 的那一项（规范成绝对路径）。"""
    for path in getattr(settings, "media_library_strm_roots", None) or []:
        if os.path.basename(os.path.normpath(path)) == STRM_ROOT_NAME:
            return os.path.abspath(path)
    return None


# ---------- translate ----------


def _parse_fields(text: str) -> list[str] | None:
    fields = [item.strip() for item in text.split(",") if item.strip()]
    if not fields or any(field not in FIELDS for field in fields):
        return None
    return [field for field in FIELDS if field in fields]


def _field_jobs(
    group: FilmGroup, fields: list[str], sources: dict, ledger: dict, redo: bool
) -> list[FieldJob]:
    """一组里每个字段：targets 是在范围内、又没被已写入记录跳过的 NFO；原文和旧译文取第一个在 targets 里的 NFO。"""
    jobs: list[FieldJob] = []
    for field in fields:
        in_scope = [doc for doc in group.docs if field_in_scope(field, doc, sources.get(doc.path))]
        if not in_scope:
            continue
        targets = {}
        for doc in in_scope:
            entry = ledger.get(doc.path)
            if not redo and entry is not None and entry.sha256_after == doc.sha256 and field in entry.fields:
                continue
            targets[doc.path] = doc.sha256
        if not targets:
            continue
        # 旧译文要显示实际会被覆盖的那份
        source = next(doc for doc in in_scope if doc.path in targets)
        if field == "title":
            source_text = strip_num(source.original_title, source.num)
            parts = split_title(source.title, source.num)
            old_text = parts[0] if parts else source.title
        else:
            # 原简介里也可能有 <br>，统一换成换行
            source_text = plot_body(source.original_plot)
            old_text = plot_body(source.plot)
        jobs.append(FieldJob(group, field, source, source_text, old_text, targets))
    return jobs


def _resume_args(args: argparse.Namespace, meta: dict) -> argparse.Namespace | None:
    """续跑时用原运行的参数替换命令行里的同名参数；命令行另给了不同的值时打印原因返回 None。"""
    original = meta.get("args") if isinstance(meta.get("args"), dict) else {}
    defaults = {"fields": None, "path_prefix": None, "engine": None, "redo": False, "limit": None, "sample": None,
                "thinking": False}
    conflicts = []
    for name in RESUME_ARGS:
        old = original.get(name, defaults[name])
        new = getattr(args, name)
        if new != defaults[name] and new != old:
            conflicts.append(f"--{name.replace('_', '-')}（原运行：{old}，这次：{new}）")
        setattr(args, name, old)
    if conflicts:
        print(f"续跑沿用原运行参数，不能改：{'、'.join(conflicts)}；去掉这些参数再续跑，或重新 translate")
        return None
    args.force = bool(original.get("force", False))
    return args


def _translate(args: argparse.Namespace) -> int:
    settings = get_settings()
    missing = _missing(
        settings,
        {
            "nfo_translate_api_base": "NFO_TRANSLATE_API_BASE",
            "nfo_translate_api_key": "NFO_TRANSLATE_API_KEY",
            "nfo_translate_model": "NFO_TRANSLATE_MODEL",
            "nfo_translate_root": "NFO_TRANSLATE_ROOT",
            "nfo_translate_mdc_db": "NFO_TRANSLATE_MDC_DB",
            "nfo_translate_name_map": "NFO_TRANSLATE_NAME_MAP",
        },
    )
    if missing:
        print(f"缺少配置：{'、'.join(missing)}（在 .env 里填写）")
        return 1
    model = settings.nfo_translate_model
    run = meta = None
    if args.resume:
        run = _open_run(args.resume)
        if run is None:
            return 1
        meta = read_run_meta(run)
        if meta is None or not meta.get("model"):
            print(f"运行目录里的 {META_FILE} 缺失或读不出模型名，不能续跑：{run.path}")
            return 1
        if meta["model"] != model:
            print(f"这次运行用的模型是 {meta['model']}，当前配置是 {model}；换模型请重新 translate，不要续跑")
            return 1
        if _resume_args(args, meta) is None:
            return 1
    fields = _parse_fields(args.fields or ",".join(FIELDS))
    if fields is None:
        print(f"--fields 只能是 title、plot，用逗号分隔：{args.fields}")
        return 1
    if args.limit is not None and args.sample is not None:
        print("--limit 和 --sample 只能用一个")
        return 1
    if args.workers < 1 or (args.limit is not None and args.limit < 1) or (args.sample is not None and args.sample < 1):
        print("--workers、--limit、--sample 必须是正整数")
        return 1
    root = os.path.abspath(settings.nfo_translate_root)
    if not os.path.isdir(root):
        print(f"NFO_TRANSLATE_ROOT 不是目录：{root}")
        return 1
    prefix_dir = None
    if args.path_prefix:
        prefix_dir = os.path.normpath(os.path.join(root, args.path_prefix.strip("/")))
        if not os.path.isdir(prefix_dir):
            print(f"--path-prefix 指向的目录不存在：{args.path_prefix}")
            return 1
    if not os.path.isfile(settings.nfo_translate_mdc_db):
        print(f"MDC 数据库不存在：{settings.nfo_translate_mdc_db}")
        return 1
    try:
        glossary = load_actor_glossary(settings.nfo_translate_name_map)
    except ValueError as exc:
        print(str(exc))
        return 1

    if run is not None:
        # 续跑会追加记录，旧报告作废；新报告写完再记指纹，中途被杀也不能 apply
        if meta.pop("report", None) is not None:
            write_run_meta(run, meta)
    else:
        try:
            run = RunDir.create(BASE_DIR)
        except FileExistsError:
            print("同一秒内已有一次运行，请稍后再试")
            return 1
        meta = {"model": model, "run_id": run.run_id, "args": vars(args)}
        write_run_meta(run, meta)

    # MDC 库复制到临时目录，读完即删，不留在运行目录里
    with tempfile.TemporaryDirectory(prefix="nfo-retranslate-mdc-") as tmp:
        sources = load_task_sources(snapshot_mdc_db(settings.nfo_translate_mdc_db, tmp), root)
    groups, read_errors = group_films(root)
    orphans = count_orphans(groups, sources)
    if orphans > MAX_ORPHANS and not args.force:
        print(
            f"找不到 MDC 任务的 NFO 有 {orphans} 个（超过 {MAX_ORPHANS}），旧版残留可能还没清；"
            "确认清理过后加 --force 继续"
        )
        return 1

    if prefix_dir is not None:
        groups = [g for g in groups if g.docs[0].path.startswith(prefix_dir + os.sep)]
    if args.engine:
        groups = [g for g in groups if group_matches_engine(g, args.engine)]

    ledger = load_ledger(BASE_DIR)
    records = run.load_translations()
    done = {(rec.group_key, rec.field) for rec in records}
    plans: dict[str, list[FieldJob]] = {}
    for group in groups:
        # 已有记录的字段不再翻；一组所有字段都有记录才算翻完
        jobs = [job for job in _field_jobs(group, fields, sources, ledger, args.redo) if (group.key, job.field) not in done]
        if jobs:
            plans[group.key] = jobs

    selected = meta.get("groups") if args.resume else None
    if selected is not None:
        # 续跑只补当初选中的组，不按 --limit / --sample 重新挑
        chosen = set(selected)
        keys = [key for key in plans if key in chosen]
    else:
        keys = list(plans)
        if args.limit is not None:
            keys = keys[: args.limit]
        elif args.sample is not None:
            picked = set(RANDOM.sample(keys, min(args.sample, len(keys))))
            keys = [key for key in keys if key in picked]
        if args.limit is not None or args.sample is not None:
            meta["groups"] = sorted(keys)
            write_run_meta(run, meta)

    field_jobs = {(job.group.key, job.field): job for key in keys for job in plans[key]}
    translate_jobs = [
        TranslateJob(
            key=job.group.key,
            field=job.field,
            user_message=build_user_message(
                job.field,
                num=job.source_doc.num,
                actors=job.source_doc.actors,
                glossary=glossary,
                studio=job.source_doc.studio,
                series=job.source_doc.series,
                text=job.source_text,
            ),
        )
        for job in field_jobs.values()
    ]
    total = len(translate_jobs)
    print(f"运行编号：{run.run_id}；要翻 {len(keys)} 部、{total} 个字段，模型 {model}，"
          f"思考{'开' if args.thinking else '关'}", flush=True)
    progress = {"done": 0, "failed": 0}

    def on_result(tjob: TranslateJob, text: str | None, reason: str | None) -> None:
        job = field_jobs[(tjob.key, tjob.field)]
        new_text, error = None, reason or None
        if text is not None and error is None and job.field == "title":
            # 模型常在开头带上番号，build_title 还会再拼一次
            text = strip_num(text.strip(), job.source_doc.num)
            if "\n" in text or "\r" in text:
                error = "标题译文含换行"
        if text is not None and error is None:
            names = known_names(job.source_doc.actors, glossary)
            new_text, error = validate_output(job.field, job.source_text, text, names=names)
        if new_text is None and not error:
            error = "翻译失败"
        run.append_translation(
            TranslationRecord(
                group_key=job.group.key,
                field=job.field,
                num=job.source_doc.num,
                actors=list(job.source_doc.actors),
                source_text=job.source_text,
                old_text=job.old_text,
                new_text=new_text,
                error=error,
                targets=job.targets,
            )
        )
        progress["done"] += 1
        progress["failed"] += error is not None
        if progress["done"] % PROGRESS_EVERY == 0 or progress["done"] == total:
            print(f"已完成 {progress['done']}/{total}，失败 {progress['failed']}", flush=True)

    client = TranslatorClient(settings.nfo_translate_api_base, settings.nfo_translate_api_key, model,
                              thinking=args.thinking)
    interrupted = False
    try:
        translate_all(client, translate_jobs, workers=args.workers, on_result=on_result)
    except KeyboardInterrupt:
        interrupted = True

    # 报告和指纹用同一份字节；之后文件再被追加，指纹就对不上，apply 会拒绝
    data, loaded = read_translations(run)
    all_records = latest_translations(loaded)
    write_report(run.report_path, all_records, model=model, run_id=run.run_id)
    meta["report"] = fingerprint(data)
    write_run_meta(run, meta)
    failed = sum(1 for rec in all_records if rec.error is not None)
    print(f"报告：{os.path.join(BASE_DIR, run.run_id, 'report.html')}")
    print(
        f"汇总：{len({rec.group_key for rec in all_records})} 部、{len(all_records)} 个字段，"
        f"成功 {len(all_records) - failed}，失败 {failed}；"
        f"找不到 MDC 任务的 NFO {orphans} 个，读不了的 NFO {len(read_errors)} 个"
    )
    if interrupted:
        print(f"已中断；同样的命令加 --resume {run.run_id} 继续")
        return 130
    print(f"看过报告后写回：python scripts/nfo_retranslate.py apply --run {run.run_id}")
    return 0


# ---------- apply / restore ----------


def _read_skip_file(path: str, records: list[TranslationRecord]) -> set[str] | None:
    """读跳过名单：每行一个 NFO 路径或番号，空行和 # 开头的行忽略；番号换成这次运行里该番号组的全部 NFO。"""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [line.strip() for line in fh]
    except OSError as exc:
        print(f"跳过名单读不了：{exc}")
        return None
    by_num: dict[str, set[str]] = {}
    for rec in records:
        by_num.setdefault(rec.num, set()).update(rec.targets)
    skip: set[str] = set()
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line in by_num:
            skip |= by_num[line]
        elif line.endswith(".nfo"):
            skip.add(os.path.abspath(line))
        else:
            print(f"跳过名单里的「{line}」不是这次运行里的番号，也不是 .nfo 路径，忽略")
    return skip


def _refresher_or_error(settings, root: str | None):
    """生成 Jellyfin 刷新函数需要的参数；缺配置时打印原因返回 None。"""
    missing = _missing(settings, {"jellyfin_base_url": "JELLYFIN_BASE_URL", "jellyfin_api_key": "JELLYFIN_API_KEY"})
    if root is None:
        missing.append("NFO_TRANSLATE_ROOT")
    strm_root = _strm_root(settings)
    if strm_root is None:
        missing.append(f"MEDIA_LIBRARY_STRM_ROOTS（含 {STRM_ROOT_NAME} 的一项）")
    if missing:
        print(f"刷新 Jellyfin 缺少配置：{'、'.join(missing)}；或加 --no-refresh，写完后手动扫描 Jellyfin 库")
        return None
    return strm_root


def _client_factory(settings):
    return lambda: JellyfinClient(
        settings.jellyfin_base_url,
        settings.jellyfin_api_key,
        settings.jellyfin_timeout_seconds,
        settings.jellyfin_page_size,
    )


def _safe_refresher(refresher: Refresher) -> Refresher:
    """刷新阶段出任何异常都记成刷新失败，不打断汇总；已写入的 NFO 不回滚。"""

    def refresh(paths: list[str]) -> tuple[int, list[tuple[str, str]], list[str]]:
        try:
            return refresher(paths)
        except Exception as exc:  # noqa: BLE001 - 刷新失败只记录
            return 0, [("刷新阶段", f"刷新出错：{type(exc).__name__}: {exc}")], []

    return refresh


def _with_refresher(settings, root: str | None, no_refresh: bool, work) -> ApplyResult | None:
    """no_refresh 时 refresher 为 None；否则开数据库会话生成刷新函数再干活。缺配置返回 None。"""
    if no_refresh:
        return work(None)
    strm_root = _refresher_or_error(settings, root)
    if strm_root is None:
        return None
    with SessionLocal() as db:
        refresher = make_refresher(db, _client_factory(settings), root=root, strm_root=strm_root)
        return work(_safe_refresher(refresher))


def _print_refresh(result: ApplyResult, no_refresh: bool) -> None:
    if no_refresh:
        print("没有刷新 Jellyfin：请在 18x 里手动扫描 Jellyfin 库")
        return
    print(
        f"Jellyfin 刷新成功 {result.refreshed} 个条目，失败 {len(result.refresh_failed)} 个，"
        f"找不到条目 {len(result.missing_items)} 个 NFO"
    )
    for item_id, reason in result.refresh_failed[:10]:
        print(f"  刷新失败 {item_id}：{reason}")
    if result.refresh_failed or result.missing_items:
        print("刷新没覆盖到的，请在 18x 里扫描 Jellyfin 库兜底（已写入的 NFO 不会回滚）")


def _apply(args: argparse.Namespace) -> int:
    run = _open_run(args.run)
    if run is None:
        return 1
    model = _meta_model(run)
    if model is None:
        return 1
    report = (read_run_meta(run) or {}).get("report")
    data, records = read_translations(run)
    if report is None or report != fingerprint(data) or not os.path.isfile(run.report_path):
        print(
            "这次运行的报告没生成完，或报告之后翻译记录又有变化，不写回；"
            f"先 translate --resume {run.run_id} 重新生成报告，看过再 apply"
        )
        return 1
    settings = get_settings()
    if not getattr(settings, "nfo_translate_root", None):
        print("缺少配置：NFO_TRANSLATE_ROOT")
        return 1
    root = os.path.abspath(settings.nfo_translate_root)
    skip_paths: set[str] = set()
    if args.skip:
        loaded = _read_skip_file(args.skip, records)
        if loaded is None:
            return 1
        skip_paths = loaded

    result = _with_refresher(
        settings,
        root,
        args.no_refresh,
        # 写回只用核对过指纹的那份记录
        lambda refresher: apply_run(
            run,
            base_dir=BASE_DIR,
            root=root,
            model=model,
            skip_paths=skip_paths,
            refresher=refresher,
            records=records,
        ),
    )
    if result is None:
        return 1

    # skipped 里混着几类原因，按 NFO 分开计数
    listed, failed, other = set(), set(), Counter()
    other_paths = set()
    for path, reason in result.skipped:
        if reason.startswith("在跳过名单里"):
            listed.add(path)
        elif "没有可写的译文" in reason:
            failed.add(path)
        else:
            other_paths.add(path)
            other[reason] += 1
    print(f"运行编号：{run.run_id}，模型 {model}")
    print(f"写入：{len(result.written)}")
    print(f"跳过名单：{len(listed)}")
    print(f"翻译失败不写：{len(failed)}")
    print(f"文件被改动或读写出错：{len(other_paths)}")
    for reason, count in other.most_common(10):
        print(f"  {reason}：{count}")
    _print_refresh(result, args.no_refresh)
    print(f"明细：{os.path.join(BASE_DIR, run.run_id, 'apply.jsonl')}")
    return 0


def _restore(args: argparse.Namespace) -> int:
    run = _open_run(args.run)
    if run is None:
        return 1
    settings = get_settings()
    root_setting = getattr(settings, "nfo_translate_root", None)
    root = os.path.abspath(root_setting) if root_setting else None
    result = _with_refresher(
        settings,
        root,
        args.no_refresh,
        lambda refresher: restore_run(run, base_dir=BASE_DIR, refresher=refresher),
    )
    if result is None:
        return 1
    reasons = Counter(reason for _, reason in result.skipped)
    print(f"运行编号：{run.run_id}")
    print(f"还原：{len(result.written)}")
    print(f"没还原：{len(result.skipped)}")
    for reason, count in reasons.most_common(10):
        print(f"  {reason}：{count}")
    _print_refresh(result, args.no_refresh)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NFO 标题、简介重新翻译")
    sub = parser.add_subparsers(dest="command", required=True)

    tr = sub.add_parser("translate", help="翻译并出报告，不改 NFO")
    tr.add_argument("--limit", type=int, default=None, help="只翻前 N 部")
    tr.add_argument("--sample", type=int, default=None, help="随机抽 N 部试跑")
    tr.add_argument("--fields", default=None, help="要翻的字段：title、plot，逗号分隔（默认两个都翻）")
    tr.add_argument("--path-prefix", default=None, help="只翻根目录下这个子目录里的 NFO")
    tr.add_argument("--engine", default=None, help="只翻简介标记为「由 X 提供翻译」的片子，例如 Google")
    tr.add_argument("--workers", type=int, default=8, help="并发请求数")
    tr.add_argument("--thinking", action="store_true", help="打开模型思考（默认关）")
    tr.add_argument("--resume", default=None, metavar="RUN_ID", help="续跑这次运行，跳过已翻过的字段，沿用原运行的参数")
    tr.add_argument("--redo", action="store_true", help="已写入记录里的 NFO 也重翻")
    tr.add_argument("--force", action="store_true", help="找不到 MDC 任务的 NFO 超过 100 个也继续")

    ap = sub.add_parser("apply", help="把某次运行的译文写回 NFO，并刷新 Jellyfin")
    ap.add_argument("--run", required=True, metavar="RUN_ID", help="运行编号")
    ap.add_argument("--skip", default=None, metavar="FILE", help="跳过名单：每行一个 NFO 路径或番号")
    ap.add_argument("--no-refresh", action="store_true", help="不刷新 Jellyfin")

    rs = sub.add_parser("restore", help="用某次运行写入时的备份还原 NFO，并刷新 Jellyfin")
    rs.add_argument("--run", required=True, metavar="RUN_ID", help="运行编号")
    rs.add_argument("--no-refresh", action="store_true", help="不刷新 Jellyfin")
    return parser


def main(argv: list[str] | None = None) -> int:
    _quiet_http_logs()
    args = _parser().parse_args(argv)
    if args.command == "translate":
        return _translate(args)
    if args.command == "apply":
        return _apply(args)
    return _restore(args)


if __name__ == "__main__":
    sys.exit(main())
