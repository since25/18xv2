"""DEL_SOMETHING 和 MOVE_SSD_CACHE_TO_DISK2 的输出解析（只用标准库）。

由阶段 6 的 `scripts/unraid/report_script_run.py` 搬来，解析规则不变；18x 执行这两个脚本后直接用它整理结果。
另加演练名单解析：演练时脚本只打印“将删除 / 将移动”，正式解析器不计这些行。
"""

from __future__ import annotations

from dataclasses import dataclass
import re


SCRIPT_DEL = "DEL_SOMETHING"
SCRIPT_MOVE = "MOVE_SSD_CACHE_TO_DISK2"
COUNT_KEYS = (
    "deleted_dirs",
    "deleted_files",
    "empty_dirs",
    "moved_new",
    "moved_rescan",
    "ambiguous",
    "skipped",
    "errors",
    "warnings",
    "unparsed_lines",
    "moved",
    "duplicates_removed",
    "failed",
)
_DEL_KNOWN_TAGS = {
    "DELETED",
    "EMPTY",
    "MOVED",
    "SKIPPED",
    "ERROR",
    "错误",
    "WARN",
    "ALREADY-PLACED",
    "SUMMARY",
    "INFO",
    "SKIP",
    "处理",
    "完成",
    "BACKUP",
    "DRY-RUN",
    # 整理脚本：同名目录合并进已有目录；命中超过组合上限的多个白名单而跳过
    "MERGED",
    "AMBIGUOUS",
}
_TAG_RE = re.compile(r"^\[(?P<tag>[^\]]+)\]")
_HIT_LINE_RE = re.compile(r"^命中(?:标准词|词项)\s*[:：]\s*(?P<keyword>.+?)\s*$")


@dataclass(slots=True)
class ParseResult:
    counts: dict[str, int]
    items: list[dict[str, str | None]]
    summary_found: bool = True


def _counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


def _item(
    kind: str,
    *,
    path: str | None = None,
    target_path: str | None = None,
    keyword: str | None = None,
    message: str | None = None,
) -> dict[str, str | None]:
    return {
        "kind": kind,
        "path": path,
        "target_path": target_path,
        "keyword": keyword,
        "message": message,
    }


def _rest_after_marker(line: str, marker: str) -> str:
    rest = line[len(marker) :].strip()
    if rest.startswith((":", "：")):
        rest = rest[1:].strip()
    return rest


def _path_or_message(rest: str) -> tuple[str | None, str | None]:
    """日志没有统一的错误行格式时，路径放 path，其余文字放 message。"""
    if not rest:
        return None, None
    if rest.startswith(("/", "\\")):
        return rest, None
    return None, rest


