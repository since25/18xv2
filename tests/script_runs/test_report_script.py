from __future__ import annotations

from datetime import UTC, datetime

from scripts.unraid.report_script_run import (
    build_report_payload,
    main,
    parse_del_something_output,
    parse_move_ssd_cache_output,
)


def test_parse_del_something_covers_reported_line_types() -> None:
    output = "\n".join(
        [
            "[DELETED] 已删除目录：/data/finish/示例目录A",
            "[DELETED] 已删除文件：/data/finish/示例文件A.mkv",
            "[EMPTY] /data/finish/示例空目录",
            "[MOVED] /data/finish/示例资源B -> /data/已整理/示例词/示例资源B",
            "命中词项: 示例词",
            "[MOVED] /data/已整理/抖音/示例资源C -> /data/已整理/示例词/示例资源C",
            "命中标准词: 示例词",
            "[AMBIGUOUS-LOW] 示例歧义词",
            "[SKIPPED] /data/finish/示例超大文件.mkv",
            "[ERROR] /data/finish/示例错误.mkv",
            "[错误] 示例错误消息",
            "[WARN] 示例警告消息",
            "[ALREADY-PLACED] /data/已整理/示例资源D",
            "命中词项: 示例词",
            "[INFO] 忽略信息",
            "移动词项:",
            "普通日志文本",
            "[处理] 开始处理",
            "[完成] 处理完成",
            "[BACKUP] 备份完成",
            "[DRY-RUN] 演练模式",
            "[UNKNOWN] 未知标签",
            "[DELETED] 格式不正确",
            "[MOVED] /data/finish/示例资源E /data/已整理/示例词/示例资源E",
            "[SUMMARY]",
            "清理完成",
        ]
    )

    result = parse_del_something_output(output)

    assert result.counts == {
        "deleted_dirs": 1,
        "deleted_files": 1,
        "empty_dirs": 1,
        "moved_new": 1,
        "moved_rescan": 1,
        "ambiguous": 1,
        "skipped": 1,
        "errors": 2,
        "warnings": 1,
        "unparsed_lines": 3,
        "moved": 0,
        "duplicates_removed": 0,
        "failed": 0,
    }
    assert [item["kind"] for item in result.items] == [
        "deleted_dir",
        "deleted_file",
        "empty_dir",
        "moved_new",
        "moved_rescan",
        "ambiguous",
        "skipped",
        "error",
        "error",
        "warning",
    ]
    assert result.items[3]["target_path"] == "/data/已整理/示例词/示例资源B"
    assert result.items[3]["keyword"] == "示例词"


def test_del_ignores_unlabeled_text_and_known_section_labels() -> None:
    result = parse_del_something_output(
        "\n".join(
            [
                "移动:",
                "合并目录:",
                "清理空目录:",
                "设置权限",
                "[处理] 正在处理",
                "[完成] 已完成",
                "[BACKUP] 已备份",
                "[DRY-RUN] 演练",
                "[UNKNOWN] 未知标签",
                "[DELETED] 不是目录或文件",
                "[MOVED] /data/finish/示例资源A /data/已整理/示例词/示例资源A",
            ]
        )
    )

    assert result.counts["unparsed_lines"] == 3


def test_parse_move_requires_completion_summary_and_keeps_only_problems() -> None:
    complete = parse_move_ssd_cache_output(
        "\n".join(
            [
                "移动 /data/cache/示例A 到 /data/disk2/示例A",
                "跳过：/data/cache/示例B",
                "失败：/data/cache/示例C",
                "完成: 移动 4 个, 删除重复 2 个, 跳过 1 个, 失败 1 个",
            ]
        )
    )
    assert complete.counts["moved"] == 4
    assert complete.counts["duplicates_removed"] == 2
    assert complete.counts["skipped"] == 1
    assert complete.counts["failed"] == 1
    assert [item["kind"] for item in complete.items] == ["skipped", "error"]
    assert complete.summary_found is True

    incomplete = parse_move_ssd_cache_output("移动 /data/cache/示例A 到 /data/disk2/示例A")
    assert incomplete.summary_found is False
    assert incomplete.counts["failed"] == 1


def test_parse_move_ignores_section_text_without_unparsed_warnings() -> None:
    result = parse_move_ssd_cache_output(
        "\n".join(
            [
                "移动:",
                "合并目录:",
                "清理空目录:",
                "设置权限",
                "开始处理示例资源",
                "完成: 移动 1 个, 删除重复 0 个, 跳过 0 个, 失败 0 个",
            ]
        )
    )

    assert result.summary_found is True
    assert result.counts["unparsed_lines"] == 0


def test_build_report_payload_uses_utc_and_run_key() -> None:
    payload = build_report_payload(
        "DEL_SOMETHING",
        "2026-11-02T12:09:00+08:00",
        0,
        "[DELETED] 已删除文件：/data/finish/示例文件A.mkv",
    )

    assert payload["run_key"] == "DEL_SOMETHING:2026-11-02T12:09:00+08:00"
    assert payload["finished_at"].endswith("Z")
    assert payload["counts"]["deleted_files"] == 1
    assert datetime.fromisoformat(payload["finished_at"].replace("Z", "+00:00")).tzinfo == UTC


def test_report_main_is_zero_for_network_failure_and_dry_run(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "run.log"
    output_file.write_text("[DELETED] 已删除文件：/data/finish/示例文件A.mkv\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("KEYWORDS_API_USERNAME=demo\nKEYWORDS_API_PASSWORD=demo\n", encoding="utf-8")
    monkeypatch.setattr("scripts.unraid.report_script_run._send_report", lambda *args, **kwargs: False)

    assert (
        main(
            [
                "DEL_SOMETHING",
                "2026-11-02T04:09:00Z",
                "1",
                str(output_file),
                str(env_file),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "DEL_SOMETHING",
                "2026-11-02T04:09:00Z",
                "1",
                str(output_file),
                str(env_file),
                "--dry-run",
            ]
        )
        == 0
    )

