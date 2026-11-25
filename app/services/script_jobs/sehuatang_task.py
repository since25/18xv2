"""sehuatang 在 18x 一侧：启动前写 input.json，结束后读 result.json、更新帖子去向表。"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import app as app_package
from app.core.config import get_settings
from app.models.keywords import KeywordEntry
from app.models.script_runs import SehuatangPost
from app.services.script_jobs.definitions import PreparedCommand, RunContext, RunOutcome
from app.services.script_jobs.sehuatang.matching import Term, normalize


INPUT_FILE = "input.json"
RESULT_FILE = "result.json"
# 子进程每处理完一帖就追加一行，被打断时靠它找回已处理的部分
ITEMS_FILE = "items.jsonl"
MIN_TERM_LENGTH = 2
PROJECT_ROOT = Path(app_package.__file__).resolve().parent.parent


def load_block_terms(db: Session) -> list[Term]:
    """18x 黑名单里启用词条的规范名和全部别名（与 DEL 一致：去首尾空白后至少 2 个字）。"""
    entries = db.scalars(
        select(KeywordEntry)
        .where(KeywordEntry.keyword_type == "blacklist", KeywordEntry.status == "active")
        .options(selectinload(KeywordEntry.aliases))
        .order_by(KeywordEntry.id.asc())
    ).all()
    terms: list[Term] = []
    seen: set[str] = set()
    for entry in entries:
        for raw in [entry.canonical_name, *(alias.alias for alias in entry.aliases)]:
            display = (raw or "").strip()
            if len(display) < MIN_TERM_LENGTH:
                continue
            term = normalize(display)
            if term and term not in seen:
                seen.add(term)
                terms.append((display, term))
    return terms


def prepare(db: Session, ctx: RunContext) -> PreparedCommand:
    settings = get_settings()
    run_dir = ctx.run_dir.resolve()
    submitted = db.scalars(select(SehuatangPost.tid).where(SehuatangPost.last_outcome == "submitted")).all()
    payload = {
        "dry_run": ctx.dry_run,
        "pages": ctx.params["pages"],
        "forum_url": ctx.params["forum_url"],
        "qb_category": ctx.params["qb_category"],
        "terms": [list(term) for term in load_block_terms(db)],
        "submitted_tids": sorted(submitted),
    }
    (run_dir / INPUT_FILE).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ)
    # 子进程的工作目录是运行目录，要显式把项目根放进模块搜索路径
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PROJECT_ROOT), env.get("PYTHONPATH", "")]))
    env["PYTHONUNBUFFERED"] = "1"
    env["SEHUATANG_SESSION_PATH"] = str(Path(settings.sehuatang_session_path).resolve())
    for key, value in (
        ("QB_URL", settings.qb_url),
        ("QB_USERNAME", settings.qb_username),
        ("QB_PASSWORD", settings.qb_password),
    ):
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return PreparedCommand(
        argv=[
            sys.executable,
            "-m",
            "app.services.script_jobs.sehuatang.main",
            "--input",
            str(run_dir / INPUT_FILE),
            "--result",
            str(run_dir / RESULT_FILE),
        ],
        env=env,
    )


def _update_posts(db: Session, run_id: int, items: list[dict]) -> None:
    now = datetime.now(UTC)
    for item in items:
        tid = item.get("tid")
        if not tid:
            continue
        post = db.scalar(select(SehuatangPost).where(SehuatangPost.tid == tid))
        if post is None:
            post = SehuatangPost(tid=tid, title=item.get("title") or "", url=item.get("url") or "",
                                 first_seen_at=now, last_outcome=item["kind"])
            db.add(post)
        else:
            post.title = item.get("title") or post.title
            post.url = item.get("url") or post.url
        # 已提交过的帖子不会被之后的其他结果改回别的状态
        if post.last_outcome != "submitted":
            post.last_outcome = item["kind"]
        if item["kind"] == "submitted":
            post.last_outcome = "submitted"
            post.submitted_at = now
        post.last_run_id = run_id
        post.updated_at = now
    db.commit()


def _run_items(raw_items: list[dict]) -> list[dict]:
    return [
        {
            "kind": item["kind"],
            "path": item.get("title"),
            "target_path": item.get("url"),
            "keyword": item.get("keyword"),
            "message": item.get("message"),
        }
        for item in raw_items
    ]


def salvage(db: Session, ctx: RunContext) -> RunOutcome:
    """运行被停止、超时或重启打断时，读子进程逐帖追加的 items.jsonl，找回已处理的帖子。

    已提交的帖子照常记进帖子表，第二天不会重复提交。最后一行可能只写了一半，跳过。
    """
    path = ctx.run_dir / ITEMS_FILE
    raw_items: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("kind"):
                raw_items.append(item)
    counts: dict[str, int] = {}
    for item in raw_items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    if raw_items and not ctx.dry_run:
        _update_posts(db, ctx.run_id, raw_items)
    return RunOutcome(status="", counts=counts, items=_run_items(raw_items), error_reason=None)


def finalize(db: Session, ctx: RunContext, exit_code: int) -> RunOutcome:
    result_path = ctx.run_dir / RESULT_FILE
    if exit_code != 0 or not result_path.is_file():
        return RunOutcome(status="failed", counts={}, items=[], error_reason="运行异常退出")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    counts = {key: int(value) for key, value in (result.get("counts") or {}).items()}
    raw_items = list(result.get("items") or [])
    items = _run_items(raw_items)
    if not ctx.dry_run:
        _update_posts(db, ctx.run_id, raw_items)

    fatal = result.get("fatal_reason")
    if fatal:
        status = "failed"
    elif counts.get("submit_failed", 0) > 0 or counts.get("parse_failed", 0) > 0:
        status = "warning"
    else:
        status = "success"
    return RunOutcome(status=status, counts=counts, items=items, error_reason=fatal)
