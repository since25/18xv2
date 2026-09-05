#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_COOKIE_PATH = Path.home() / ".18x_v2_admin_cookies.txt"
DEFAULT_LOG_PATH = Path.home() / ".18x_review_intake.log"
DEFAULT_ENV_PATH = Path.home() / "selfapp" / "IINA-script" / ".env"
SHARED_BASE_URL_ENV = "X18V2_BASE_URL"
SHARED_ENV_FILE_ENV = "X18V2_ENV_FILE"


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


def _default_base_url(specific_env: str) -> str:
    return os.getenv(specific_env) or os.getenv(SHARED_BASE_URL_ENV) or DEFAULT_BASE_URL


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}

    values = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _credential_env_path() -> Path:
    override = os.getenv(SHARED_ENV_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_ENV_PATH


def _login(opener, cookie_jar: MozillaCookieJar, cookie_path: Path, base_url: str, args) -> None:
    env_values = _read_env_file(_credential_env_path())
    username = (
        args.username
        or os.getenv("REVIEW_INTAKE_USERNAME")
        or env_values.get("18xv2_login_user")
        or "wang"
    )
    password = (
        args.password
        or os.getenv("REVIEW_INTAKE_PASSWORD")
        or env_values.get("18xv2_login_pass")
    )
    if password is None:
        if not sys.stdin.isatty():
            raise RequestFailed(
                401,
                "登录已过期：IINA 快捷脚本无法交互输入密码，请先刷新 cookie 或配置 REVIEW_INTAKE_PASSWORD。",
            )
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


def _is_url(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value))


def _resolve_path(args) -> str:
    if args.path:
        raw_path = args.path.strip()
    elif args.stdin:
        raw_path = sys.stdin.read().strip()
    else:
        raw_path = _clipboard_path()
    working_directory = (args.working_directory or "").strip()
    if (
        raw_path
        and working_directory
        and not raw_path.startswith("/")
        and not _is_url(raw_path)
    ):
        return str(Path(working_directory) / raw_path)
    return raw_path


def _log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            timestamp = datetime.now().isoformat(timespec="seconds")
            file.write(f"{timestamp} {message.rstrip()}\n")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="提交本地路径到 18x 待审核池。")
    parser.add_argument("bucket", nargs="?", choices=["whitelist", "blacklist"], help="目标待审区域")
    parser.add_argument("--path", help="直接传入视频路径；不传则读取剪贴板")
    parser.add_argument("--working-directory", help="当 --path 是相对路径时，用这个目录拼成绝对路径")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取路径")
    parser.add_argument(
        "--base-url",
        default=_default_base_url("REVIEW_INTAKE_BASE_URL"),
        help="API 根地址；也可用 REVIEW_INTAKE_BASE_URL 或 X18V2_BASE_URL",
    )
    parser.add_argument("--source", default="shortcut", help="写入待审项的来源标记")
    parser.add_argument("--username", help="登录用户名；默认读取 REVIEW_INTAKE_USERNAME 或 wang")
    parser.add_argument("--password", help="登录密码；也可用 REVIEW_INTAKE_PASSWORD")
    parser.add_argument(
        "--cookie-path",
        default=str(DEFAULT_COOKIE_PATH),
        help="会话 cookie 保存位置",
    )
    parser.add_argument(
        "--log-path",
        default=os.getenv("REVIEW_INTAKE_CLI_LOG", str(DEFAULT_LOG_PATH)),
        help="调试日志路径",
    )
    parser.add_argument("--login-only", action="store_true", help="只刷新登录 cookie，不提交路径")
    parser.add_argument("--print-response", action="store_true", help="打印接口完整响应")
    args = parser.parse_args()

    log_path = Path(args.log_path).expanduser()
    base_url = args.base_url.rstrip("/")
    cookie_path = Path(args.cookie_path).expanduser()
    cookie_jar = _load_cookie_jar(cookie_path)
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    if args.login_only:
        try:
            _login(opener, cookie_jar, cookie_path, base_url, args)
        except RequestFailed as exc:
            _log(log_path, f"login refresh failed: {exc.status} {exc.detail}")
            print(exc.detail, file=sys.stderr)
            return 1
        _log(log_path, "login refreshed")
        print("已刷新 18x v2 登录 cookie")
        return 0

    if args.bucket is None:
        parser.error("bucket is required unless --login-only is used")

    raw_path = _resolve_path(args)
    _log(log_path, f"bucket={args.bucket} raw_path={raw_path!r} working_directory={args.working_directory!r}")
    if not raw_path:
        _log(log_path, "failed: empty path")
        print("未获取到路径：请传 --path，或先把路径放入剪贴板。", file=sys.stderr)
        return 2

    payload = {"raw_path": raw_path, "source": args.source}
    url = f"{base_url}/review-intake/{args.bucket}"

    try:
        response = _json_request(opener, url, payload)
    except RequestFailed as exc:
        if exc.status != 401:
            _log(log_path, f"failed: {exc.status} {exc.detail}")
            print(exc.detail, file=sys.stderr)
            return 1
        _log(log_path, "login required")
        try:
            _login(opener, cookie_jar, cookie_path, base_url, args)
        except RequestFailed as login_exc:
            _log(log_path, f"login failed: {login_exc.status} {login_exc.detail}")
            print(login_exc.detail, file=sys.stderr)
            return 1
        try:
            response = _json_request(opener, url, payload)
        except RequestFailed as retry_exc:
            _log(log_path, f"failed after login: {retry_exc.status} {retry_exc.detail}")
            print(retry_exc.detail, file=sys.stderr)
            return 1

    _save_cookie_jar(cookie_jar, cookie_path)
    _log(log_path, f"ok: id={response.get('id')} status={response.get('status')}")
    if args.print_response:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        bucket_label = "白名单" if args.bucket == "whitelist" else "黑名单"
        print(f"已提交到{bucket_label}待审核：#{response.get('id')} {response.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
