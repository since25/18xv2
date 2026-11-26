from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path

import httpx
import pytest

from app.services.actresses.gfriends import (
    GfriendsError,
    GfriendsIndex,
    download_image,
    gfriends_image_url,
    load_filetree,
    load_name_map,
    normalize_gfriends_name,
)


def _tree(content: dict) -> dict:
    return {"Content": content, "Information": {}}


def test_normalize_strips_spaces_dots_brackets_and_lowercases():
    assert normalize_gfriends_name(" 甲・乙（丙）AB ") == "甲乙丙ab"


def test_find_direct_and_variants():
    index = GfriendsIndex.from_filetree(
        _tree({"a-源": {"甲.jpg": "AI-Fix-甲.jpg?t=1", "乙-834.jpg": "乙-834.jpg?t=2", "丙（丁）.jpg": "丙（丁）.jpg?t=3"}})
    )

    assert index.find(["甲"]) == "a-源/AI-Fix-甲.jpg"
    assert index.find(["乙"]) == "a-源/乙-834.jpg"
    assert index.find(["丁"]) == "a-源/丙（丁）.jpg"
    assert index.find(["丙"]) == "a-源/丙（丁）.jpg"
    assert index.find(["甲 "]) == "a-源/AI-Fix-甲.jpg"
    assert index.used_name_map is False


def test_find_prefers_first_folder_sorted():
    index = GfriendsIndex.from_filetree(_tree({"b-源": {"甲.jpg": "甲.jpg?t=1"}, "a-源": {"甲.jpg": "甲.jpg?t=2"}}))

    assert index.find(["甲"]) == "a-源/甲.jpg"


def test_find_via_name_map():
    index = GfriendsIndex.from_filetree(_tree({"a-源": {"日甲.jpg": "日甲.jpg?t=1"}}), name_map={"中甲": "日甲"})

    assert index.find(["中甲"]) == "a-源/日甲.jpg"
    assert index.used_name_map is True


def test_find_tries_names_in_order_and_returns_none():
    index = GfriendsIndex.from_filetree(_tree({"a-源": {"乙.jpg": "乙.jpg?t=1", "丙.jpg": "丙.jpg?t=1"}}))

    assert index.find(["甲", "乙", "丙"]) == "a-源/乙.jpg"
    assert index.find(["甲", "丁"]) is None
    assert index.find([]) is None


def test_load_name_map_parses_keyword_and_zh(tmp_path):
    path = tmp_path / "mapping_actor.xml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<actor>\n'
        '  <a zh_cn="中甲" zh_tw="中甲台" jp="日甲" keyword=",中甲,别 甲,"/>\n'
        "</actor>\n",
        encoding="utf-8",
    )

    name_map = load_name_map(str(path))

    assert name_map == {"中甲": "日甲", "中甲台": "日甲", "别甲": "日甲"}


def test_load_name_map_missing_or_bad_returns_none(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml <<<", encoding="utf-8")

    assert load_name_map(None) is None
    assert load_name_map("") is None
    assert load_name_map(str(tmp_path / "missing.xml")) is None
    assert load_name_map(str(bad)) is None


class _Fetch:
    def __init__(self, payload: bytes | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload or b""


NOW = datetime(2026, 11, 26, 12, 0, 0)


def _write_cache(path: Path, content: dict, age: timedelta) -> None:
    path.write_text(json.dumps(content), encoding="utf-8")
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))


def test_load_filetree_uses_fresh_cache(tmp_path):
    cache = tmp_path / "Filetree.json"
    _write_cache(cache, {"Content": {"缓存": {}}}, timedelta(days=6))
    fetch = _Fetch(b'{"Content": {"new": {}}}')

    assert load_filetree(cache, fetch=fetch, now=NOW) == {"Content": {"缓存": {}}}
    assert fetch.calls == 0


def test_load_filetree_refetches_stale_cache(tmp_path):
    cache = tmp_path / "Filetree.json"
    _write_cache(cache, {"Content": {"缓存": {}}}, timedelta(days=8))
    fetch = _Fetch(b'{"Content": {"new": {}}}')

    assert load_filetree(cache, fetch=fetch, now=NOW) == {"Content": {"new": {}}}
    assert fetch.calls == 1
    assert json.loads(cache.read_text(encoding="utf-8")) == {"Content": {"new": {}}}


def test_load_filetree_falls_back_to_stale_on_fetch_error(tmp_path):
    cache = tmp_path / "Filetree.json"
    _write_cache(cache, {"Content": {"缓存": {}}}, timedelta(days=30))

    assert load_filetree(cache, fetch=_Fetch(error=OSError("断网")), now=NOW) == {"Content": {"缓存": {}}}


def test_load_filetree_raises_without_cache(tmp_path):
    cache = tmp_path / "sub" / "Filetree.json"

    with pytest.raises(GfriendsError):
        load_filetree(cache, fetch=_Fetch(error=OSError("断网")), now=NOW)


def test_load_filetree_creates_cache_dir(tmp_path):
    cache = tmp_path / "sub" / "Filetree.json"

    assert load_filetree(cache, fetch=_Fetch(b'{"Content": {}}'), now=NOW) == {"Content": {}}
    assert cache.is_file()


def test_gfriends_image_url():
    assert gfriends_image_url("a-源/甲.jpg") == (
        "https://raw.githubusercontent.com/gfriends/gfriends/master/Content/a-源/甲.jpg"
    )


def _transport(response: httpx.Response) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: response)


def test_download_image_returns_content_and_type():
    content = b"\xff\xd8jpeg"
    result = download_image(
        "http://gfriends.test/甲.jpg",
        transport=_transport(httpx.Response(200, content=content, headers={"Content-Type": "image/jpeg"})),
    )

    assert result == (content, "image/jpeg")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"}),
        httpx.Response(404, content=b"", headers={"Content-Type": "image/jpeg"}),
        httpx.Response(200, content=b"x" * (6 * 1024 * 1024), headers={"Content-Type": "image/jpeg"}),
    ],
    ids=["not-image", "http-404", "oversize"],
)
def test_download_image_rejects_bad_responses(response):
    with pytest.raises(GfriendsError):
        download_image("http://gfriends.test/甲.jpg", transport=_transport(response))


def test_download_image_wraps_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("虚构：连不上", request=request)

    with pytest.raises(GfriendsError):
        download_image("http://gfriends.test/甲.jpg", transport=httpx.MockTransport(handler))
