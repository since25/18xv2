"""白名单候选服务：扫描、提交、列表、丢弃、恢复。

依赖 MagnetDownloadService 的底层 API：
- build_candidates_for_keyword_entry
- _check_single_duplicate
- _build_target_path
- create_and_submit_tasks

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry
from app.models.whitelist import WhitelistCandidate
from app.schemas.magnet_tasks import DuplicateCheckItemRequest
from app.schemas.whitelist import ScanSummary
from app.services.tasks.organize_task_service import OrganizeTaskService

logger = logging.getLogger(__name__)


class WhitelistCandidateService:
    def __init__(self, db: Session, *, magnet_svc):
        self.db = db
        self.magnet_svc = magnet_svc

    def _load_whitelist_entries(self, keyword_entry_ids):
        stmt = (
            select(KeywordEntry)
            .where(KeywordEntry.keyword_type == "whitelist")
            .where(KeywordEntry.status == "active")
            .order_by(KeywordEntry.id.asc())
        )
        if keyword_entry_ids:
            stmt = stmt.where(KeywordEntry.id.in_(keyword_entry_ids))
        entries = list(self.db.scalars(stmt).all())
        if not entries:
            raise ValueError("未找到任何 active 白名单关键词")
        return entries

    def scan(
        self, *,
        tree_import_id: int,
        keyword_entry_ids: list[int] | None,
        per_keyword_limit: int,
        progress_cb: Callable[[str, int, int], None],
    ) -> ScanSummary:
        entries = self._load_whitelist_entries(keyword_entry_ids)
        directory_names = OrganizeTaskService._build_keyword_directory_names(entries)
        progress_cb("加载关键词", 0, len(entries))

        new = updated = skipped = failed = 0

        for idx, entry in enumerate(entries):
            progress_cb("扫描外部库", idx + 1, len(entries))
            try:
                raw_candidates = self.magnet_svc.build_candidates_for_keyword_entry(
                    keyword_entry=entry, limit=per_keyword_limit,
                )
                for cand in raw_candidates:
                    existing = self.db.scalar(select(WhitelistCandidate).where(
                        WhitelistCandidate.source_tid == cand.source_tid,
                        WhitelistCandidate.source_magnet == cand.source_magnet,
                        WhitelistCandidate.matched_keyword_entry_id == entry.id,
                    ))
                    # 低成本状态：刷新 last_scanned_at 但不动其它字段
                    if existing and existing.lifecycle_status in {"submitted", "dismissed"}:
                        existing.last_scanned_at = datetime.now(UTC)
                        skipped += 1
                        continue
                    if existing and existing.duplicate_status == "task_exists":
                        existing.last_scanned_at = datetime.now(UTC)
                        skipped += 1
                        continue

                    # clear / duplicate_found / 新候选 → 重新评估 duplicate
                    dup_input = DuplicateCheckItemRequest(
                        source_tid=cand.source_tid,
                        source_title=cand.source_title,
                        source_magnet=cand.source_magnet,
                        matched_keyword=cand.matched_keyword,
                        matched_alias=cand.matched_alias,
                    )
                    dup = self.magnet_svc._check_single_duplicate(
                        dup_input, tree_import_id=tree_import_id,
                    )
                    target_path = self.magnet_svc._build_target_path(
                        keyword_dir=directory_names[entry.id],
                        source_title=cand.source_title,
                    )

                    if existing is None:
                        self.db.add(WhitelistCandidate(
                            source_tid=cand.source_tid,
                            source_magnet=cand.source_magnet,
                            source_title=cand.source_title,
                            source_section=cand.source_section,
                            source_detail_url=cand.source_detail_url,
                            matched_keyword_entry_id=entry.id,
                            matched_keyword=cand.matched_keyword,
                            matched_alias=cand.matched_alias,
                            match_score=cand.match_score,
                            last_scanned_tree_import_id=tree_import_id,
                            duplicate_status=dup.status,
                            duplicate_reason=dup.reason,
                            matched_import_label=dup.matched_import_label,
                            target_path=target_path,
                            lifecycle_status="pending",
                        ))
                        new += 1
                    else:
                        existing.duplicate_status = dup.status
                        existing.duplicate_reason = dup.reason
                        existing.matched_import_label = dup.matched_import_label
                        existing.target_path = target_path
                        existing.last_scanned_tree_import_id = tree_import_id
                        existing.last_scanned_at = datetime.now(UTC)
                        updated += 1
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("scan 关键词 %s 失败", entry.canonical_name)
                failed += 1

        return ScanSummary(
            scanned_keywords=len(entries),
            new=new, updated=updated, skipped=skipped, failed_keywords=failed,
        )
