from __future__ import annotations

from app.services.script_jobs.media_output import parse_del_dry_run, parse_output
from scripts.unraid.report_script_run import parse_del_something_output


DEL_SAMPLE = "\n".join(
    [
        "[DELETED] 已删除目录：/data/finish/示例目录A",
        "[DELETED] 已删除文件：/data/finish/示例文件A.mkv",
        "[EMPTY] /data/finish/示例空目录",
        "[MOVED] /data/finish/示例资源B -> /data/已整理/示例词/示例资源B",
        "命中词项: 示例词",
        "[AMBIGUOUS-LOW] 示例歧义词",
        "[WARN] 示例警告消息",
        "[SUMMARY]",
        "move candidates: 1",
    ]
)


def test_parsers_importable_from_app() -> None:
    assert parse_output("DEL_SOMETHING", DEL_SAMPLE) == parse_del_something_output(DEL_SAMPLE)


def test_del_parser_keeps_counting_after_each_organize_summary() -> None:
    # DEL 依次跑多条整理任务，每条结尾都打印一段 [SUMMARY]；后面任务的移动和错误也要计入
    output = "\n".join(
        [
            "[INFO] Organizing: /data/finish -> /data/已整理",
            "[MOVED] /data/finish/示例B -> /data/已整理/示例词/示例B",
            "        命中标准词: 示例词",
            "[SUMMARY]",
            "move candidates: 1",
            "ambiguous: 0",
            "skip: 0",
            "log: /tmp/organize.txt",
            "[INFO] Organizing: /data/已整理/抖音 -> /data/已整理",
            "[MOVED] /data/已整理/抖音/示例C -> /data/已整理/示例词/示例C",
            "        命中标准词: 示例词",
            "[ERROR] 移动失败: /data/已整理/抖音/示例D -> /data/已整理/示例词/示例D | 示例原因",
            "[SUMMARY]",
            "move candidates: 1",
        ]
    )
    result = parse_output("DEL_SOMETHING", output)
    assert result.counts["moved_new"] == 1
    assert result.counts["moved_rescan"] == 1
    assert result.counts["errors"] == 1
    assert result.counts["unparsed_lines"] == 0


def test_dry_run_lists_would_delete_and_would_move() -> None:
    output = "\n".join(
        [
            "[INFO] 加载关键词数量：2",
            "[DRY-RUN] 将删除目录：/data/finish/示例坏目录",
            "[DRY-RUN] 将删除文件：/data/finish/示例坏文件.mp4",
            "[完成] 未实际删除，日志保存于 /tmp/x.txt",
            "[INFO] Organizing: /data/finish -> /data/已整理",
            "[DRY-RUN] /data/finish/示例B -> /data/已整理/示例词/示例B",
            "          命中标准词: 示例词",
            "          命中词项: 示例词",
            "[DRY-RUN] /data/已整理/抖音/示例C -> /data/已整理/示例词/示例C",
            "          命中标准词: 示例词",
            "          命中词项: 示例别名",
            "[WARN] 示例警告",
        ]
    )
    result = parse_del_dry_run(output)

    assert result.counts["deleted_dirs"] == 1
    assert result.counts["deleted_files"] == 1
    assert result.counts["moved_new"] == 1
    assert result.counts["moved_rescan"] == 1
    assert result.counts["warnings"] == 1
    plan_items = [item for item in result.items if item["kind"] != "warning"]
    assert [item["kind"] for item in plan_items] == ["deleted_dir", "deleted_file", "moved_new", "moved_rescan"]
    assert all(item["message"] == "演练" for item in plan_items)
    assert plan_items[0]["path"] == "/data/finish/示例坏目录"
    moved = [item for item in plan_items if item["kind"].startswith("moved")]
    assert all(item["keyword"] == "示例词" for item in moved)
    assert moved[1]["path"] == "/data/已整理/抖音/示例C"
    assert moved[1]["target_path"] == "/data/已整理/示例词/示例C"


def test_del_parser_counts_merged_and_ambiguous_in_later_jobs() -> None:
    output = "\n".join(
        [
            "[INFO] Organizing: /data/finish -> /data/已整理",
            "[SUMMARY]",
            "move candidates: 0",
            "[INFO] Organizing: /data/已整理/抖音 -> /data/已整理",
            "[MERGED] /data/已整理/抖音/示例E -> /data/已整理/示例词/示例E",
            "          合并: 新移入 2 项 | 重复去重 1 项 | 同名冲突保留 0 项",
            "          [WARN] 源目录未清空(仍有内容), 保留待下轮处理: /data/已整理/抖音/示例E",
            "[AMBIGUOUS] /data/已整理/抖音/示例F",
            "            命中多个 whitelist: 甲 (甲) | 乙 (乙) | 丙 (丙) | 丁 (丁)",
            "[SUMMARY]",
        ]
    )
    result = parse_output("DEL_SOMETHING", output)
    assert result.counts["unparsed_lines"] == 0
    assert result.counts["moved_rescan"] == 1
    assert result.counts["ambiguous"] == 1
    assert result.counts["warnings"] == 1
    merged = next(item for item in result.items if item["kind"] == "moved_rescan")
    assert merged["target_path"] == "/data/已整理/示例词/示例E"
    assert merged["message"] == "合并到已有目录"
    ambiguous = next(item for item in result.items if item["kind"] == "ambiguous")
    assert ambiguous["path"] == "/data/已整理/抖音/示例F"
