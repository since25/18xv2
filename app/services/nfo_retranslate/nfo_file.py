"""NFO 文件读写：读字段、拼新标题和新简介、只改三个标签写回、原子替换。

XML 库只用来读值和校验；写回时按文本定位 <title>、<outline>、<plot> 替换，
其余内容（CDATA、缩进、转义、其他标签）逐字节不变。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import hashlib
import os
import re
import stat
import tempfile
import xml.etree.ElementTree as ET

# 原标题末尾的分段后缀，例如 " cd2"
_PART_SUFFIX = re.compile(r" cd\d+$")
# 简介结尾的翻译标记「由 X 提供翻译」，只认最末尾的一段
_MARKER = re.compile(r"由\s*([^<>\n由]*?)\s*提供翻译\s*$")
# <br> 的各种写法：<br>、<br/>、<br />、<BR>
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
# 三个可写标签：带内容的（非贪婪，可跨行）或自闭合的，各取第一个
_FIELD_PATTERNS = {
    tag: re.compile(rf"<{tag}>.*?</{tag}>|<{tag}\s*/>", re.DOTALL) for tag in ("title", "outline", "plot")
}


class NfoError(Exception):
    """NFO 读不了、解析失败，或写入被拒绝。"""


@dataclass(frozen=True)
class NfoDoc:
    """一份 NFO 的原文和用到的字段；字段值已还原 CDATA 和转义。"""

    path: str
    raw: str
    sha256: str
    num: str
    title: str
    original_title: str
    plot: str
    original_plot: str
    actors: tuple[str, ...]
    studio: str
    series: str


def _parse(data: bytes) -> ET.Element:
    """解析 XML，失败时抛 NfoError。"""
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise NfoError(f"NFO 不是合法 XML：{exc}") from exc


def read_nfo(path: str) -> NfoDoc:
    """读 NFO：raw 和 sha256 取文件原文，字段值用 XML 库读出。"""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        raw = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NfoError(f"读取 NFO 失败：{exc}") from exc
    root = _parse(data)
    names = (actor.findtext("name", default="").strip() for actor in root.findall("actor"))
    return NfoDoc(
        path=path,
        raw=raw,
        sha256=sha256_text(raw),
        num=root.findtext("num", default=""),
        title=root.findtext("title", default=""),
        original_title=root.findtext("originaltitle", default=""),
        plot=root.findtext("plot", default=""),
        original_plot=root.findtext("originalplot", default=""),
        actors=tuple(name for name in names if name),
        studio=root.findtext("studio", default=""),
        series=root.findtext("series", default=""),
    )


def split_title(title: str, num: str) -> tuple[str, str] | None:
    """把「番号 + 空格 + 正文 + 分段后缀」拆成 (正文, 分段后缀)；不以「番号 + 空格」开头时返回 None。"""
    prefix = num + " "
    if not num or not title.startswith(prefix):
        return None
    rest = title[len(prefix):]
    match = _PART_SUFFIX.search(rest)
    suffix = match.group(0) if match else ""
    return rest[: len(rest) - len(suffix)].strip(), suffix


def strip_num(text: str, num: str) -> str:
    """去掉开头的番号和空白；不以番号开头就只去首尾空白。"""
    if num and text.startswith(num):
        text = text[len(num):]
    return text.strip()


def translator_marker(plot: str) -> str | None:
    """取简介结尾「由 X 提供翻译」里的 X；没有标记时返回 None。"""
    match = _MARKER.search(plot)
    return (match.group(1) or None) if match else None


def plot_body(plot: str) -> str:
    """去掉翻译标记，<br> 换成换行，再去首尾空白。"""
    return _BR.sub("\n", _MARKER.sub("", plot)).strip()


def build_title(num: str, translated: str, part_suffix: str) -> str:
    """新标题 = 番号 + 空格 + 译文 + 原分段后缀。"""
    return f"{num} {translated}{part_suffix}"


def build_plot(translated: str, model: str) -> str:
    """新简介 = 译文（换行改成 <br>）+ 结尾翻译标记。"""
    return translated.replace("\n", "<br>") + f"<br>  <br>由 {model} 提供翻译"


def _cdata(text: str) -> str:
    """包成 CDATA；内容里的 ]]> 拆成两段，避免提前结束。"""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def replace_fields(raw: str, *, title: str | None, plot: str | None) -> str:
    """只替换 <title>、<outline>、<plot> 的内容，其余文本不动；None 表示该字段不动，plot 同时写 outline。"""
    values: dict[str, str] = {}
    if title is not None:
        values["title"] = title
    if plot is not None:
        values["outline"] = plot
        values["plot"] = plot
    # 先在原文上定位全部标签，再从后往前替换，新内容不会影响后续定位
    spans: list[tuple[int, int, str]] = []
    for tag, value in values.items():
        match = _FIELD_PATTERNS[tag].search(raw)
        if match is None:
            raise NfoError(f"NFO 里没有 <{tag}> 标签")
        spans.append((match.start(), match.end(), f"<{tag}>{_cdata(value)}</{tag}>"))
    for start, end, element in sorted(spans, reverse=True):
        raw = raw[:start] + element + raw[end:]
    return raw


def sha256_text(text: str) -> str:
    """文本按 UTF-8 编码后的 sha256 十六进制串。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write(path: str, content: str) -> None:
    """同目录写临时文件、校验 XML、还原原文件的权限和属主后原子替换；任何失败都不动原文件。"""
    try:
        st = os.stat(path)
    except OSError as exc:
        raise NfoError(f"读取 NFO 属性失败：{exc}") from exc
    if st.st_nlink > 1:
        raise NfoError("NFO 有硬链接")
    data = content.encode("utf-8")
    _parse(data)
    abs_path = os.path.abspath(path)
    try:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(abs_path), prefix=f".{os.path.basename(abs_path)}.", suffix=".tmp"
        )
    except OSError as exc:
        raise NfoError(f"创建临时文件失败：{exc}") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, abs_path)
    except BaseException as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        if isinstance(exc, OSError):
            raise NfoError(f"写入 NFO 失败：{exc}") from exc
        raise
