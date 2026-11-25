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


def test_cli_script_runs_standalone_against_real_database(db_session, tmp_path):
    """命令行脚本单独运行（不经过测试夹具导入全部模型）也要能用。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    today = date.today().strftime("%Y_%m_%d")
    _write_csv(csv_dir / f"shuhuatang_{today}_0129.csv", [["示例", "https://sehuatang.org/thread-700-1-1.html", "x"]])
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path}/test.db", PYTHONPATH=str(root))
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "seed_sehuatang_posts.py"), "--csv-dir", str(csv_dir)],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "新增 1 个" in result.stdout
    db_session.expire_all()
    assert db_session.scalar(select(SehuatangPost).where(SehuatangPost.tid == "700")) is not None


def test_seed_is_idempotent(db_session, tmp_path):
    _write_csv(
        tmp_path / "shuhuatang_2026_11_25_0129.csv",
        [["示例", "https://sehuatang.org/thread-400-1-1.html", "x"]],
    )
    assert seed_from_csv_dir(db_session, tmp_path, days=14, today=date(2026, 11, 25)) == 1
    assert seed_from_csv_dir(db_session, tmp_path, days=14, today=date(2026, 11, 25)) == 0
