"""翻译报告：把翻译记录生成自包含的单文件 HTML（内联 CSS，文字全部转义）。

报告只用传进来的记录、模型名和运行编号，不读任何配置，接口地址和密钥不会进报告。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from html import escape

from app.services.nfo_retranslate.runs import TranslationRecord

_FIELD_NAMES = {"title": "标题", "plot": "简介"}
_FIELD_ORDER = {"title": 0, "plot": 1}
_COLUMNS = ("番号", "演员", "字段", "日文原文", "旧译文", "新译文", "检查结果")
_CSS = """
body{margin:24px;font:14px/1.5 -apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;color:#1f2328;background:#fff}
h1{font-size:20px;margin:0 0 4px}
.meta{color:#59636e;margin:0 0 16px}
table{border-collapse:collapse;margin:0 0 16px}
th,td{border:1px solid #d1d9e0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa;font-weight:600}
.summary td{font-size:18px;font-weight:600;text-align:right}
.records thead th{position:sticky;top:0}
.records td{white-space:pre-wrap;word-break:break-word}
.records td:nth-child(1){white-space:nowrap}
.records td:nth-child(n+4):nth-child(-n+6){min-width:16em;max-width:32em}
tr.failed td{background:#ffebe9;color:#82071e}
"""


def _cells(values: Sequence[str]) -> str:
    return "".join(f"<td>{escape(value)}</td>" for value in values)


def write_report(path: str, records: Sequence[TranslationRecord], *, model: str, run_id: str) -> None:
    """生成 report.html：顶部汇总和失败原因计数，下面每部片每个字段一行，失败行标红并写原因。

    同一部片同一字段有多条记录（续跑补翻）时以最后一条为准，和 apply 一致。
    """
    latest = {(rec.group_key, rec.field): rec for rec in records}
    rows = sorted(latest.values(), key=lambda rec: (rec.group_key, _FIELD_ORDER.get(rec.field, len(_FIELD_ORDER))))
    failed = [rec for rec in rows if rec.error is not None]
    films = len({rec.group_key for rec in rows})

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>NFO 重新翻译报告 {escape(run_id)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>NFO 重新翻译报告</h1>",
        f'<p class="meta">运行编号 {escape(run_id)} · 模型 {escape(model)}</p>',
        '<table class="summary">',
        "<tr><th>部数</th><th>字段</th><th>成功</th><th>失败</th></tr>",
        f"<tr><td>{films}</td><td>{len(rows)}</td><td>{len(rows) - len(failed)}</td><td>{len(failed)}</td></tr>",
        "</table>",
    ]
    if failed:
        parts.append('<table class="reasons">')
        parts.append("<tr><th>失败原因</th><th>数量</th></tr>")
        for reason, count in Counter(rec.error for rec in failed).most_common():
            parts.append(f"<tr>{_cells([reason or ''])}<td>{count}</td></tr>")
        parts.append("</table>")

    parts.append('<table class="records">')
    parts.append("<thead><tr>" + "".join(f"<th>{name}</th>" for name in _COLUMNS) + "</tr></thead>")
    parts.append("<tbody>")
    for rec in rows:
        values = [
            rec.num,
            "、".join(rec.actors),
            _FIELD_NAMES.get(rec.field, rec.field),
            rec.source_text,
            rec.old_text,
            rec.new_text or "",
            "通过" if rec.error is None else rec.error,
        ]
        row_tag = "<tr>" if rec.error is None else '<tr class="failed">'
        parts.append(f"{row_tag}{_cells(values)}</tr>")
    parts.append("</tbody>")
    parts.append("</table>")
    parts.append("</body>")
    parts.append("</html>")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts) + "\n")
