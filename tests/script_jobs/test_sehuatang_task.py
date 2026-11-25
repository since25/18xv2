from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.keywords import KeywordAlias, KeywordEntry
from app.models.script_runs import SehuatangPost
from app.services.script_jobs import run_store, sehuatang_task
from app.services.script_jobs.definitions import RunContext


def _entry(name: str, *, keyword_type="blacklist", status="active", aliases=()) -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=name.lower(),
        keyword_type=keyword_type,
        status=status,
    )
    entry.aliases = [KeywordAlias(alias=alias, alias_normalized=alias.lower()) for alias in aliases]
    return entry


def _ctx(tmp_path: Path, run_id: int, *, dry_run=False) -> RunContext:
    directory = tmp_path / "sehuatang" / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=run_id,
        job_name="sehuatang",
        params={"pages": 4, "forum_url": "https://sehuatang.org/f?page={page}", "qb_category": "国产BT"},
        dry_run=dry_run,
        run_dir=directory,
    )


def _write_result(ctx: RunContext, *, counts=None, items=(), fatal_reason=None) -> None:
    payload = {"counts": counts or {}, "items": list(items), "fatal_reason": fatal_reason}
    (ctx.run_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _item(kind: str, tid: str, **extra) -> dict:
    return {
        "kind": kind,
        "tid": tid,
        "title": f"示例标题{tid}",
        "url": f"https://sehuatang.org/thread-{tid}-1-1.html",
        "keyword": None,
        "message": None,
        **extra,
    }


def _new_run(db_session, *, dry_run=False):
    return run_store.create_run(db_session, job_name="sehuatang", trigger="manual", dry_run=dry_run, status="running")


def test_load_block_terms_includes_aliases_skips_short_and_inactive(db_session):
    db_session.add_all(
        [
            _entry("AI增强", aliases=["AI強化", "强"]),
            _entry("停用词", status="disabled"),
            _entry("白名单词", keyword_type="whitelist"),
            _entry("X"),
        ]
    )
    db_session.commit()
    terms = sehuatang_task.load_block_terms(db_session)
    assert sorted(display for display, _ in terms) == ["AI增强", "AI強化"]
    assert ("AI增强", "ai增强") in terms


def test_prepare_writes_input_with_submitted_tids_and_no_secrets(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("QB_URL", "https://qb.invalid:16666")
    monkeypatch.setenv("QB_USERNAME", "user")
    monkeypatch.setenv("QB_PASSWORD", "SECRET-PW")
    get_settings.cache_clear()
    try:
        db_session.add_all(
            [
                _entry("AI增强"),
                SehuatangPost(tid="1", title="t", url="u", last_outcome="submitted"),
                SehuatangPost(tid="2", title="t", url="u", last_outcome="title_blocked"),
            ]
        )
        db_session.commit()
        ctx = _ctx(tmp_path, 7)
        prepared = sehuatang_task.prepare(db_session, ctx)
    finally:
        get_settings.cache_clear()

    payload = json.loads((ctx.run_dir / "input.json").read_text(encoding="utf-8"))
    assert payload["submitted_tids"] == ["1"]
    assert payload["pages"] == 4
    assert payload["qb_category"] == "国产BT"
    assert payload["terms"] == [["AI增强", "ai增强"]]
    assert "SECRET-PW" not in (ctx.run_dir / "input.json").read_text(encoding="utf-8")
    assert prepared.env["QB_PASSWORD"] == "SECRET-PW"
    assert prepared.env["PYTHONUNBUFFERED"] == "1"
    assert Path(prepared.env["SEHUATANG_SESSION_PATH"]).is_absolute()
    assert prepared.argv[1:4] == ["-m", "app.services.script_jobs.sehuatang.main", "--input"]


def test_finalize_maps_status_and_items(db_session, tmp_path):
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    _write_result(
        ctx,
        counts={"submitted": 1, "submit_failed": 1},
        items=[_item("submitted", "10", message="种子"), _item("submit_failed", "11", message="qB 拒收")],
    )
    outcome = sehuatang_task.finalize(db_session, ctx, 0)
    assert outcome.status == "warning"
    assert outcome.counts["submitted"] == 1
    assert outcome.items[0] == {
        "kind": "submitted",
        "path": "示例标题10",
        "target_path": "https://sehuatang.org/thread-10-1-1.html",
        "keyword": None,
        "message": "种子",
    }
    posts = {post.tid: post for post in db_session.scalars(select(SehuatangPost)).all()}
    assert posts["10"].last_outcome == "submitted"
    assert posts["10"].submitted_at is not None
    assert posts["10"].last_run_id == run.id
    assert posts["11"].last_outcome == "submit_failed"


@pytest.mark.parametrize(
    ("exit_code", "write", "expected_reason"),
    [(1, True, "运行异常退出"), (0, False, "运行异常退出")],
)
def test_finalize_crash_or_missing_result_is_failed(db_session, tmp_path, exit_code, write, expected_reason):
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    if write:
        _write_result(ctx, counts={"submitted": 1})
    outcome = sehuatang_task.finalize(db_session, ctx, exit_code)
    assert outcome.status == "failed"
    assert outcome.error_reason == expected_reason


def test_finalize_fatal_reason_is_failed_with_reason(db_session, tmp_path):
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    _write_result(ctx, fatal_reason="站点 cookie 可能失效：列表页全部失败")
    outcome = sehuatang_task.finalize(db_session, ctx, 0)
    assert outcome.status == "failed"
    assert outcome.error_reason == "站点 cookie 可能失效：列表页全部失败"


def test_finalize_qb_login_failure_leaves_posts_not_submitted(db_session, tmp_path):
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    _write_result(
        ctx,
        counts={"submit_failed": 1},
        items=[_item("submit_failed", "20", message="qB 登录失败（HTTP 403）")],
        fatal_reason="qB 登录失败（HTTP 403）",
    )
    outcome = sehuatang_task.finalize(db_session, ctx, 0)
    assert outcome.status == "failed"
    post = db_session.scalar(select(SehuatangPost).where(SehuatangPost.tid == "20"))
    assert post.last_outcome == "submit_failed"
    assert post.submitted_at is None


def test_finalize_dry_run_does_not_touch_posts(db_session, tmp_path):
    run = _new_run(db_session, dry_run=True)
    ctx = _ctx(tmp_path, run.id, dry_run=True)
    _write_result(ctx, counts={"submitted": 1}, items=[_item("submitted", "30", message="演练，未实际提交")])
    outcome = sehuatang_task.finalize(db_session, ctx, 0)
    assert outcome.status == "success"
    assert db_session.scalars(select(SehuatangPost)).all() == []


def _write_partial(ctx: RunContext, items: list[dict], trailing: str = "") -> None:
    lines = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    (ctx.run_dir / "items.jsonl").write_text(lines + trailing, encoding="utf-8")


def test_salvage_reads_partial_items_and_marks_submitted(db_session, tmp_path):
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    _write_partial(
        ctx,
        [_item("submitted", "50", message="种子"), _item("title_blocked", "51", keyword="AI增强")],
        trailing='{"kind": "submitted", "tid": "5',  # 被打断时写了一半的行
    )
    outcome = sehuatang_task.salvage(db_session, ctx)
    assert outcome.counts["submitted"] == 1
    assert outcome.counts["title_blocked"] == 1
    assert [item["kind"] for item in outcome.items] == ["submitted", "title_blocked"]
    post = db_session.scalar(select(SehuatangPost).where(SehuatangPost.tid == "50"))
    assert post.last_outcome == "submitted"
    assert post.submitted_at is not None


def test_salvage_dry_run_and_missing_file(db_session, tmp_path):
    run = _new_run(db_session, dry_run=True)
    ctx = _ctx(tmp_path, run.id, dry_run=True)
    assert sehuatang_task.salvage(db_session, ctx).items == []
    _write_partial(ctx, [_item("submitted", "60", message="演练，未实际提交")])
    outcome = sehuatang_task.salvage(db_session, ctx)
    assert outcome.counts["submitted"] == 1
    assert db_session.scalars(select(SehuatangPost)).all() == []


def test_submitted_post_not_downgraded_later(db_session, tmp_path):
    db_session.add(SehuatangPost(tid="40", title="旧标题", url="u", last_outcome="submitted"))
    db_session.commit()
    run = _new_run(db_session)
    ctx = _ctx(tmp_path, run.id)
    _write_result(ctx, counts={"title_blocked": 1}, items=[_item("title_blocked", "40", keyword="AI增强")])
    sehuatang_task.finalize(db_session, ctx, 0)
    post = db_session.scalar(select(SehuatangPost).where(SehuatangPost.tid == "40"))
    assert post.last_outcome == "submitted"
