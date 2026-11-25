"""解析论坛页面：列表页、帖子页、安全验证页和 Cloudflare 挑战页。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup


SITE_ROOT = "https://sehuatang.org/"
_TID_RE = re.compile(r"thread-(\d+)-|[?&]tid=(\d+)")
_MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+")
_SAFEID_RE = re.compile(r"var safeid='([^']+)'")


@dataclass(frozen=True)
class ListPost:
    tid: str
    title: str
    url: str


@dataclass(frozen=True)
class ThreadLinks:
    magnets: list[str]
    attachment_urls: list[str]


def _absolute(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return SITE_ROOT + href.lstrip("/")


def tid_from_url(url: str) -> str | None:
    """从帖子地址里取帖子编号：thread-<tid>-… 或 tid=<tid>。"""
    match = _TID_RE.search(url or "")
    if match is None:
        return None
    return match.group(1) or match.group(2)


def parse_list(html: str) -> list[ListPost]:
    """列表页里的帖子（a.s.xst），同一页按帖子编号去重。"""
    soup = BeautifulSoup(html, "html.parser")
    posts: list[ListPost] = []
    seen: set[str] = set()
    for link in soup.select("a.s.xst"):
        href = link.get("href") or ""
        tid = tid_from_url(href)
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        posts.append(ListPost(tid=tid, title=link.get_text().strip(), url=_absolute(href)))
    return posts


def parse_thread(html: str) -> ThreadLinks:
    """帖子页里的磁力链接（保持顺序去重）和种子附件下载地址。"""
    magnets = list(dict.fromkeys(_MAGNET_RE.findall(html)))
    soup = BeautifulSoup(html, "html.parser")
    attachments: list[str] = []
    for link in soup.select('a[href*="mod=attachment"]'):
        text = link.get_text()
        if "torrent" in text.lower() or "下载附件" in text:
            url = _absolute(link.get("href") or "")
            if url not in attachments:
                attachments.append(url)
    return ThreadLinks(magnets=magnets, attachment_urls=attachments)


def extract_safeid(html: str) -> str | None:
    """站点“安全验证 / 18 岁确认”页里的 safeid；不是验证页返回 None。"""
    if "static/safe/js" not in html:
        return None
    match = _SAFEID_RE.search(html)
    return match.group(1) if match else None


def is_challenge(status: int, html: str) -> bool:
    """Cloudflare 挑战页（cf_clearance 失效时出现）。"""
    return status in (403, 503) or "_cf_chl_opt" in html
