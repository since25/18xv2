"""对指定删除批次里已删除的片子补跑配套文件清理（115 和 porn_tv1）。

删片批次删完视频后会自动清理同名的 nfo、图片、字幕；这里用于给已经完成的批次补跑。
默认只预览会删什么，加 --apply 才真正删除（115 端进回收站）。
一次只处理一个批次；清理失败会记在批次的文件行上，不影响片子的删除结果。

用法（在生产容器内执行）：
  docker exec docker-app-1 python scripts/actress_clean_leftovers.py --batch 12          # 只预览
  docker exec docker-app-1 python scripts/actress_clean_leftovers.py --batch 12 --apply  # 真正删除
"""
from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
# 单独运行脚本时 app.models 不会自动导入关键词模型，扫描条目的关系会配置失败
import app.models.keywords  # noqa: F401
from app.services.actresses.archive_service import ActressError
from app.services.actresses.delete_batch_service import DeleteBatchService
from app.services.actresses.delete_guard import FilmDeleteGuard, GuardError
from app.services.actresses.job_runner import _openlist_client, actress_enabled
from app.services.client_115.client import Real115Client

_GROUP_LABELS = {"remote_leftover": "115", "source_leftover": "本地"}


def main() -> int:
    parser = argparse.ArgumentParser(description="补跑女优删除批次的配套文件清理")
    parser.add_argument("--batch", type=int, required=True, help="删除批次编号")
    parser.add_argument("--apply", action="store_true", help="真正删除；不加只预览")
    args = parser.parse_args()

    settings = get_settings()
    if not actress_enabled(settings):
        print("女优功能未开启（ACTRESS_ENABLED），不清理")
        return 1
    source_root = getattr(settings, "actress_source_root", None)
    organized_root = getattr(settings, "actress_organized_root", None)
    if not source_root or not organized_root:
        print("女优删除未就绪：ACTRESS_SOURCE_ROOT / ACTRESS_ORGANIZED_ROOT 没配齐")
        return 1
    openlist = _openlist_client(settings)
    if openlist is None:
        print("未配置 OpenList（OPENLIST_URL / OPENLIST_TOKEN），无法确认 115 目录，不清理")
        return 1
    try:
        guard = FilmDeleteGuard(source_root, organized_root)
    except GuardError as exc:
        print(f"失败：{exc}")
        return 1

    client_115 = Real115Client(settings)
    with SessionLocal() as db:
        try:
            actions = DeleteBatchService().clean_leftovers(
                db,
                args.batch,
                client_115=client_115,
                guard=guard,
                openlist=openlist,
                apply=args.apply,
            )
        except ActressError as exc:
            print(f"失败：{exc}")
            return 1

    label = "已删除" if args.apply else "将删除"
    for action in actions:
        kind = "目录" if action.whole_dir else "文件"
        print(f"{label}  {_GROUP_LABELS[action.group]}  {kind}  {action.target}")
    whole_dirs = sum(1 for action in actions if action.whole_dir)
    print(f"共 {len(actions)} 项（目录 {whole_dirs}，文件 {len(actions) - whole_dirs}）")
    if not actions:
        print("没有可清理的配套文件")
    if not args.apply:
        print("只预览，未删除；确认无误后加 --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
