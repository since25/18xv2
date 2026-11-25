from __future__ import annotations

from app.services.script_jobs.sehuatang.pages import (
    ListPost,
    extract_safeid,
    is_challenge,
    parse_list,
    parse_thread,
    tid_from_url,
)

from tests.script_jobs.sehuatang.helpers import list_page, thread_page


MAGNET_A = "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MAGNET_B = "magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


def test_parse_list_extracts_tid_title_url_and_dedupes():
    html = list_page([("101", "示例标题一"), ("102", "示例标题二"), ("101", "示例标题一")])
    assert parse_list(html) == [
        ListPost(tid="101", title="示例标题一", url="https://sehuatang.org/thread-101-1-1.html"),
        ListPost(tid="102", title="示例标题二", url="https://sehuatang.org/thread-102-1-1.html"),
    ]


def test_parse_list_supports_tid_query_links():
    html = '<a class="s xst" href="forum.php?mod=viewthread&amp;tid=205&amp;extra=1">示例标题</a>'
    assert parse_list(html) == [
        ListPost(tid="205", title="示例标题", url="https://sehuatang.org/forum.php?mod=viewthread&tid=205&extra=1")
    ]


def test_parse_list_skips_links_without_tid():
    assert parse_list('<a class="s xst" href="home.php">无编号</a>') == []


def test_tid_from_url():
    assert tid_from_url("https://sehuatang.org/thread-3010-1-1.html") == "3010"
    assert tid_from_url("https://sehuatang.org/forum.php?mod=viewthread&tid=88") == "88"
    assert tid_from_url("https://sehuatang.org/home.php") is None


def test_parse_thread_magnets_dedup_and_attachment_filter():
    html = thread_page(
        magnets=[MAGNET_A, MAGNET_B, MAGNET_A],
        attachments=[
            ("forum.php?mod=attachment&aid=1", "示例.torrent"),
            ("forum.php?mod=attachment&aid=2", "封面.jpg"),
            ("forum.php?mod=attachment&aid=3", "下载附件"),
            ("forum.php?mod=other&aid=4", "x.torrent"),
        ],
    )
    links = parse_thread(html)
    assert links.magnets == [MAGNET_A, MAGNET_B]
    assert links.attachment_urls == [
        "https://sehuatang.org/forum.php?mod=attachment&aid=1",
        "https://sehuatang.org/forum.php?mod=attachment&aid=3",
    ]


def test_extract_safeid_only_on_safe_page():
    safe = "<script src='static/safe/js/a.js'></script><script>var safeid='abc123';</script>"
    assert extract_safeid(safe) == "abc123"
    assert extract_safeid("<script>var safeid='abc123';</script>") is None
    assert extract_safeid("<script src='static/safe/js/a.js'></script>") is None


def test_is_challenge():
    assert is_challenge(200, "<script>window._cf_chl_opt={}</script>") is True
    assert is_challenge(403, "") is True
    assert is_challenge(503, "") is True
    assert is_challenge(200, "<html>正常页面</html>") is False
