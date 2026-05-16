"""
关键词提取 CLI。从已导入的目录树批次中提取关键词候选，输出到标准输出。
用法：python scripts/keyword_extractor.py --import-id 1 [--top 50]
"""
from __future__ import annotations

import argparse
import sys

from app.db.session import SessionLocal
from app.services.classifier.keyword_extractor_service import KeywordExtractorService


def main() -> int:
    parser = argparse.ArgumentParser(description="从目录树批次提取关键词候选")
    parser.add_argument("--import-id", type=int, required=True, help="目录树导入批次 ID")
    parser.add_argument("--top", type=int, default=50, help="最多输出前 N 个候选词（默认 50）")
    parser.add_argument("--keywords", nargs="*", default=None, help="手工指定关键词列表，空格分隔")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        service = KeywordExtractorService(db)
        if args.keywords:
            stats = service.extract_manual_keywords(
                import_id=args.import_id,
                keywords=args.keywords,
            )
        else:
            stats = service.extract_from_folder_names(
                import_id=args.import_id,
                top_n=args.top,
            )
        print(f"[结果] 共 {len(stats)} 个关键词候选（import_id={args.import_id}）：")
        for stat in stats[:args.top]:
            print(f"  [{stat.count:4d}] {stat.keyword}  ({stat.source})")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