def _strip_label(rest: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        prefix = f"{label}："
        if rest.startswith(prefix):
            return rest[len(prefix) :].strip()
        prefix = f"{label}:"
        if rest.startswith(prefix):
            return rest[len(prefix) :].strip()
    return rest


def _tag_name(line: str) -> str | None:
    match = _TAG_RE.match(line)
    return match.group("tag") if match else None


def _is_known_del_tag(tag: str) -> bool:
    return tag in _DEL_KNOWN_TAGS or tag.startswith("AMBIGUOUS-")


def parse_del_something_output(output: str) -> ParseResult:
    """解析 DEL_SOMETHING 的标记行，只报告未知标签和格式错误。"""
    counts = _counts()
    items: list[dict[str, str | None]] = []
    lines = output.splitlines()
    in_summary = False
    ignore_next_hit = False
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        index += 1
        if not line:
            continue
        if in_summary:
            # 汇总段是无标签的“键: 值”行；遇到下一条带标签的行（下一条整理任务开始）就结束汇总段
            if not line.startswith("["):
                continue
            in_summary = False
        if line.startswith("[SUMMARY]"):
            in_summary = True
            continue
        if ignore_next_hit:
            if _HIT_LINE_RE.match(line):
                ignore_next_hit = False
                continue
            ignore_next_hit = False

        if line.startswith("[ALREADY-PLACED]"):
            ignore_next_hit = True
            continue
        if line.startswith(("[INFO]", "[SKIP]")):
            continue

        deleted_match = re.match(r"^\[DELETED\]\s*已删除(目录|文件)\s*[:：]\s*(?P<path>\S.*)$", line)
        if deleted_match:
            kind = "deleted_dir" if deleted_match.group(1) == "目录" else "deleted_file"
            count_key = "deleted_dirs" if kind == "deleted_dir" else "deleted_files"
            counts[count_key] += 1
            items.append(_item(kind, path=deleted_match.group("path").strip()))
            continue
        if line.startswith("[DELETED]"):
            counts["unparsed_lines"] += 1
            continue
        if line.startswith("[EMPTY]"):
            path = _strip_label(_rest_after_marker(line, "[EMPTY]"), ("空文件夹", "空目录")) or None
            counts["empty_dirs"] += 1
            items.append(_item("empty_dir", path=path))
            continue
        moved_match = re.match(r"^\[MOVED\]\s*(?P<source>.+?)\s+->\s+(?P<target>.+?)\s*$", line)
        if moved_match:
            if index >= len(lines):
                counts["unparsed_lines"] += 1
                continue
            keyword_line = lines[index].strip()
            keyword_match = _HIT_LINE_RE.match(keyword_line)
            if keyword_match is None:
                counts["unparsed_lines"] += 1
                continue
            index += 1
            source = moved_match.group("source").strip()
            target = moved_match.group("target").strip()
            keyword = keyword_match.group("keyword").strip()
            kind = "moved_rescan" if re.search(r"已整理/抖音(?:风)?(?:/|$)", source) else "moved_new"
            counts[kind] += 1
            items.append(_item(kind, path=source, target_path=target, keyword=keyword))
            continue
        merged_match = re.match(r"^\[MERGED\]\s*(?P<source>.+?)\s+->\s+(?P<target>.+?)\s*$", line)
        if merged_match:
            source = merged_match.group("source").strip()
            kind = "moved_rescan" if re.search(r"已整理/抖音(?:风)?(?:/|$)", source) else "moved_new"
            counts[kind] += 1
            items.append(
                _item(kind, path=source, target_path=merged_match.group("target").strip(), message="合并到已有目录")
            )
            continue
        if line.startswith("[MOVED]"):
            counts["unparsed_lines"] += 1
            continue
        tag = _tag_name(line)
        if tag is None:
            # 无标签的说明、分隔线和自由文本不属于结构化日志。
            continue
        if not _is_known_del_tag(tag):
            counts["unparsed_lines"] += 1
            continue
        for marker, kind, count_key in (
            ("[AMBIGUOUS-LOW]", "ambiguous", "ambiguous"),
            ("[AMBIGUOUS]", "ambiguous", "ambiguous"),
            ("[SKIPPED]", "skipped", "skipped"),
            ("[WARN]", "warning", "warnings"),
        ):
            if line.startswith(marker):
                rest = _strip_label(_rest_after_marker(line, marker), ("文件过大", "跳过"))
                path, message = _path_or_message(rest)
                counts[count_key] += 1
                items.append(_item(kind, path=path, message=message))
                break
        else:
            error_marker = None
            if line.startswith("[ERROR]"):
                error_marker = "[ERROR]"
            elif line.startswith("[错误]"):
                error_marker = "[错误]"
            if error_marker is not None:
                rest = _rest_after_marker(line, error_marker)
                path, message = _path_or_message(rest)
                counts["errors"] += 1
                items.append(_item("error", path=path, message=message))
            else:
                # 其余已知标签是分隔线或状态提示，忽略其正文。
                continue

    return ParseResult(counts=counts, items=items)


_MOVE_SUMMARY_RE = re.compile(
    r"^完成\s*[:：]\s*移动\s*(?P<moved>\d+)\s*个\s*[,，]\s*"
    r"删除重复\s*(?P<duplicates_removed>\d+)\s*个\s*[,，]\s*"
    r"跳过\s*(?P<skipped>\d+)\s*个\s*[,，]\s*失败\s*(?P<failed>\d+)\s*个\s*$"
)


def parse_move_ssd_cache_output(output: str) -> ParseResult:
    """解析搬运脚本的汇总行，名单只保留跳过和失败项。"""
    counts = _counts()
    items: list[dict[str, str | None]] = []
    summary_found = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        summary_match = _MOVE_SUMMARY_RE.match(line)
        if summary_match:
            summary_found = True
            for key in ("moved", "duplicates_removed", "skipped", "failed"):
                counts[key] = int(summary_match.group(key))
            continue
        skipped_match = re.match(r"^(?:\[SKIPPED\]|\[SKIP\])\s*(.+?)\s*$|^跳过\s*[:：]\s*(.+?)\s*$", line)
        if skipped_match:
            items.append(_item("skipped", path=(skipped_match.group(1) or skipped_match.group(2)).strip()))
            continue
        failed_match = re.match(
            r"^(?:\[FAILED?\]\s*|\[ERROR\]\s*|(?:移动)?失败\s*[:：]\s*|\[移动失败\]\s*)(.+?)\s*$",
            line,
        )
        if failed_match:
            items.append(_item("error", path=failed_match.group(1).strip()))
            continue
        # MOVE 的其余输出是分隔线或自由文本，不计入未识别行。

    if not summary_found:
        # 没有汇总行时无法证明运行成功；用一个失败计数让服务端能计算 failed。
        counts["failed"] = max(1, counts["failed"])
    return ParseResult(counts=counts, items=items, summary_found=summary_found)


def parse_output(script_name: str, output: str) -> ParseResult:
    """按脚本名选择解析器，供单独测试和其他本地工具调用。"""
    if script_name == SCRIPT_DEL:
        return parse_del_something_output(output)
    if script_name == SCRIPT_MOVE:
        return parse_move_ssd_cache_output(output)
    raise ValueError(f"不支持的脚本名: {script_name}")


# 保留简短别名，方便部署机上的独立测试直接导入。
parse_del_output = parse_del_something_output
parse_move_output = parse_move_ssd_cache_output


_DRY_DELETE_RE = re.compile(r"^\[DRY-RUN\]\s*将删除(目录|文件)\s*[:：]\s*(?P<path>\S.*)$")
_DRY_MOVE_RE = re.compile(r"^\[DRY-RUN\]\s*(?P<source>/.+?)\s+->\s+(?P<target>.+?)\s*$")
_RESCAN_RE = re.compile(r"已整理/抖音(?:风)?(?:/|$)")


def parse_del_dry_run(output: str) -> ParseResult:
    """解析 DEL 演练输出：列出“将删除”“将移动”，其余行（错误、警告、歧义）按正式解析器处理并合并计数。"""
    base = parse_del_something_output(output)
    counts = dict(base.counts)
    items: list[dict[str, str | None]] = []
    lines = output.splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        delete_match = _DRY_DELETE_RE.match(line)
        if delete_match:
            kind = "deleted_dir" if delete_match.group(1) == "目录" else "deleted_file"
            counts["deleted_dirs" if kind == "deleted_dir" else "deleted_files"] += 1
            items.append(_item(kind, path=delete_match.group("path").strip(), message="演练"))
            continue
        move_match = _DRY_MOVE_RE.match(line)
        if move_match:
            next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
            hit = _HIT_LINE_RE.match(next_line)
            if hit is None:
                counts["unparsed_lines"] += 1
                continue
            source = move_match.group("source").strip()
            kind = "moved_rescan" if _RESCAN_RE.search(source) else "moved_new"
            counts[kind] += 1
            items.append(
                _item(
                    kind,
                    path=source,
                    target_path=move_match.group("target").strip(),
                    keyword=hit.group("keyword").strip(),
                    message="演练",
                )
            )
    return ParseResult(counts=counts, items=items + base.items, summary_found=base.summary_found)
