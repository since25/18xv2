"""
将 examples/rules.yaml 同步到数据库 strategy_rules 表。
每次部署后运行一次，确保规则库与 YAML 保持一致。
用法：python scripts/sync_strategy_rules.py [--dry-run] [--rules-file PATH]
"""
from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.strategy_rule_service import StrategyRuleService


def main() -> int:
    parser = argparse.ArgumentParser(description="将 rules.yaml 同步到 strategy_rules 表")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要变更的规则，不写库")
    parser.add_argument("--rules-file", default=None, help="指定规则文件路径（默认读 settings.rules_file）")
    args = parser.parse_args()

    settings = get_settings()
    rules_file = args.rules_file or settings.rules_file

    print(f"[sync] 规则文件：{rules_file}")

    if args.dry_run:
        print("[dry-run] 仅预览，不写库")
        # 只加载并打印，不连 DB
        from app.services.classifier.keyword_classifier import load_rules_from_yaml
        try:
            payload = load_rules_from_yaml(rules_file)
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 读取规则文件失败：{exc}", file=sys.stderr)
            return 1
        rules = payload.get("rules", [])
        print(f"[dry-run] 共 {len(rules)} 条规则：")
        for rule in rules:
            print(f"  - {rule.get('name')} | priority={rule.get('priority')} | target_root={rule.get('target_root')}")
        return 0

    db = SessionLocal()
    try:
        service = StrategyRuleService(db)
        result = service.sync_yaml_to_db(rules_file)
        print(f"[成功] created={result.get('created', 0)} updated={result.get('updated', 0)} deactivated={result.get('deactivated', 0)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 同步失败：{exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
