from __future__ import annotations

from app.services.script_jobs.sehuatang.job import JobInput, run_job
from app.services.script_jobs.sehuatang.matching import normalize
from app.services.script_jobs.sehuatang.site import SiteResponse

from tests.script_jobs.sehuatang.fakes import FORUM, FakeQb, FakeSite, ok
from tests.script_jobs.sehuatang.helpers import list_page, multi_file_torrent, single_file_torrent, thread_page


MAGNET = "magnet:?xt=urn:btih:" + "C" * 40
TERMS = [("AI增强", normalize("AI增强")), ("示例坏词", normalize("示例坏词"))]


def _url(tid: str) -> str:
    return f"https://sehuatang.org/thread-{tid}-1-1.html"


def _att(aid: int) -> str:
    return f"https://sehuatang.org/forum.php?mod=attachment&aid={aid}"


def _thread_with_torrent(aid: int, magnets=(MAGNET,)) -> SiteResponse:
    return ok(thread_page(magnets=list(magnets), attachments=[(f"forum.php?mod=attachment&aid={aid}", "x.torrent")]))


def _input(**overrides) -> JobInput:
    values = dict(
        dry_run=False,
        pages=1,
        forum_url=FORUM,
        qb_category="国产BT",
        terms=TERMS,
        submitted_tids=set(),
    )
    values.update(overrides)
    return JobInput(**values)


def _run(inp: JobInput, site: FakeSite, qb):
    logs: list[str] = []
    result = run_job(inp, site, qb, log=logs.append, sleep=lambda seconds: None)
    return result, logs


def _kinds(result) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in result.items:
        grouped.setdefault(item["kind"], []).append(item["tid"])
    return grouped


def test_flow_title_block_seen_skip_torrent_block_and_submit():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(
                list_page([("1", "【新作】AI增强版"), ("2", "已提交过的帖子"), ("3", "种子里有坏词"), ("4", "正常帖子")])
            ),
            _url("3"): _thread_with_torrent(30),
            _att(30): ok(content=multi_file_torrent("示例坏词合集", [["正片.mp4"]])),
            _url("4"): _thread_with_torrent(40),
            _att(40): ok(content=single_file_torrent("正常视频.mp4")),
        }
    )
    qb = FakeQb()
    result, _ = _run(_input(submitted_tids={"2"}), site, qb)

    assert result.fatal_reason is None
    assert result.counts["posts_found"] == 4
    assert result.counts["title_blocked"] == 1
    assert result.counts["skipped_seen"] == 1
    assert result.counts["torrent_blocked"] == 1
    assert result.counts["submitted"] == 1
    assert _kinds(result) == {"title_blocked": ["1"], "torrent_blocked": ["3"], "submitted": ["4"]}
    blocked = next(item for item in result.items if item["kind"] == "title_blocked")
    assert blocked["keyword"] == "AI增强"
    torrent_blocked = next(item for item in result.items if item["kind"] == "torrent_blocked")
    assert torrent_blocked["keyword"] == "示例坏词"
    assert len(qb.torrents) == 1
    assert qb.torrents[0][2] == "国产BT"
    assert qb.magnets == []
    # 标题被拦和已提交的帖子不进帖子页
    assert _url("1") not in site.visited
    assert _url("2") not in site.visited


def test_blacklisted_ad_file_inside_torrent_does_not_block_it():
    # 每个种子都夹带的广告文件名在黑名单里；只要种子名本身没命中就照常提交，广告交给 qB 排除 / DEL 清理
    terms = TERMS + [("台湾uu美少女直播", normalize("台湾uu美少女直播"))]
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("33", "正常帖子")])),
            _url("33"): _thread_with_torrent(330),
            _att(330): ok(content=multi_file_torrent("正常合集", [["正片.mp4"], ["台湾uu美少女直播 20年信誉保证服务全球.mp4"]])),
        }
    )
    qb = FakeQb()
    result, _ = _run(_input(terms=terms), site, qb)
    assert result.counts["torrent_blocked"] == 0
    assert result.counts["submitted"] == 1
    assert len(qb.torrents) == 1


def test_prefers_torrent_over_magnet_and_never_submits_both():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("5", "正常帖子")])),
            _url("5"): _thread_with_torrent(50),
            _att(50): ok(content=single_file_torrent("a.mp4")),
        }
    )
    qb = FakeQb()
    result, _ = _run(_input(), site, qb)
    assert len(qb.torrents) == 1
    assert qb.magnets == []
    assert result.items[0]["message"] == "种子"


