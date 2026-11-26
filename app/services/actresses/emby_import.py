"""旧 Emby 黑白名单的一次性导入：把启用中的 emby_blacklist / emby_whitelist 关键词按人名设成女优状态。

关键词的规范名就是人名。关键词表只读，不改不删；女优名只写进女优自己的表。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import Actress
from app.models.keywords import KeywordEntry
from app.services.actresses.archive_service import ArchiveService, require_strm_roots
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses.names import build_name_index, normalize_actress_name

# 关键词类型 → 导入后的女优状态；按这个顺序写入
_STATUS_BY_TYPE = {"emby_blacklist": "blacklist", "emby_whitelist": "whitelist"}
_STATUS_LABELS = {"none": "未标", "blacklist": "黑名单", "whitelist": "白名单"}


@dataclass
class ImportRow:
    """导入结果的一行，对应一个关键词。"""

    name: str
    # blacklist / whitelist
    target_status: str
    # will_set（只列出时：将设置）/ set（已设置）/ unchanged（已是目标状态）/ conflict（不导入）
    result: str
    note: str | None = None


def _settle(person_rows: list[ImportRow], current_status: str, changed_result: str) -> None:
    """按这个人在档案里的当前状态填结果：未标的导入，已是目标状态的不变，已是相反状态的不覆盖、列为冲突。"""
    for row in person_rows:
        if current_status == "none":
            row.result = changed_result
        elif current_status == row.target_status:
            row.result = "unchanged"
        else:
            row.result, row.note = "conflict", f"档案里已是{_STATUS_LABELS[current_status]}"


def import_emby_lists(db: Session, *, apply: bool, strm_roots: list[str]) -> list[ImportRow]:
    """读启用中的 Emby 黑白名单关键词，按关键词顺序返回每条的导入结果。

    同一人（名字归一化后相同，或在档案里是同一个女优）同时在黑白两边 → conflict，不导入；
    档案里已是相反状态的不覆盖，也列为 conflict。
    apply=False 只列出，不写任何数据（也不建档）；apply=True 建档并以来源「导入」改状态，
    再重算待删清单。apply=True 且根目录没配置时抛 ActressError，不改任何数据。
    """
    if apply:
        require_strm_roots(strm_roots, "导入旧 Emby 黑白名单")

    entries = db.execute(
        select(KeywordEntry.canonical_name, KeywordEntry.keyword_type)
        .where(KeywordEntry.keyword_type.in_(_STATUS_BY_TYPE), KeywordEntry.status == "active")
        .order_by(KeywordEntry.keyword_type, KeywordEntry.canonical_name_normalized, KeywordEntry.id)
    ).all()
    index = build_name_index(db)

    rows: list[ImportRow] = []
    # 同一人的各条关键词：档案里已有的按女优 id 归组，没有的按归一化名归组
    people: dict[tuple[str, int | str], list[ImportRow]] = {}
    for name, keyword_type in entries:
        row = ImportRow(name=name, target_status=_STATUS_BY_TYPE[keyword_type], result="will_set")
        rows.append(row)
        normalized = normalize_actress_name(name)
        if not normalized:
            row.result, row.note = "conflict", "名字为空或只含空格和标点，不导入"
            continue
        actress_id = index.get(normalized)
        key = ("actress", actress_id) if actress_id is not None else ("name", normalized)
        people.setdefault(key, []).append(row)

    importable: dict[tuple[str, int | str], list[ImportRow]] = {}
    for key, person_rows in people.items():
        if len({row.target_status for row in person_rows}) > 1:
            for row in person_rows:
                row.result, row.note = "conflict", "同一人同时在 Emby 黑名单和白名单里，不导入"
        else:
            importable[key] = person_rows

    if not apply:
        for (kind, value), person_rows in importable.items():
            # 档案里还没有的人算未标
            current_status = db.get(Actress, value).status if kind == "actress" else "none"
            _settle(person_rows, current_status, "will_set")
        return rows

    archive = ArchiveService()
    groups = list(importable.values())
    actresses = archive.ensure_actresses(db, [person_rows[0].name for person_rows in groups])
    ids_by_status: dict[str, list[int]] = {status: [] for status in _STATUS_BY_TYPE.values()}
    for actress, person_rows in zip(actresses, groups):
        _settle(person_rows, actress.status, "set")
        # 只改未标的人；已是目标状态或相反状态的都不动
        if actress.status == "none":
            ids_by_status[person_rows[0].target_status].append(actress.id)
    for status, actress_ids in ids_by_status.items():
        if actress_ids:
            archive.set_status(db, actress_ids, status, source="import")
    CandidateService().reconcile(db, strm_roots=strm_roots, added_by="mark")
    return rows
