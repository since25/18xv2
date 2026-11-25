"""切换到 18x 时一次性导入：最近 N 天 Unraid 版 sehuatang 的 CSV 里出现过的帖子编号，记为已提交。

只为跨天去重，不导入标题、资源明细，也不生成运行记录。
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.script_runs import SehuatangPost
from app.services.script_jobs.sehuatang.pages import tid_from_url


CSV_NAME_RE = re.compile(r"^shuhuatang_(\d{4})_(\d{2})_(\d{2})_\d{4}\.csv$")
SEED_TITLE = "（迁移导入）"


def _recent_files(csv_dir: Path, *, days: int, today: date) -> list[Path]:
    earliest = today - timedelta(days=days)
    files = []
    for path in sorted(Path(csv_dir).iterdir()):
        match = CSV_NAME_RE.match(path.name)
        if not match:
            continue
        file_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if earliest < file_date <= today:
            files.append(path)
    return files


def seed_from_csv_dir(db: Session, csv_dir: Path, *, days: int = 14, today: date) -> int:
    """导入最近 days 天 CSV 里的帖子编号；已存在的跳过，返回新增条数。"""
    found: dict[str, str] = {}
    for path in _recent_files(csv_dir, days=days, today=today):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                if len(row) < 2:
                    continue
                tid = tid_from_url(row[1])
                if tid:
                    found.setdefault(tid, row[1])
    if not found:
        return 0
    existing = set(db.scalars(select(SehuatangPost.tid).where(SehuatangPost.tid.in_(list(found)))).all())
    now = datetime.now(UTC)
    added = 0
    for tid, url in found.items():
        if tid in existing:
            continue
        db.add(SehuatangPost(tid=tid, title=SEED_TITLE, url=url, first_seen_at=now, last_outcome="submitted",
                             updated_at=now))
        added += 1
    db.commit()
    return added