def test_falls_back_to_magnet_when_torrent_invalid():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("6", "正常帖子")])),
            _url("6"): _thread_with_torrent(60),
            _att(60): ok(text="<html>不是种子</html>"),
        }
    )
    qb = FakeQb()
    result, _ = _run(_input(), site, qb)
    assert qb.torrents == []
    assert qb.magnets == [([MAGNET], "国产BT")]
    assert result.items[0]["kind"] == "submitted"
    assert result.items[0]["message"] == "磁力"


def test_no_torrent_and_no_magnet_is_parse_failed():
    site = FakeSite({FORUM.format(page=1): ok(list_page([("7", "正常帖子")])), _url("7"): ok(thread_page())})
    result, _ = _run(_input(), site, FakeQb())
    assert result.counts["parse_failed"] == 1
    assert result.items[0]["message"] == "未找到种子或磁力"


def test_thread_page_error_is_parse_failed_and_continues():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("8", "帖子甲"), ("9", "帖子乙")])),
            _url("8"): RuntimeError("连接被重置"),
            _url("9"): ok(thread_page(magnets=[MAGNET])),
        }
    )
    result, _ = _run(_input(), site, FakeQb())
    assert _kinds(result) == {"parse_failed": ["8"], "submitted": ["9"]}


def test_cookie_invalid_when_all_list_pages_fail():
    site = FakeSite({})
    result, _ = _run(_input(pages=2), site, FakeQb())
    assert result.fatal_reason.startswith("站点 cookie 可能失效")
    assert result.counts["pages_failed"] == 2
    assert all("forumdisplay" in url for url in site.visited)


def test_challenge_page_sets_fatal_reason():
    site = FakeSite(
        {FORUM.format(page=1): SiteResponse(status=200, text="<script>_cf_chl_opt={}</script>", content=b"")}
    )
    result, _ = _run(_input(), site, FakeQb())
    assert result.fatal_reason.startswith("站点 cookie 可能失效")
    assert "Cloudflare" in result.fatal_reason


def test_no_posts_found_sets_fatal_reason():
    site = FakeSite({FORUM.format(page=1): ok("<html>空列表</html>")})
    result, _ = _run(_input(), site, FakeQb())
    assert result.fatal_reason.startswith("站点 cookie 可能失效")


def test_qb_login_failure_marks_all_submit_failed():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("10", "帖子甲"), ("11", "AI增强 帖子")])),
            _url("10"): ok(thread_page(magnets=[MAGNET])),
        }
    )
    result, _ = _run(_input(), site, FakeQb(login_fail=True))
    assert result.fatal_reason == "qB 登录失败（HTTP 403）"
    assert result.counts["submitted"] == 0
    assert _kinds(result) == {"title_blocked": ["11"], "submit_failed": ["10"]}


def test_missing_qb_client_fails_real_run():
    site = FakeSite({FORUM.format(page=1): ok(list_page([("12", "帖子甲")]))})
    result, _ = _run(_input(), site, None)
    assert result.fatal_reason == "未配置 qB 地址或账号"
    assert result.counts["submitted"] == 0


def test_add_failure_is_submit_failed_without_fatal():
    site = FakeSite({FORUM.format(page=1): ok(list_page([("13", "帖子甲")])), _url("13"): ok(thread_page(magnets=[MAGNET]))})
    result, _ = _run(_input(), site, FakeQb(add_fail=True))
    assert result.fatal_reason is None
    assert result.counts["submit_failed"] == 1


def test_dry_run_never_calls_qb():
    site = FakeSite({FORUM.format(page=1): ok(list_page([("14", "帖子甲")])), _url("14"): ok(thread_page(magnets=[MAGNET]))})
    qb = FakeQb()
    result, _ = _run(_input(dry_run=True), site, qb)
    assert qb.logged_in is False
    assert qb.magnets == []
    assert result.counts["submitted"] == 1
    assert result.items[0]["message"] == "演练，未实际提交"


def test_record_callback_receives_each_item_as_it_happens():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("31", "AI增强 帖子"), ("32", "正常帖子")])),
            _url("32"): ok(thread_page(magnets=[MAGNET])),
        }
    )
    recorded: list[dict] = []
    result = run_job(_input(), site, FakeQb(), log=lambda m: None, sleep=lambda s: None, record=recorded.append)
    assert recorded == result.items
    assert [item["kind"] for item in recorded] == ["title_blocked", "submitted"]


def test_posts_deduplicated_across_pages():
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("15", "帖子甲")])),
            FORUM.format(page=2): ok(list_page([("15", "帖子甲"), ("16", "帖子乙")])),
            _url("15"): ok(thread_page(magnets=[MAGNET])),
            _url("16"): ok(thread_page(magnets=[MAGNET])),
        }
    )
    result, _ = _run(_input(pages=2), site, FakeQb())
    assert result.counts["pages_ok"] == 2
    assert result.counts["submitted"] == 2
