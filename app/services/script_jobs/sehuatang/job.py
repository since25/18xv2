"""sehuatang 主流程：抓列表 → 标题过黑名单 → 跳过已提交 → 进帖子 → 种子内文件名再过黑名单 → 提交 qB。

打印的进度里只有页码、帖子编号和标题，不含 cookie、密码和请求头。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import random

from app.services.script_jobs.sehuatang.matching import Term, find_hit
from app.services.script_jobs.sehuatang.pages import ListPost, is_challenge, parse_list, parse_thread
from app.services.script_jobs.sehuatang.qb import QbError
from app.services.script_jobs.sehuatang.site import SiteClient
from app.services.script_jobs.sehuatang.torrent import TorrentParseError, list_names


COUNT_KEYS = (
    "pages_ok",
    "pages_failed",
    "posts_found",
    "title_blocked",
    "torrent_blocked",
    "skipped_seen",
    "submitted",
    "submit_failed",
    "parse_failed",
)
COOKIE_PREFIX = "站点 cookie 可能失效："
LIST_WAIT = (10, 20)
THREAD_WAIT = (2, 4)


@dataclass
class JobInput:
    dry_run: bool
    pages: int
    forum_url: str
    qb_category: str
    terms: list[Term]
    submitted_tids: set[str]


@dataclass
class JobResult:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNT_KEYS, 0))
    items: list[dict] = field(default_factory=list)
    fatal_reason: str | None = None

    def add(self, kind: str, post: ListPost, *, keyword: str | None = None, message: str | None = None) -> None:
        self.counts[kind] += 1
        self.items.append(
            {"kind": kind, "tid": post.tid, "title": post.title, "url": post.url, "keyword": keyword, "message": message}
        )


def _collect_posts(inp: JobInput, site: SiteClient, result: JobResult, log, sleep) -> tuple[list[ListPost], str | None]:
    posts: dict[str, ListPost] = {}
    challenge: str | None = None
    for page in range(1, inp.pages + 1):
        url = inp.forum_url.format(page=page)
        log(f"抓取列表第 {page} 页")
        try:
            response = site.get(url, timeout=20)
        except Exception as exc:  # noqa: BLE001 - 单页失败只计数
            result.counts["pages_failed"] += 1
            log(f"  列表第 {page} 页请求失败（{type(exc).__name__}）")
            continue
        if is_challenge(response.status, response.text):
            result.counts["pages_failed"] += 1
            challenge = f"第 {page} 页遇到 Cloudflare 挑战"
            log(f"  {challenge}")
            break
        if response.status != 200:
            result.counts["pages_failed"] += 1
            log(f"  列表第 {page} 页返回 HTTP {response.status}")
            continue
        page_posts = parse_list(response.text)
        result.counts["pages_ok"] += 1
        result.counts["posts_found"] += len(page_posts)
        for post in page_posts:
            posts.setdefault(post.tid, post)
        log(f"  第 {page} 页 {len(page_posts)} 帖")
        if page < inp.pages:
            sleep(random.uniform(*LIST_WAIT))
    return list(posts.values()), challenge


def _download_torrent(site: SiteClient, urls: list[str], log) -> tuple[bytes, list[str]] | None:
    for url in urls:
        try:
            response = site.get(url, timeout=15)
            return response.content, list_names(response.content)
        except TorrentParseError:
            log("  附件不是有效种子，跳过")
        except Exception as exc:  # noqa: BLE001
            log(f"  种子下载失败（{type(exc).__name__}）")
    return None


def run_job(
    inp: JobInput,
    site: SiteClient,
    qb,
    *,
    log: Callable[[str], None],
    sleep: Callable[[float], None],
) -> JobResult:
    result = JobResult()
    posts, challenge = _collect_posts(inp, site, result, log, sleep)

    if result.counts["pages_ok"] == 0:
        result.fatal_reason = COOKIE_PREFIX + (challenge or "列表页全部失败")
    elif challenge:
        result.fatal_reason = COOKIE_PREFIX + challenge
    elif result.counts["posts_found"] == 0:
        result.fatal_reason = COOKIE_PREFIX + "列表页没有帖子"
    if result.fatal_reason:
        log(result.fatal_reason)
        return result

    candidates: list[ListPost] = []
    for post in posts:
        hit = find_hit(post.title, inp.terms)
        if hit:
            result.add("title_blocked", post, keyword=hit)
        elif post.tid in inp.submitted_tids:
            result.counts["skipped_seen"] += 1
        else:
            candidates.append(post)
    log(
        f"有效帖子 {len(candidates)}，标题被拦 {result.counts['title_blocked']}，"
        f"已提交过 {result.counts['skipped_seen']}"
    )

    qb_error: str | None = None
    if not inp.dry_run and candidates:
        if qb is None:
            qb_error = "未配置 qB 地址或账号"
        else:
            try:
                qb.login()
            except QbError as exc:
                qb_error = str(exc)
    if qb_error:
        # qB 不可用时不再进帖子；全部记为提交失败，第二天会重新尝试
        result.fatal_reason = qb_error
        log(qb_error)
        for post in candidates:
            result.add("submit_failed", post, message=qb_error)
        return result

    for index, post in enumerate(candidates, 1):
        sleep(random.uniform(*THREAD_WAIT))
        log(f"[{index}/{len(candidates)}] {post.tid} {post.title[:30]}")
        try:
            response = site.get(post.url, timeout=15)
            if response.status != 200 or is_challenge(response.status, response.text):
                result.add("parse_failed", post, message=f"帖子页打开失败（HTTP {response.status}）")
                continue
            links = parse_thread(response.text)
        except Exception as exc:  # noqa: BLE001
            result.add("parse_failed", post, message=f"帖子页解析出错（{type(exc).__name__}）")
            continue

        torrent = _download_torrent(site, links.attachment_urls, log)
        if torrent is not None:
            data, names = torrent
            hit = next((word for word in (find_hit(name, inp.terms) for name in names) if word), None)
            if hit:
                result.add("torrent_blocked", post, keyword=hit)
                continue
        elif not links.magnets:
            result.add("parse_failed", post, message="未找到种子或磁力")
            continue

        via = "种子" if torrent is not None else "磁力"
        if inp.dry_run:
            result.add("submitted", post, message="演练，未实际提交")
            continue
        try:
            if torrent is not None:
                qb.add_torrent(torrent[0], f"{post.tid}.torrent", inp.qb_category)
            else:
                qb.add_magnets(links.magnets, inp.qb_category)
        except QbError as exc:
            result.add("submit_failed", post, message=str(exc))
            continue
        result.add("submitted", post, message=via)
        log(f"  已提交（{via}）")

    log(
        "完成：提交 {submitted}，标题拦 {title_blocked}，种子拦 {torrent_blocked}，"
        "跳过 {skipped_seen}，提交失败 {submit_failed}，解析失败 {parse_failed}".format(**result.counts)
    )
    return result
