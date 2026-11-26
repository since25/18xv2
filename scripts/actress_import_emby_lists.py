"""
一次性把旧 Emby 黑白名单（启用中的 emby_blacklist / emby_whitelist 关键词）导入女优档案。
关键词本身不改不删。默认只列出，加 --apply 才写入（标记来源记为「导入」），写入后重算待删清单。
同一人同时在黑白两边的不导入，列为冲突。

用法（在生产容器内执行）：
  docker exec docker-app-1 python scripts/actress_import_emby_lists.py            # 只列出，不写入
  docker exec docker-app-1 python scripts/actress_import_emby_lists.py --apply    # 写入
"""
from __future__ import annotations

import argparse
from collections import Counter
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.actresses.archive_service import ActressError
from app.services.actresses.emby_import import import_emby_lists
from app.services.actresses.job_runner import actress_enabled

_RESULT_LABELS = {"will_set": "将设置", "set": "已设置", "unchanged": "不变", "conflict": "冲突"}
_STATUS_LABELS = {"blacklist": "黑名单", "whitelist": "白名单"}


def main() -> int:
    parser = argparse.ArgumentParser(description="把旧 Emby 黑白名单导入女优档案")
    parser.add_argument("--apply", action="store_true", help="真正写入；不加只列出")
    args = parser.parse_args()

    settings = get_settings()
    # 写入会重算待删清单，功能关闭时不建清单
    if args.apply and not actress_enabled(settings):
        print("女优功能未开启（ACTRESS_ENABLED），不导入")
        return 1

    with SessionLocal() as db:
        try:
            rows = import_emby_lists(
                db, apply=args.apply, strm_roots=list(settings.media_library_strm_roots or [])
            )
        except ActressError as exc:
            print(f"失败：{exc}")
            return 1

    for row in rows:
        line = f"{_RESULT_LABELS[row.result]} {row.name} → {_STATUS_LABELS[row.target_status]}"
        print(f"{line}（{row.note}）" if row.note else line)
    counts = Counter(row.result for row in rows)
    shown = ("set" if args.apply else "will_set", "unchanged", "conflict")
    summary = "，".join(f"{_RESULT_LABELS[result]} {counts[result]}" for result in shown)
    print(f"共 {len(rows)} 条：{summary}")
    if not args.apply:
        print("只列出，未写入；确认无误后加 --apply 写入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
