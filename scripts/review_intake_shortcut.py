#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_COOKIE_PATH = Path.home() / ".18x_review_intake_cookies.txt"


class RequestFailed(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _json_request(opener, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body
        try:
            detail = json.loads(body).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise RequestFailed(exc.code, str(detail)) from exc
    except URLError as exc:
        raise RequestFailed(0, f"连接失败：{exc.reason}") from exc
    return json.loads(body) if body else {}


def _load_cookie_jar(path: Path) -> MozillaCookieJar:
    jar = MozillaCookieJar(str(path))
    if path.exists():
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    return jar


def _save_cookie_jar(jar: MozillaCookieJar, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    jar.save(str(path), ignore_discard=True, ignore_expires=True)


def _login(opener, cookie_jar: MozillaCookieJar, cookie_path: Path, base_url: str, args) -> None:
    username = args.username or os.getenv("REVIEW_INTAKE_USERNAME") or "wang"
    password = args.password or os.getenv("REVIEW_INTAKE_PASSWORD")
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")
    _json_request(
        opener,
        f"{base_url}/auth/login",
        {"username": username, "password": password},
    )
    _save_cookie_jar(cookie_jar, cookie_path)


def _clipboard_path() -> str:
    result = subprocess.run(
        ["pbpaste"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _resolve_path(args) -> str:
    if args.path:
        return args.path.strip()
    if args.stdin:
        return sys.stdin.read().strip()
    return _clipboard_path()


def main() -> int:
    parser = argparse.ArgumentParser(description="提交本地路径到 18x 待审核池。")
    parser.add_argument("bucket", choices=["whitelist", "blacklist"], help="目标待审区域")
    parser.add_argument("--path", help="直接传入视频路径；不传则读取剪贴板")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取路径")
    parser.add_argument(
        "--base-url",
        default=os.getenv("REVIEW_INTAKE_BASE_URL", DEFAULT_BASE_URL),
        help="API 根地址；本地后端用 http://127.0.0.1:8000，生产 nginx 用 http://host:8010/api",
    )
    parser.add_argument("--source", default="shortcut", help="写入待审项的来源标记")
    parser.add_argument("--username", help="登录用户名；默认读取 REVIEW_INTAKE_USERNAME 或 wang")
    parser.add_argument("--password", help="登录密码；也可用 REVIEW_INTAKE_PASSWORD")
    parser.add_argument(
        "--cookie-path",
        default=str(DEFAULT_COOKIE_PATH),
        help="会话 cookie 保存位置",
    )
    parser.add_argument("--print-response", action="store_true", help="打印接口完整响应")
    args = parser.parse_args()

    raw_path = _resolve_path(args)
    if not raw_path:
        print("未获取到路径：请传 --path，或先把路径放入剪贴板。", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    cookie_path = Path(args.cookie_path).expanduser()
    cookie_jar = _load_cookie_jar(cookie_path)
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    payload = {"raw_path": raw_path, "source": args.source}
    url = f"{base_url}/review-intake/{args.bucket}"

    try:
        response = _json_request(opener, url, payload)
    except RequestFailed as exc:
        if exc.status != 401:
            print(exc.detail, file=sys.stderr)
            return 1
        _login(opener, cookie_jar, cookie_path, base_url, args)
        try:
            response = _json_request(opener, url, payload)
        except RequestFailed as retry_exc:
            print(retry_exc.detail, file=sys.stderr)
            return 1

    _save_cookie_jar(cookie_jar, cookie_path)
    if args.print_response:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        bucket_label = "白名单" if args.bucket == "whitelist" else "黑名单"
        print(f"已提交到{bucket_label}待审核：#{response.get('id')} {response.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
