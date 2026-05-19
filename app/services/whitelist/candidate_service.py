"""白名单候选服务：扫描、提交、列表、丢弃、恢复。

依赖 MagnetDownloadService 的底层 API：
- build_candidates_for_keyword_entry
- check_single_duplicate
- build_target_path
- create_and_submit_tasks

详见 docs/superpowers/specs/2026-05-19-whitelist-batch-page-design.md §4
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, UTC

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry
from app.models.whitelist import WhitelistCandidate
from app.schemas.magnet_tasks import DuplicateCheckItemRequest, MagnetTaskCreateItem
from app.schemas.whitelist import ScanSummary, SubmitSummary
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
                    dup = self.magnet_svc.check_single_duplicate(
                        dup_input, tree_import_id=tree_import_id,
                    )
                    target_path = self.magnet_svc.build_target_path(
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
            except Exception as exc:
                self.db.rollback()
                logger.exception(
                    "scan 关键词 %s 失败 (%s)", entry.canonical_name, type(exc).__name__,
                )
                failed += 1

        return ScanSummary(
            scanned_keywords=len(entries),
            new=new, updated=updated, skipped=skipped, failed_keywords=failed,
        )

    def submit_selected(
        self, *,
        candidate_ids: list[int],
        force_submit: bool,
        progress_cb: Callable[[str, int, int], None],
    ) -> SubmitSummary:
        if not candidate_ids:
            raise ValueError("未选择有效的候选项")
        candidates = list(self.db.scalars(
            select(WhitelistCandidate).where(WhitelistCandidate.id.in_(candidate_ids))
        ).all())
        if not candidates:
            raise ValueError("未选择有效的候选项")

        submitted = failed = skipped = 0
        for idx, cand in enumerate(candidates):
            progress_cb("提交到 115", idx, len(candidates))
            # 防御并发：scan 可能并行改写过 cand，重读最新状态
            self.db.refresh(cand)
            if cand.lifecycle_status != "pending":
                skipped += 1
                continue
            try:
                task = self.magnet_svc.create_and_submit_tasks(
                    items=[_candidate_to_create_item(cand)],
                    force_submit=force_submit,
                    tree_import_id=cand.last_scanned_tree_import_id,
                )[0]
                cand.magnet_task_id = task.id
                if task.status == "submitted":
                    cand.lifecycle_status = "submitted"
                    cand.submitted_at = datetime.now(UTC)
                    submitted += 1
                elif task.status == "duplicate_skipped":
                    cand.lifecycle_status = "submitted"  # 已存在视同已处理
                    cand.submitted_at = datetime.now(UTC)
                    skipped += 1
                else:  # "failed"
                    cand.lifecycle_status = "failed"
                    cand.failure_reason = task.failure_reason
                    failed += 1
                self.db.commit()
            except Exception as exc:
                # 关键：异常可能发生在 create_and_submit_tasks 内部的 flush/commit；
                # session 已 failed，必须 rollback 才能继续写 cand
                self.db.rollback()
                cand = self.db.merge(cand)
                cand.lifecycle_status = "failed"
                cand.failure_reason = str(exc)
                self.db.commit()
                failed += 1

        return SubmitSummary(submitted=submitted, failed=failed, skipped=skipped)

    def list_candidates(
        self, *,
        lifecycle_status: str | None,
        matched_keyword_entry_id: int | None,
        duplicate_status: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[WhitelistCandidate], int]:
        """按 lifecycle / keyword / duplicate / 模糊搜索过滤候选，返回 (items, total) 元组。"""
        base = select(WhitelistCandidate)
        if lifecycle_status:
            base = base.where(WhitelistCandidate.lifecycle_status == lifecycle_status)
        if matched_keyword_entry_id:
            base = base.where(
                WhitelistCandidate.matched_keyword_entry_id == matched_keyword_entry_id
            )
        if duplicate_status:
            base = base.where(WhitelistCandidate.duplicate_status == duplicate_status)
        if search:
            pattern = f"%{search}%"
            base = base.where(or_(
                WhitelistCandidate.source_title.ilike(pattern),
                WhitelistCandidate.matched_keyword.ilike(pattern),
            ))

        total = self.db.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        items = list(self.db.scalars(
            base.order_by(
                WhitelistCandidate.match_score.desc(),
                WhitelistCandidate.id.desc(),
            )
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all())
        return items, total

    def dismiss(self, *, candidate_id: int, reason: str | None) -> WhitelistCandidate:
        """将候选标记为 dismissed。已提交的候选不允许丢弃。"""
        cand = self.db.get(WhitelistCandidate, candidate_id)
        if cand is None:
            raise LookupError("候选不存在")
        if cand.lifecycle_status == "submitted":
            raise ValueError("已提交的候选不能丢弃")
        cand.lifecycle_status = "dismissed"
        cand.dismissed_at = datetime.now(UTC)
        self.db.commit()
        return cand

    def restore(self, *, candidate_id: int) -> WhitelistCandidate:
        """将 dismissed 或 failed 的候选恢复为 pending。"""
        cand = self.db.get(WhitelistCandidate, candidate_id)
        if cand is None:
            raise LookupError("候选不存在")
        if cand.lifecycle_status == "submitted":
            raise ValueError("已提交的候选不能 restore")
        if cand.lifecycle_status not in {"dismissed", "failed"}:
            raise ValueError(f"当前状态 {cand.lifecycle_status} 不能 restore")
        cand.lifecycle_status = "pending"
        cand.dismissed_at = None
        cand.failure_reason = None
        self.db.commit()
        return cand


def _candidate_to_create_item(cand: WhitelistCandidate):
    """把 WhitelistCandidate 转成 MagnetTaskCreateItem。"""
    return MagnetTaskCreateItem(
        source_tid=cand.source_tid,
        source_title=cand.source_title,
        source_magnet=cand.source_magnet,
        source_detail_url=cand.source_detail_url,
        source_section=cand.source_section,
        matched_keyword=cand.matched_keyword,
        matched_alias=cand.matched_alias,
        match_score=cand.match_score,
        keyword_entry_id=cand.matched_keyword_entry_id,
        target_path=cand.target_path,
    )
