from __future__ import annotations

from pathlib import Path

from app.services.emby_media_actions.strm_mapping_service import (
    StrmMappingService,
    decode_115_open_path,
    normalize_stream_url,
)


def test_normalize_stream_url_decodes_host_case_and_trailing_spaces() -> None:
    assert normalize_stream_url(" HTTP://192.168.70.138:5244/d/115_OPEN/a%20b.mkv \n") == (
        "http://192.168.70.138:5244/d/115_OPEN/a%20b.mkv"
    )


def test_decode_115_open_path() -> None:
    decoded = decode_115_open_path(
        "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a%20b.mkv"
    )

    assert decoded.mount_name == "115_OPEN"
    assert decoded.remote_path == "/电影/a b.mkv"


def test_scan_for_url_returns_source_and_organized_matches(tmp_path: Path) -> None:
    source_root = tmp_path / "alist_mv1"
    organized_root = tmp_path / "mp302_mv"
    source_root.mkdir()
    organized_root.mkdir()
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv"
    (source_root / "a.strm").write_text(url + "\n", encoding="utf-8")
    (organized_root / "a.strm").write_text(url, encoding="utf-8")
    (organized_root / "other.strm").write_text("http://example.invalid/other.mkv", encoding="utf-8")

    service = StrmMappingService(
        strm_roots=[str(tmp_path)],
        source_roots=[str(source_root)],
        organized_roots=[str(organized_root)],
    )

    matches = service.scan_for_url(url)

    assert [match.path_role for match in matches] == ["source_strm", "organized_strm"]
    assert {match.root_name for match in matches} == {"alist_mv1", "mp302_mv"}
