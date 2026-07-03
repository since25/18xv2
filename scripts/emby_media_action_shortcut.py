#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

DEFAULT_COOKIE_PATH = Path.home() / ".18x_emby_media_actions_cookies.txt"


class RequestFailed(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def build_payload(
    action: str,
    path: str,
    source: str,
    *,
    title: str | None = None,
    emby_item_id: str | None = None,
    emby_payload: dict | None = None,
    url: str | None = None,
    nfo_path: str | None = None,
    nfo_xml: str | None = None,
) -> dict:
    action_map = {
        "delete-plan": "delete_plan",
        "blacklist": "metadata_blacklist",
        "whitelist": "metadata_whitelist",
    }
    payload = {
        "action": action_map[action],
        "path": path,
        "source": source,
        "emby_item_id": emby_item_id or path,
        "title": title or Path(path).name or path,
    }
    if emby_payload is not None:
        payload["emby_payload"] = emby_payload
    if url is not None:
        payload["url"] = url
    if nfo_path is not None:
        payload["nfo_path"] = nfo_path
    if nfo_xml is not None:
        payload["nfo_xml"] = nfo_xml
    return payload


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
    username = args.username or os.getenv("EMBY_MEDIA_ACTIONS_USERNAME") or "wang"
    password = args.password or os.getenv("EMBY_MEDIA_ACTIONS_PASSWORD")
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")
    _json_request(
        opener,
        f"{base_url}/auth/login",
        {"username": username, "password": password},
    )
    _save_cookie_jar(cookie_jar, cookie_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="提交 Emby 媒体动作到后端。")
    parser.add_argument("action", choices=["delete-plan", "blacklist", "whitelist"])
    parser.add_argument("--path", required=True)
    parser.add_argument("--title", help="媒体标题；IINA/mpv 可传 media-title 或 filename")
    parser.add_argument("--emby-item-id", help="Emby item id；没有时后端会按路径/标题解析")
    parser.add_argument("--emby-payload-json", help="Emby item JSON 对象字符串")
    parser.add_argument("--url", help="播放/strm 指向的远端 URL")
    parser.add_argument("--nfo-path", help="NFO 文件路径")
    parser.add_argument("--nfo-xml", help="NFO XML 内容")
    parser.add_argument(
        "--base-url",
        default=os.getenv("EMBY_MEDIA_ACTIONS_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--source", default="shortcut", help="写入媒体动作的来源标记")
    parser.add_argument("--username", help="登录用户名；默认读取 EMBY_MEDIA_ACTIONS_USERNAME 或 wang")
    parser.add_argument("--password", help="登录密码；也可用 EMBY_MEDIA_ACTIONS_PASSWORD")
    parser.add_argument(
        "--cookie-path",
        default=str(DEFAULT_COOKIE_PATH),
        help="会话 cookie 保存位置",
    )
    parser.add_argument("--print-response", action="store_true", help="打印接口完整响应")
    args = parser.parse_args()
    emby_payload = None
    if args.emby_payload_json:
        try:
            emby_payload = json.loads(args.emby_payload_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--emby-payload-json must be valid JSON: {exc}")
        if not isinstance(emby_payload, dict):
            parser.error("--emby-payload-json must be a JSON object")

    base_url = args.base_url.rstrip("/")
    cookie_path = Path(args.cookie_path).expanduser()
    cookie_jar = _load_cookie_jar(cookie_path)
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    payload = build_payload(
        args.action,
        args.path,
        args.source,
        title=args.title,
        emby_item_id=args.emby_item_id,
        emby_payload=emby_payload,
        url=args.url,
        nfo_path=args.nfo_path,
        nfo_xml=args.nfo_xml,
    )
    url = f"{base_url}/emby-media-actions/intake"

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
        print(f"已提交 Emby 媒体动作：{args.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
