"""
手动维护本地已整理视频在 Jellyfin 里的显示名（序号 · 关键词/资源包）。
不受 JELLYFIN_DISPLAY_NAMES_ENABLED 开关限制，但需要 Jellyfin 地址和 API Key。

用法（在生产容器内执行）：
  docker exec docker-app-1 python scripts/jellyfin_display_names.py --dry-run              # 只预览，不写入
  docker exec docker-app-1 python scripts/jellyfin_display_names.py --keyword 名字          # 只改一个关键词
  docker exec docker-app-1 python scripts/jellyfin_display_names.py                        # 全量
  docker exec docker-app-1 python scripts/jellyfin_display_names.py --restore [--keyword 名字]  # 回滚：改回文件名并解锁
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import sys

from app.db.session import SessionLocal
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin.job_runner import JOB_NAMES, JobAlreadyRunning, run_names_job, start_job


def main() -> int:
    parser = argparse.ArgumentParser(description="维护 Jellyfin 本地视频显示名")
    parser.add_argument("--dry-run", action="store_true", help="只计算并比对，不写入 Jellyfin")
    parser.add_argument("--keyword", default=None, help="只处理这个关键词（规范名或别名）下的视频")
    parser.add_argument("--restore", action="store_true", help="回滚：名字改回文件名（去掉扩展名）并解锁")
    args = parser.parse_args()

    with SessionLocal() as db:
        try:
            job_id = start_job(db, JOB_NAMES)
        except JobAlreadyRunning:
            print("已有显示名同步任务在运行，请稍后再试")
            return 1

    # 与页面和定时任务共用后台任务记录，结果也写进 background_jobs
    try:
        run_names_job(job_id, dry_run=args.dry_run, keyword=args.keyword, restore=args.restore)
    except KeyboardInterrupt:
        # 不收尾的话任务会一直显示"运行中"，挡住之后的手动运行和每日任务
        with SessionLocal() as db:
            BackgroundJobService.update(
                db, job_id, stage="失败", done=True, error="手动中断", finished_at=datetime.now(UTC)
            )
        print("已中断，任务记为失败；已改过的名字保留，重新运行会从头比对")
        return 130

    with SessionLocal() as db:
        job = BackgroundJobService.get(db, job_id) or {}
    if job.get("error") or job.get("stage") == "失败":
        print(f"失败：{job.get('error') or '未知错误'}")
        return 1
    summary = job.get("summary") or {}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 有条目或合集没改成功时返回非 0，避免看起来像全部成功
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
