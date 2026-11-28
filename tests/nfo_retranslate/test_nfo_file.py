from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import xml.etree.ElementTree as ET

import pytest

from app.services.nfo_retranslate.nfo_file import (
    NfoError,
    atomic_write,
    build_plot,
    build_title,
    plot_body,
    read_nfo,
    replace_fields,
    sha256_text,
    split_title,
    strip_num,
    translator_marker,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample.nfo"
SELF_CLOSING = FIXTURES / "sample_selfclosing.nfo"

# 只认 <title>、<outline>、<plot> 三个标签开头的行（不含 originaltitle、originalplot 等）
_FIELD_LINE = re.compile(r"^\s*<(?:title|outline|plot)[\s/>]")


def _raw(path: Path) -> str:
    """按字节读出再解码，避免换行被改写。"""
    return path.read_bytes().decode("utf-8")


def _without_fields(text: str) -> str:
    """去掉三个标签所在的行，其余行原样拼回。"""
    return "".join(line for line in text.splitlines(keepends=True) if not _FIELD_LINE.match(line))


def _field_line(text: str, tag: str) -> str:
    """取某个标签所在的那一行。"""
    pattern = re.compile(rf"^\s*<{tag}[\s/>]")
    return next(line for line in text.splitlines(keepends=True) if pattern.match(line))


def test_read_nfo_fields():
    doc = read_nfo(str(SAMPLE))

    assert doc.path == str(SAMPLE)
    assert doc.raw == _raw(SAMPLE)
    assert doc.sha256 == sha256_text(doc.raw)
    assert doc.num == "MIAA-759"
    assert doc.title == "MIAA-759 订婚后的我被两位上司在耳边低语诱惑"
    assert doc.original_title == "MIAA-759 婚約したばかりの僕に耳元で囁いてくるW上司 森沢かな"
    assert doc.actors == ("西田那津", "森泽佳奈")
    assert doc.studio == "MOODYZ"
    assert doc.series == ""
    assert translator_marker(doc.plot) == "OpenAI"


def test_read_nfo_unescapes_original_plot():
    doc = read_nfo(str(SAMPLE))

    assert "囁く&誘惑する！<br>厳しい先輩" in doc.original_plot
    assert "&amp;" not in doc.original_plot
    assert "&lt;br&gt;" not in doc.original_plot


def test_read_nfo_rejects_missing_or_broken_file(tmp_path):
    with pytest.raises(NfoError):
        read_nfo(str(tmp_path / "missing.nfo"))

    broken = tmp_path / "broken.nfo"
    broken.write_text("<movie><title>没闭合</movie>", encoding="utf-8")
    with pytest.raises(NfoError):
        read_nfo(str(broken))


def test_split_title_variants():
    assert split_title("MIAA-759 刚订婚 cd2", "MIAA-759") == ("刚订婚", " cd2")
    assert split_title(
        "2017-11-18 MIDE-488 新人！ 新人出道", "2017-11-18 MIDE-488 新人！"
    ) == ("新人出道", "")
    assert split_title("别的开头", "MIAA-759") is None


def test_strip_num_and_plot_body():
    assert strip_num("MIAA-759 婚約 森沢かな", "MIAA-759") == "婚約 森沢かな"
    assert strip_num("  没有番号的标题 ", "MIAA-759") == "没有番号的标题"
    assert plot_body("第一段<br>第二段<br>  <br>由 Google 提供翻译") == "第一段\n第二段"


def test_build_title_and_plot():
    assert build_title("ABC-001", "新标题", " cd1") == "ABC-001 新标题 cd1"
    assert build_plot("甲\n乙", "qwen38") == "甲<br>乙<br>  <br>由 qwen38 提供翻译"
    # 模型输出 \r\n 或 \r 时不留下 \r
    assert build_plot("甲\r\n乙\r丙", "qwen38") == "甲<br>乙<br>丙<br>  <br>由 qwen38 提供翻译"


def test_replace_fields_only_touches_three_tags():
    raw = _raw(SAMPLE)
    new_plot = build_plot("新简介第一段\n第二段", "qwen38")

    out = replace_fields(raw, title="新标题", plot=new_plot)

    assert _without_fields(out) == _without_fields(raw)
    assert _field_line(out, "title") == "  <title><![CDATA[新标题]]></title>\n"
    assert _field_line(out, "outline") == f"  <outline><![CDATA[{new_plot}]]></outline>\n"
    assert _field_line(out, "plot") == f"  <plot><![CDATA[{new_plot}]]></plot>\n"
    root = ET.fromstring(out)
    assert root.findtext("title") == "新标题"
    assert root.findtext("outline") == root.findtext("plot") == new_plot


def test_replace_fields_none_keeps_field():
    raw = _raw(SAMPLE)

    only_plot = replace_fields(raw, title=None, plot=build_plot("新简介", "qwen38"))
    assert _field_line(only_plot, "title") == _field_line(raw, "title")

    only_title = replace_fields(raw, title="新标题", plot=None)
    assert _field_line(only_title, "outline") == _field_line(raw, "outline")
    assert _field_line(only_title, "plot") == _field_line(raw, "plot")


def test_replace_self_closing_tags():
    raw = _raw(SELF_CLOSING)
    new_plot = build_plot("新简介", "qwen38")

    out = replace_fields(raw, title=None, plot=new_plot)

    assert _without_fields(out) == _without_fields(raw)
    assert _field_line(out, "outline") == f"  <outline><![CDATA[{new_plot}]]></outline>\n"
    assert _field_line(out, "plot") == f"  <plot><![CDATA[{new_plot}]]></plot>\n"
    root = ET.fromstring(out)
    assert root.findtext("outline") == root.findtext("plot") == new_plot


def test_replace_escapes_cdata_terminator():
    raw = _raw(SAMPLE)

    out = replace_fields(raw, title="标题]]>尾", plot="a]]>b")

    root = ET.fromstring(out)
    assert root.findtext("title") == "标题]]>尾"
    assert "a]]>b" in root.findtext("plot")
    assert "a]]>b" in root.findtext("outline")


def test_atomic_write_keeps_mode_and_rejects_bad_xml(tmp_path):
    target = tmp_path / "MIAA-759.nfo"
    shutil.copyfile(SAMPLE, target)
    os.chmod(target, 0o666)
    before = os.stat(target)
    new = replace_fields(_raw(SAMPLE), title="新标题", plot=None)

    atomic_write(str(target), new)

    after = os.stat(target)
    assert target.read_bytes() == new.encode("utf-8")
    assert stat.S_IMODE(after.st_mode) == 0o666
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)

    with pytest.raises(NfoError):
        atomic_write(str(target), "<movie><title>没闭合</movie>")
    assert target.read_bytes() == new.encode("utf-8")
    assert os.listdir(tmp_path) == ["MIAA-759.nfo"]


def test_atomic_write_cleans_temp_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "MIAA-759.nfo"
    shutil.copyfile(SAMPLE, target)
    original = target.read_bytes()

    def fail_replace(src, dst):
        raise OSError("模拟替换失败")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(NfoError):
        atomic_write(str(target), replace_fields(_raw(SAMPLE), title="新标题", plot=None))
    assert target.read_bytes() == original
    assert os.listdir(tmp_path) == ["MIAA-759.nfo"]


def test_atomic_write_refuses_hardlink(tmp_path):
    target = tmp_path / "MIAA-759.nfo"
    shutil.copyfile(SAMPLE, target)
    os.link(target, tmp_path / "link.nfo")
    original = target.read_bytes()

    with pytest.raises(NfoError, match="NFO 有硬链接"):
        atomic_write(str(target), replace_fields(_raw(SAMPLE), title="新标题", plot=None))
    assert target.read_bytes() == original
