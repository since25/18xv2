#!/usr/bin/env python3
"""待审核候选词提取的回归验证。

用「已批准的历史记录」当标准答案集：你当初手工确认的那个关键词，就是正确答案。
本脚本用新提取规则重跑这些路径，看正确答案有没有出现在候选里。

只读运行（除非显式加 --apply-pending）。默认只打印汇总数字，不打印任何路径
与关键词明细；需要人工抽查时再加 --show-details。

用法：
    python scripts/verify_review_intake_candidates.py
    python scripts/verify_review_intake_candidates.py --show-details
    python scripts/verify_review_intake_candidates.py --apply-pending
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.review_intake import ReviewIntakeItem  # noqa: E402
from app.services.keywords.registry_service import (  # noqa: E402
    KeywordRegistryService,
    normalize_keyword_text,
)
from app.services.review_intake_candidates import extract_raw_candidates  # noqa: E402
from app.services.review_intake_service import ReviewIntakeService  # noqa: E402

TOP_N = 5


def _load_ignore_tokens(db: Session) -> set[str]:
    entries, _total = KeywordRegistryService(db).list_entries(
        keyword_type="ignore", status="active", limit=5000
    )
    return {entry.canonical_name_normalized for entry in entries}


def _pure_candidates(raw_path: str, ignore_tokens: set[str]) -> list[str]:
    """只跑纯提取链路：切片 → 结构过滤 → 忽略库过滤 → 排序。

    刻意不做"和关键词库比对"这一步。因为这些历史记录批准时已经把答案写进了
    关键词库，跑完整管线会把正确答案标成 existing 归到提示组，反而判成未命中，
    这是数据泄漏。真实场景里新人名并不在库中。
    """
    result = []
    for item in extract_raw_candidates(raw_path):
        normalized = normalize_keyword_text(item.text)
        if normalized in ignore_tokens:
            continue
        result.append(item.text)
    return result


def _hit(answer: str, candidates: list[str], top_n: int | None = None) -> bool:
    target = normalize_keyword_text(answer).casefold()
    pool = candidates if top_n is None else candidates[:top_n]
    return any(normalize_keyword_text(text).casefold() == target for text in pool)


def _old_rule_hit(item: ReviewIntakeItem) -> bool:
    """旧规则当初有没有把答案提出来（直接读当初落库的候选）。"""
    try:
        stored = json.loads(item.extracted_keywords_json or "[]")
    except json.JSONDecodeError:
        return False
    words = [entry.get("keyword", "") for entry in stored if isinstance(entry, dict)]
    return _hit(item.approved_keyword or "", words)


def _report(title: str, rows: list[tuple[bool, bool]], target_text: str) -> float:
    total = len(rows)
    if total == 0:
        print(f"{title}：没有样本，跳过")
        return 0.0
    strict = sum(1 for narrow, _wide in rows if narrow)
    wide = sum(1 for _narrow, wide in rows if wide)
    rate = strict / total * 100
    print(f"{title}")
    print(f"  样本 {total} 条")
    print(f"  正确答案出现在前 {TOP_N} 个候选里：{strict} 条，命中率 {rate:.1f}%（{target_text}）")
    print(f"  放宽到候选任意位置：{wide} 条，命中率 {wide / total * 100:.1f}%")
    return rate


def main() -> int:
    parser = argparse.ArgumentParser(description="回归验证待审核候选词提取效果。")
    parser.add_argument("--database-url", help="覆盖 DATABASE_URL")
    parser.add_argument("--show-details", action="store_true", help="打印未命中样本的明细（含路径，谨慎使用）")
    parser.add_argument("--apply-pending", action="store_true", help="用新规则重算所有待审项的候选并写回数据库")
    args = parser.parse_args()

    url = args.database_url or get_settings().database_url
    engine = create_engine(url, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db: Session = factory()

    try:
        ignore_tokens = _load_ignore_tokens(db)
        approved = db.scalars(
            select(ReviewIntakeItem).where(
                ReviewIntakeItem.status == "approved",
                ReviewIntakeItem.approved_keyword.is_not(None),
            )
        ).all()

        zero_rows: list[tuple[bool, bool]] = []
        kept_rows: list[tuple[bool, bool]] = []
        old_baseline = 0
        misses: list[ReviewIntakeItem] = []

        for item in approved:
            candidates = _pure_candidates(item.raw_path, ignore_tokens)
            narrow = _hit(item.approved_keyword, candidates, TOP_N)
            wide = _hit(item.approved_keyword, candidates)
            if _old_rule_hit(item):
                kept_rows.append((narrow, wide))
                old_baseline += 1
            else:
                zero_rows.append((narrow, wide))
            if not narrow:
                misses.append(item)

        print("=" * 64)
        print(f"关键词库中的忽略词：{len(ignore_tokens)} 个（用于过滤噪声片段）")
        print("=" * 64)
        rate = _report(
            "【指标一】当初捕获失败、只能手工确认的记录",
            zero_rows,
            "目标 ≥80%",
        )
        print()
        _report(
            "【指标二】当初旧规则就能捕获的记录（防退化）",
            kept_rows,
            f"旧规则基线 {old_baseline}/{len(kept_rows)} = 100.0%",
        )
        print()
        print("说明：以上是在同一批用于调规则的历史样本上测出的成绩，属于训练集口径，")
        print("      上线后请以新投递记录的真实命中率为准。")

        if args.show_details:
            print()
            print(f"未命中样本 {len(misses)} 条明细：")
            for item in misses:
                candidates = _pure_candidates(item.raw_path, ignore_tokens)
                print(f"  答案={item.approved_keyword!r}")
                print(f"    路径={item.raw_path}")
                print(f"    候选={candidates[:TOP_N]}")

        if args.apply_pending:
            service = ReviewIntakeService(db)
            pending = db.scalars(
                select(ReviewIntakeItem).where(ReviewIntakeItem.status == "pending")
            ).all()
            for item in pending:
                candidates = service._extract_and_resolve_keywords(
                    bucket=item.bucket,
                    raw_path=item.raw_path,
                    pattern="",
                    flags="",
                    group_index=1,
                    limit=12,
                )
                item.extracted_keywords_json = json.dumps(
                    [entry.model_dump() for entry in candidates], ensure_ascii=False
                )
            db.commit()
            print()
            print(f"已用新规则重算 {len(pending)} 条待审项的候选词。")

        print()
        if rate >= 80:
            print(f"结论：指标一 {rate:.1f}% 达到 80% 目标，验收通过。")
            return 0
        print(f"结论：指标一 {rate:.1f}% 未达到 80% 目标，需要继续调规则。")
        return 1
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
