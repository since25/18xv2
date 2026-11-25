"""
sehuatang 切换到 18x 时运行一次：把 Unraid 版最近 N 天 CSV 里的帖子编号记为“已提交”，
避免 18x 第一次运行把这些帖子重新提交给 qB。只读 CSV，可重复运行（已有的跳过）。

用法（在 18x 容器里）：python scripts/seed_sehuatang_posts.py --csv-dir <CSV 所在目录> --days 14
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.services.script_jobs.sehuatang_seed import seed_from_csv_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 sehuatang 已提交帖子编号")
    parser.add_argument("--csv-dir", required=True, help="Unraid 版 sehuatang 写 CSV 的目录")
    parser.add_argument("--days", type=int, default=14, help="导入最近多少天的 CSV（默认 14）")
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)
    if not csv_dir.is_dir():
        print(f"目录不存在：{csv_dir}", file=sys.stderr)
        return 2
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    with SessionLocal() as db:
        added = seed_from_csv_dir(db, csv_dir, days=args.days, today=today)
    print(f"新增 {added} 个已提交帖子编号")
    return 0


if __name__ == "__main__":
    sys.exit(main())
