"""MOVE / DEL 在 18x 一侧：启动前准备命令和输入文件，结束后解析日志整理结果。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy.orm import Session

import app as app_package
from app.schemas.keywords import KeywordEntryResponse
from app.services.keywords.registry_service import KeywordRegistryService
from app.services.script_jobs import run_store
from app.services.script_jobs.definitions import PreparedCommand, RunContext, RunOutcome
from app.services.script_jobs.logs import LOG_FILE_NAME
from app.services.script_jobs.media_output import ParseResult, parse_del_dry_run, parse_output


PROJECT_ROOT = Path(app_package.__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "scripts" / "jobs"
MOVE_SCRIPT = JOBS_DIR / "move_ssd_cache_to_disk2.sh"


def export_keywords(db: Session, keyword_type: str, path: Path) -> int:
    """把启用的某类关键词按 GET /api/keywords 的返回格式写成文件，供 DEL 两个脚本读取（不再登录接口）。

    条目、顺序和字段都与接口分页拼起来的结果一致；脚本里的过滤和匹配代码不变。返回条数。
    """
    entries, _total = KeywordRegistryService(db).list_entries(
        keyword_type=keyword_type, status="active", skip=0, limit=1_000_000
    )
    payload = {
        "total": len(entries),
        "entries": [KeywordEntryResponse.model_validate(entry).model_dump(mode="json") for entry in entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return len(entries)


def move_prepare(db: Session | None, ctx: RunContext) -> PreparedCommand:
    """MOVE：用 bash 运行仓库里的原脚本，源和目标目录经环境变量传入（不拼进命令行字符串）。"""
    argv = ["bash", str(MOVE_SCRIPT)]
    if ctx.dry_run:
        argv.append("--dry-run")
    env = dict(os.environ)
    env["MOVE_SOURCE_DIR"] = ctx.params["source_dir"]
    env["MOVE_TARGET_DIR"] = ctx.params["target_dir"]
    return PreparedCommand(argv=argv, env=env)


def _read_log(ctx: RunContext) -> str | None:
    path = ctx.run_dir / LOG_FILE_NAME
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _parse(ctx: RunContext, output: str) -> ParseResult:
    if ctx.job_name == "DEL_SOMETHING" and ctx.dry_run:
        return parse_del_dry_run(output)
    return parse_output(ctx.job_name, output)


def media_finalize(db: Session | None, ctx: RunContext, exit_code: int) -> RunOutcome:
    """解析本次日志：计数和名单沿用阶段 6 的解析规则，状态按阶段 6 的判定。"""
    output = _read_log(ctx)
    if output is None:
        return RunOutcome(status="failed", counts={}, items=[], error_reason="没有找到运行日志")
    result = _parse(ctx, output)
    status = run_store.status_for(exit_code, result.counts, [item["kind"] for item in result.items])
    reason = f"运行异常退出（退出码 {exit_code}）" if exit_code != 0 else None
    return RunOutcome(status=status, counts=result.counts, items=result.items, error_reason=reason)


def media_salvage(db: Session | None, ctx: RunContext) -> RunOutcome:
    """被停止、超时或重启打断时：解析已写出的日志，找回已删除、已移动的部分。

    MOVE 被打断时没有汇总行，解析器会补一个“失败”计数；这里去掉它，状态由执行器另行标记。
    """
    output = _read_log(ctx)
    if output is None:
        return RunOutcome(status="", counts={}, items=[], error_reason=None)
    result = _parse(ctx, output)
    counts = dict(result.counts)
    if ctx.job_name == "MOVE_SSD_CACHE_TO_DISK2" and not result.summary_found:
        counts["failed"] = 0
    return RunOutcome(status="", counts=counts, items=result.items, error_reason=None)
