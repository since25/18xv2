#!/usr/bin/env python3
"""解析 Unraid 两个脚本的输出并回报到 18x。

解析规则在 `app/services/script_jobs/media_output.py`（只用标准库）；本文件只负责回报。
异常时始终返回 0，避免影响原脚本的退出码。
注意：Unraid 上部署的是本文件拆分前的独立拷贝，切换到 18x 执行后随原脚本一起停用。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

# 解析规则已搬进 app；单独运行本文件时把仓库根目录放进模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.script_jobs.media_output import (  # noqa: E402
    SCRIPT_DEL,
    SCRIPT_MOVE,
    ParseResult,
    parse_del_output,
    parse_del_something_output,
    parse_move_output,
    parse_move_ssd_cache_output,
    parse_output,
)

__all__ = [
    "ParseResult",
    "build_report_payload",
    "main",
    "parse_del_output",
    "parse_del_something_output",
    "parse_move_output",
    "parse_move_ssd_cache_output",
    "parse_output",
]


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
