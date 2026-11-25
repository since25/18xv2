"""sehuatang 站点会话（cookie 和浏览器 User-Agent）的文件存取。

cf_clearance 与 User-Agent 绑定，两者要一起更换。文件权限 0600，内容从不回显给页面。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class SiteSession:
    cookies: dict[str, str]
    user_agent: str


def parse_cookie_header(raw: str) -> dict[str, str]:
    """把浏览器里复制的 `a=1; b=2` 解析成字典。"""
    cookies: dict[str, str] = {}
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def save_site_session(path: Path, cookie_header: str, user_agent: str) -> datetime:
    """保存 cookie 和 User-Agent，返回保存时间。cookie 里没有任何 名=值 时抛 ValueError。"""
    cookies = parse_cookie_header(cookie_header)
    if not cookies:
        raise ValueError("cookie 格式不对：应为浏览器里复制的“名=值; 名=值”")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    payload = {
        "cookies": cookies,
        "user_agent": user_agent.strip(),
        "updated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return now


def _read(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_site_session(path: Path) -> SiteSession | None:
    payload = _read(path)
    if not payload or not payload.get("cookies"):
        return None
    return SiteSession(cookies=dict(payload["cookies"]), user_agent=str(payload.get("user_agent") or ""))


def site_session_status(path: Path) -> dict[str, object]:
    """只返回是否已设置和更新时间，绝不包含 cookie 内容。"""
    payload = _read(path)
    if not payload or not payload.get("cookies"):
        return {"configured": False, "updated_at": None}
    return {"configured": True, "updated_at": payload.get("updated_at")}
