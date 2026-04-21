from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry, KeywordHit
from app.models.tree import TreeImport, TreeNode
from app.services.keywords.registry_service import normalize_keyword_text
from app.services.tasks.organize_task_service import OrganizeTaskService


def _seed_import(db: Session) -> tuple[int, int, int]:
    """返回 (import_id, keyword_id_a, keyword_id_b)"""
    ti = TreeImport(source_filename="test.txt", status="done")
    db.add(ti)
    db.flush()
    node = TreeNode(
        import_id=ti.id, raw_name="专辑X",
        normalized_name="专辑x", raw_path="/待整理/专辑X",
        depth=1, node_type="folder", fingerprint_hint="fp1",
    )
    db.add(node)
    ka = KeywordEntry(
        canonical_name="作者A",
        canonical_name_normalized=normalize_keyword_text("作者A"),
        keyword_type="whitelist",
        status="active"
    )
    kb = KeywordEntry(
        canonical_name="作者B",
        canonical_name_normalized=normalize_keyword_text("作者B"),
        keyword_type="whitelist",
        status="active"
    )
    db.add_all([ka, kb])
    db.flush()
    db.add_all([
        KeywordHit(import_id=ti.id, raw_keyword="作者A", normalized_keyword="作者a",
                   keyword_entry_id=ka.id, source_path="/待整理/专辑X", source_folder_name="专辑X",
                   match_source="test"),
        KeywordHit(import_id=ti.id, raw_keyword="作者B", normalized_keyword="作者b",
                   keyword_entry_id=kb.id, source_path="/待整理/专辑X", source_folder_name="专辑X",
                   match_source="test"),
    ])
    db.commit()
    return ti.id, ka.id, kb.id


def test_list_ambiguous_conflicts_returns_keyword_options(db_session: Session):
    import_id, ka_id, kb_id = _seed_import(db_session)
    conflicts = OrganizeTaskService(db_session).list_ambiguous_conflicts(import_id=import_id)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.source_path == "/待整理/专辑X"
    # keyword_options 必须包含 id 和 name
    assert len(conflict.keyword_options) == 2
    option_ids = {opt.id for opt in conflict.keyword_options}
    assert ka_id in option_ids
    assert kb_id in option_ids
    option_names = {opt.name for opt in conflict.keyword_options}
    assert "作者A" in option_names
    assert "作者B" in option_names
