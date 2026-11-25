from __future__ import annotations

import pytest

from app.services.script_jobs.sehuatang.torrent import TorrentParseError, list_names

from tests.script_jobs.sehuatang.helpers import bencode, multi_file_torrent, single_file_torrent


def test_single_file_returns_name():
    assert list_names(single_file_torrent("示例视频.mp4")) == ["示例视频.mp4"]


def test_multi_file_returns_name_and_joined_paths():
    data = multi_file_torrent("示例合集", [["第一集", "a.mp4"], ["b.mp4"]])
    assert list_names(data) == ["示例合集", "第一集/a.mp4", "b.mp4"]


def test_multi_file_prefers_utf8_path():
    data = bencode(
        {
            "info": {
                "name": "x",
                "name.utf-8": "示例合集",
                "files": [{"length": 1, "path": ["bad"], "path.utf-8": ["好", "c.mp4"]}],
            }
        }
    )
    assert list_names(data) == ["示例合集", "好/c.mp4"]


@pytest.mark.parametrize("data", [b"<html>", b"", b"d4:infoi1ee", b"l1:ae", b"d4:info"])
def test_rejects_non_torrent(data):
    with pytest.raises(TorrentParseError):
        list_names(data)
