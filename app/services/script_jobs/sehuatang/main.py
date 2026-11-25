"""sehuatang 子进程入口。

用法：python -m app.services.script_jobs.sehuatang.main --input input.json --result result.json

只依赖本包、site_session 和环境变量（QB_URL / QB_USERNAME / QB_PASSWORD / SEHUATANG_SESSION_PATH），
不连数据库。正常结束退出码 0；未捕获的异常退出码 1。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

from app.services.script_jobs.sehuatang.job import JobInput, JobResult, run_job
from app.services.script_jobs.sehuatang.qb import QbClient
from app.services.script_jobs.sehuatang.site import CurlSiteClient
from app.services.script_jobs.site_session import SiteSession, load_site_session


SLEEP = time.sleep


def make_site(session: SiteSession):
    return CurlSiteClient(session.cookies, session.user_agent)


def make_qb() -> QbClient | None:
    url = os.environ.get("QB_URL", "").strip()
    username = os.environ.get("QB_USERNAME", "").strip()
    password = os.environ.get("QB_PASSWORD", "")
    if not url or not username or not password:
        return None
    return QbClient(url, username, password)


def _log(message: str) -> None:
    print(message, flush=True)


def _write_result(path: Path, result: JobResult) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_input(path: Path) -> JobInput:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return JobInput(
        dry_run=bool(raw["dry_run"]),
        pages=int(raw["pages"]),
        forum_url=str(raw["forum_url"]),
        qb_category=str(raw["qb_category"]),
        terms=[(str(display), str(term)) for display, term in raw["terms"]],
        submitted_tids=set(raw.get("submitted_tids") or []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sehuatang 抓取并提交 qB")
    parser.add_argument("--input", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)

    inp = _read_input(Path(args.input))
    result_path = Path(args.result)
    _log(f"开始：{'演练' if inp.dry_run else '真实运行'}，抓 {inp.pages} 页，黑名单 {len(inp.terms)} 个词")

    session = load_site_session(Path(os.environ.get("SEHUATANG_SESSION_PATH", "data/sehuatang/site_session.json")))
    if session is None:
        result = JobResult(fatal_reason="尚未设置站点 cookie")
        _log(result.fatal_reason)
        _write_result(result_path, result)
        return 0

    result = run_job(inp, make_site(session), None if inp.dry_run else make_qb(), log=_log, sleep=SLEEP)
    _write_result(result_path, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
