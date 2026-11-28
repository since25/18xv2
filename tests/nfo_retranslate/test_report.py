from __future__ import annotations

from html.parser import HTMLParser

from app.services.nfo_retranslate.report import write_report
from app.services.nfo_retranslate.runs import TranslationRecord

_SECRET_KEY = "sk-report-secret-0123456789"
_SECRET_BASE = "https://llm.secret.test/v1"


class _Tables(HTMLParser):
    """按 table 的 class 收集每一行：(tr 的 class, [单元格文字])；单元格文字已还原转义。"""

    def __init__(self) -> None:
        super().__init__()
        self.tables: dict[str | None, list[tuple[str | None, list[str]]]] = {}
        self._table: list[tuple[str | None, list[str]]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._table = self.tables.setdefault(attrs.get("class"), [])
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append((attrs.get("class"), self._row))
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _rec(group_key: str, num: str, field: str, *, new_text: str | None, error: str | None) -> TranslationRecord:
    return TranslationRecord(
        group_key=group_key,
        field=field,
        num=num,
        actors=["三上悠亜", "河北彩花"],
        source_text=f"{num} の原文",
        old_text=f"{num} 旧译",
        new_text=new_text,
        error=error,
        targets={f"/media/{num}/{num}.nfo": "a" * 64},
    )


def test_report_contains_rows_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("NFO_TRANSLATE_API_KEY", _SECRET_KEY)
    monkeypatch.setenv("NFO_TRANSLATE_API_BASE", _SECRET_BASE)

    title_ok = TranslationRecord(
        group_key="甲|ABC-001",
        field="title",
        num="ABC-001",
        actors=["三上悠亜", "河北彩花"],
        source_text="人妻の<秘密>&誘惑",
        old_text="人妻的秘密（旧）",
        new_text="人妻的<秘密>与诱惑",
        error=None,
        targets={"/media/甲/ABC-001/ABC-001.nfo": "a" * 64},
    )
    plot_failed = _rec("甲|ABC-001", "ABC-001", "plot", new_text=None, error="假名占比超过 15%，疑似没翻")
    first_try = _rec("乙|XYZ-002", "XYZ-002", "title", new_text=None, error="翻译接口请求失败（HTTP 500，已尝试 4 次）")
    other_kana = _rec("丙|DEF-003", "DEF-003", "plot", new_text=None, error="假名占比超过 15%，疑似没翻")
    # 续跑补翻：同一部片同一字段以最后一条为准
    retry_ok = _rec("乙|XYZ-002", "XYZ-002", "title", new_text="补翻成功的标题", error=None)
    http_failed = _rec("丁|GHI-004", "GHI-004", "title", new_text=None, error="翻译接口请求失败（HTTP 500，已尝试 4 次）")
    records = [title_ok, plot_failed, first_try, other_kana, retry_ok, http_failed]

    path = tmp_path / "report.html"
    write_report(str(path), records, model="qwen38", run_id="20261127-220000")

    content = path.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in content
    assert content.rstrip().endswith("</html>")
    assert "20261127-220000" in content
    assert "qwen38" in content
    # 文字都转义过：原文里的 <秘密> 不会变成标签
    assert "<秘密>" not in content
    # 不含配置里的接口地址和密钥
    assert _SECRET_KEY not in content
    assert _SECRET_BASE not in content
    assert "llm.secret.test" not in content

    tables = _Tables()
    tables.feed(content)

    # 顶部汇总：部数按不同的 group_key 计，字段按「部 + 字段」去重后计
    header, values = tables.tables["summary"]
    assert dict(zip(header[1], values[1], strict=True)) == {"部数": "4", "字段": "5", "成功": "2", "失败": "3"}

    reasons = {cells[0]: cells[1] for _cls, cells in tables.tables["reasons"][1:]}
    assert reasons == {"假名占比超过 15%，疑似没翻": "2", "翻译接口请求失败（HTTP 500，已尝试 4 次）": "1"}

    rows = tables.tables["records"]
    assert rows[0][1] == ["番号", "演员", "字段", "日文原文", "旧译文", "新译文", "检查结果"]
    body = {(cells[0], cells[2]): (cls, cells) for cls, cells in rows[1:]}
    assert len(body) == len(rows) - 1 == 5

    cls, cells = body[("ABC-001", "标题")]
    assert cls != "failed"
    assert cells == ["ABC-001", "三上悠亜、河北彩花", "标题", "人妻の<秘密>&誘惑", "人妻的秘密（旧）", "人妻的<秘密>与诱惑", "通过"]

    cls, cells = body[("ABC-001", "简介")]
    assert cls == "failed"
    assert cells[3:] == ["ABC-001 の原文", "ABC-001 旧译", "", "假名占比超过 15%，疑似没翻"]

    cls, cells = body[("XYZ-002", "标题")]
    assert cls != "failed"
    assert cells[5:] == ["补翻成功的标题", "通过"]

    assert body[("DEF-003", "简介")][0] == "failed"
    assert body[("GHI-004", "标题")][0] == "failed"
