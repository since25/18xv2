#!/usr/bin/env python3
"""解析 Unraid 两个脚本的输出并回报到 18x。

这个文件只依赖 Python 标准库，异常时始终返回 0，避免影响原脚本的退出码。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


SCRIPT_DEL = "DEL_SOMETHING"
SCRIPT_MOVE = "MOVE_SSD_CACHE_TO_DISK2"
COUNT_KEYS = (
    "deleted_dirs",
    "deleted_files",
    "empty_dirs",
    "moved_new",
    "moved_rescan",
    "ambiguous",
    "skipped",
    "errors",
    "warnings",
    "unparsed_lines",
    "moved",
    "duplicates_removed",
    "failed",
)
_DEL_KNOWN_TAGS = {
    "DELETED",
    "EMPTY",
    "MOVED",
    "SKIPPED",
    "ERROR",
    "错误",
    "WARN",
    "ALREADY-PLACED",
    "SUMMARY",
    "INFO",
    "SKIP",
    "处理",
    "完成",
    "BACKUP",
    "DRY-RUN",
}
_TAG_RE = re.compile(r"^\[(?P<tag>[^\]]+)\]")
_HIT_LINE_RE = re.compile(r"^命中(?:标准词|词项)\s*[:：]\s*(?P<keyword>.+?)\s*$")


@dataclass(slots=True)
class ParseResult:
    counts: dict[str, int]
    items: list[dict[str, str | None]]
    summary_found: bool = True


def _counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


def _item(
    kind: str,
    *,
    path: str | None = None,
    target_path: str | None = None,
    keyword: str | None = None,
    message: str | None = None,
) -> dict[str, str | None]:
    return {
        "kind": kind,
        "path": path,
        "target_path": target_path,
        "keyword": keyword,
        "message": message,
    }


def _rest_after_marker(line: str, marker: str) -> str:
    rest = line[len(marker) :].strip()
    if rest.startswith((":", "：")):
        rest = rest[1:].strip()
    return rest


def _path_or_message(rest: str) -> tuple[str | None, str | None]:
    """日志没有统一的错误行格式时，路径放 path，其余文字放 message。"""
    if not rest:
        return None, None
    if rest.startswith(("/", "\\")):
        return rest, None
    return None, rest


def _strip_label(rest: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        prefix = f"{label}："
        if rest.startswith(prefix):
            return rest[len(prefix) :].strip()
        prefix = f"{label}:"
        if rest.startswith(prefix):
            return rest[len(prefix) :].strip()
    return rest


def _tag_name(line: str) -> str | None:
    match = _TAG_RE.match(line)
    return match.group("tag") if match else None


def _is_known_del_tag(tag: str) -> bool:
    return tag in _DEL_KNOWN_TAGS or tag.startswith("AMBIGUOUS-")


def parse_del_something_output(output: str) -> ParseResult:
    """解析 DEL_SOMETHING 的标记行，只报告未知标签和格式错误。"""
    counts = _counts()
    items: list[dict[str, str | None]] = []
    lines = output.splitlines()
    in_summary = False
    ignore_next_hit = False
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        index += 1
        if not line:
            continue
        if in_summary:
            continue
        if line.startswith("[SUMMARY]"):
            in_summary = True
            continue
        if ignore_next_hit:
            if _HIT_LINE_RE.match(line):
                ignore_next_hit = False
                continue
            ignore_next_hit = False

        if line.startswith("[ALREADY-PLACED]"):
            ignore_next_hit = True
            continue
        if line.startswith(("[INFO]", "[SKIP]")):
            continue

        deleted_match = re.match(r"^\[DELETED\]\s*已删除(目录|文件)\s*[:：]\s*(?P<path>\S.*)$", line)
        if deleted_match:
            kind = "deleted_dir" if deleted_match.group(1) == "目录" else "deleted_file"
            count_key = "deleted_dirs" if kind == "deleted_dir" else "deleted_files"
            counts[count_key] += 1
            items.append(_item(kind, path=deleted_match.group("path").strip()))
            continue
        if line.startswith("[DELETED]"):
            counts["unparsed_lines"] += 1
            continue
        if line.startswith("[EMPTY]"):
            path = _strip_label(_rest_after_marker(line, "[EMPTY]"), ("空文件夹", "空目录")) or None
            counts["empty_dirs"] += 1
            items.append(_item("empty_dir", path=path))
            continue
        moved_match = re.match(r"^\[MOVED\]\s*(?P<source>.+?)\s+->\s+(?P<target>.+?)\s*$", line)
        if moved_match:
            if index >= len(lines):
                counts["unparsed_lines"] += 1
                continue
            keyword_line = lines[index].strip()
            keyword_match = _HIT_LINE_RE.match(keyword_line)
            if keyword_match is None:
                counts["unparsed_lines"] += 1
                continue
            index += 1
            source = moved_match.group("source").strip()
            target = moved_match.group("target").strip()
            keyword = keyword_match.group("keyword").strip()
            kind = "moved_rescan" if re.search(r"已整理/抖音(?:风)?(?:/|$)", source) else "moved_new"
            counts[kind] += 1
            items.append(_item(kind, path=source, target_path=target, keyword=keyword))
            continue
        if line.startswith("[MOVED]"):
            counts["unparsed_lines"] += 1
            continue
        tag = _tag_name(line)
        if tag is None:
            # 无标签的说明、分隔线和自由文本不属于结构化日志。
            continue
        if not _is_known_del_tag(tag):
            counts["unparsed_lines"] += 1
            continue
        for marker, kind, count_key in (
            ("[AMBIGUOUS-LOW]", "ambiguous", "ambiguous"),
            ("[SKIPPED]", "skipped", "skipped"),
            ("[WARN]", "warning", "warnings"),
        ):
            if line.startswith(marker):
                rest = _strip_label(_rest_after_marker(line, marker), ("文件过大", "跳过"))
                path, message = _path_or_message(rest)
                counts[count_key] += 1
                items.append(_item(kind, path=path, message=message))
                break
        else:
            error_marker = None
            if line.startswith("[ERROR]"):
                error_marker = "[ERROR]"
            elif line.startswith("[错误]"):
                error_marker = "[错误]"
            if error_marker is not None:
                rest = _rest_after_marker(line, error_marker)
                path, message = _path_or_message(rest)
                counts["errors"] += 1
                items.append(_item("error", path=path, message=message))
            else:
                # 其余已知标签是分隔线或状态提示，忽略其正文。
                continue

    return ParseResult(counts=counts, items=items)


_MOVE_SUMMARY_RE = re.compile(
    r"^完成\s*[:：]\s*移动\s*(?P<moved>\d+)\s*个\s*[,，]\s*"
    r"删除重复\s*(?P<duplicates_removed>\d+)\s*个\s*[,，]\s*"
    r"跳过\s*(?P<skipped>\d+)\s*个\s*[,，]\s*失败\s*(?P<failed>\d+)\s*个\s*$"
)


def parse_move_ssd_cache_output(output: str) -> ParseResult:
    """解析搬运脚本的汇总行，名单只保留跳过和失败项。"""
    counts = _counts()
    items: list[dict[str, str | None]] = []
    summary_found = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        summary_match = _MOVE_SUMMARY_RE.match(line)
        if summary_match:
            summary_found = True
            for key in ("moved", "duplicates_removed", "skipped", "failed"):
                counts[key] = int(summary_match.group(key))
            continue
        skipped_match = re.match(r"^(?:\[SKIPPED\]|\[SKIP\])\s*(.+?)\s*$|^跳过\s*[:：]\s*(.+?)\s*$", line)
        if skipped_match:
            items.append(_item("skipped", path=(skipped_match.group(1) or skipped_match.group(2)).strip()))
            continue
        failed_match = re.match(
            r"^(?:\[FAILED?\]\s*|\[ERROR\]\s*|(?:移动)?失败\s*[:：]\s*|\[移动失败\]\s*)(.+?)\s*$",
            line,
        )
        if failed_match:
            items.append(_item("error", path=failed_match.group(1).strip()))
            continue
        # MOVE 的其余输出是分隔线或自由文本，不计入未识别行。

    if not summary_found:
        # 没有汇总行时无法证明运行成功；用一个失败计数让服务端能计算 failed。
        counts["failed"] = max(1, counts["failed"])
    return ParseResult(counts=counts, items=items, summary_found=summary_found)


def parse_output(script_name: str, output: str) -> ParseResult:
    """按脚本名选择解析器，供单独测试和其他本地工具调用。"""
    if script_name == SCRIPT_DEL:
        return parse_del_something_output(output)
    if script_name == SCRIPT_MOVE:
        return parse_move_ssd_cache_output(output)
    raise ValueError(f"不支持的脚本名: {script_name}")


# 保留简短别名，方便部署机上的独立测试直接导入。
parse_del_output = parse_del_something_output
parse_move_output = parse_move_ssd_cache_output


def build_report_payload(script_name: str, started_at: str, exit_code: int, output: str) -> dict[str, object]:
    if script_name == SCRIPT_DEL:
        result = parse_del_something_output(output)
    elif script_name == SCRIPT_MOVE:
        result = parse_move_ssd_cache_output(output)
    else:
        raise ValueError(f"不支持的脚本名: {script_name}")
    return {
        "run_key": f"{script_name}:{started_at}",
        "script_name": script_name,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "exit_code": int(exit_code),
        "counts": result.counts,
        "items": result.items,
    }


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _post_json(opener, url: str, payload: dict[str, object], timeout: float = 30.0) -> None:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        response.read()


def _send_report(payload: dict[str, object], credentials_file: str, api_url: str) -> bool:
    credentials = _read_env_file(credentials_file)
    username = credentials.get("KEYWORDS_API_USERNAME")
    password = credentials.get("KEYWORDS_API_PASSWORD")
    if not username or not password:
        return False
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    base_url = api_url.rstrip("/")
    for attempt in range(3):
        try:
            _post_json(opener, f"{base_url}/auth/login", {"username": username, "password": password})
            _post_json(opener, f"{base_url}/script-runs", payload)
            return True
        except (HTTPError, URLError, TimeoutError, OSError):
            if attempt == 2:
                return False
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回报 Unraid 脚本运行结果")
    parser.add_argument("script_name")
    parser.add_argument("started_at")
    parser.add_argument("exit_code", type=int)
    parser.add_argument("output_file")
    parser.add_argument("credentials_file")
    parser.add_argument("--api-url", default=os.environ.get("SCRIPT_REPORT_API_URL", "http://192.168.70.138:8010/api"))
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # 回报脚本不能把参数问题传递给原脚本；正常帮助输出也视为安全退出。
        return 0
    try:
        if args.dry_run:
            return 0
        output = Path(args.output_file).read_text(encoding="utf-8", errors="replace")
        payload = build_report_payload(args.script_name, args.started_at, args.exit_code, output)
        if not _send_report(payload, args.credentials_file, args.api_url):
            print("脚本回报失败，已跳过", file=sys.stderr)
    except Exception:  # noqa: BLE001 - 回报不能影响原脚本
        print("脚本回报失败，已跳过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
