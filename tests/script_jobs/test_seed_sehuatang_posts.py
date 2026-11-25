from __future__ import annotations

import csv
from datetime import date

from sqlalchemy import select

from app.models.script_runs import SehuatangPost
from app.services.script_jobs.sehuatang_seed import seed_from_csv_dir


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["标题", "链接", "资源内容"])
        writer.writerows(rows)


def test_seed_reads_recent_files_dedupes_and_skips_bad_links(db_session, tmp_path):
    _write_csv(
        tmp_path / "shuhuatang_2026_11_25_0129.csv",
        [
            ["示例一", "https://sehuatang.org/thread-100-1-1.html", "magnet:?xt=urn:btih:A"],
            ["示例一", "https://sehuatang.org/thread-100-1-1.html", "Torrent File Saved"],
            ["坏链接", "https://sehuatang.org/home.php", "x"],
        ],
    )
    _write_csv(
        tmp_path / "shuhuatang_2026_11_12_0129.csv",
        [["示例二", "https://sehuatang.org/thread-200-1-1.html", "x"]],
    )
    # 超出 14 天，不读取
    _write_csv(
        tmp_path / "shuhuatang_2026_11_10_0128.csv",
        [["很旧", "https://sehuatang.org/thread-300-1-1.html", "x"]],
    )
    (tmp_path / "other.csv").write_text("not,a,match\n", encoding="utf-8")
    db_session.add(SehuatangPost(tid="200", title="已有", url="u", last_outcome="title_blocked"))
    db_session.commit()

    added = seed_from_csv_dir(db_session, tmp_path, days=14, today=date(2026, 11, 25))

    assert added == 1
    posts = {post.tid: post for post in db_session.scalars(select(SehuatangPost)).all()}
    assert set(posts) == {"100", "200"}
    assert posts["100"].last_outcome == "submitted"
    assert posts["100"].title == "（迁移导入）"
    assert posts["100"].submitted_at is None
    # 已存在的不改
    assert posts["200"].last_outcome == "title_blocked"


def test_seed_is_idempotent(db_session, tmp_path):
    _write_csv(
        tmp_path / "shuhuatang_2026_11_25_0129.csv",
        [["示例", "https://sehuatang.org/thread-400-1-1.html", "x"]],
    )
    assert seed_from_csv_dir(db_session, tmp_path, days=14, today=date(2026, 11, 25)) == 1
    assert seed_from_csv_dir(db_session, tmp_path, days=14, today=date(2026, 11, 25)) == 0
