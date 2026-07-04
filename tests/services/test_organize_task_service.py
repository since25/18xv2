from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.keywords import KeywordEntry, KeywordHit
from app.models.tasks import OrganizeTask
from app.models.tree import TreeImport, TreeNode
from app.services.keywords.registry_service import normalize_keyword_text
from app.services.tasks.organize_task_service import OrganizeTaskService


def _seed_import(db: Session, hits: list[tuple[str, str]] | None = None) -> tuple[int, list[int]]:
    """返回 (import_id, keyword_ids)，hits 每项为 (canonical_name, raw_keyword)。"""
    hits = hits or [("作者A", "作者A"), ("作者B", "作者B"), ("作者C", "作者C"), ("作者D", "作者D")]
    ti = TreeImport(source_filename="test.txt", status="done")
    db.add(ti)
    db.flush()
    node = TreeNode(
        import_id=ti.id, raw_name="专辑X",
        normalized_name="专辑x", raw_path="/待整理/专辑X",
        depth=1, node_type="folder", fingerprint_hint="fp1",
    )
    db.add(node)
    entries: list[KeywordEntry] = []
    for canonical_name, _raw_keyword in hits:
        entry = KeywordEntry(
            canonical_name=canonical_name,
            canonical_name_normalized=normalize_keyword_text(canonical_name),
            keyword_type="whitelist",
            status="active",
        )
        entries.append(entry)
    db.add_all(entries)
    db.flush()
    for entry, (_canonical_name, raw_keyword) in zip(entries, hits, strict=True):
        db.add(
            KeywordHit(
                import_id=ti.id,
                raw_keyword=raw_keyword,
                normalized_keyword=normalize_keyword_text(raw_keyword),
                keyword_entry_id=entry.id,
                source_path="/待整理/专辑X",
                source_folder_name="专辑X",
                match_source="test",
            )
        )
    db.commit()
    return ti.id, [entry.id for entry in entries if entry.id is not None]


def test_list_ambiguous_conflicts_keeps_four_keyword_options(db_session: Session):
    import_id, keyword_ids = _seed_import(db_session)
    conflicts = OrganizeTaskService(db_session).list_ambiguous_conflicts(import_id=import_id)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.source_path == "/待整理/专辑X"
    # keyword_options 必须包含 id 和 name
    assert len(conflict.keyword_options) == 4
    option_ids = {opt.id for opt in conflict.keyword_options}
    assert set(keyword_ids) == option_ids
    option_names = {opt.name for opt in conflict.keyword_options}
    assert "作者A" in option_names
    assert "作者B" in option_names
    assert "作者C" in option_names
    assert "作者D" in option_names


def test_apply_ambiguous_resolutions_from_json(db_session: Session):
    import_id, keyword_ids = _seed_import(db_session)
    ka_id = keyword_ids[0]
    svc = OrganizeTaskService(db_session)
    tasks, replaced, skipped, errors = svc.apply_ambiguous_resolutions_from_json(
        import_id=import_id,
        resolutions=[{"source_path": "/待整理/专辑X", "keyword_entry_id": ka_id}],
        replace_existing=True,
    )
    assert errors == []
    assert len(tasks) == 1
    assert tasks[0].keyword_entry_id == ka_id
    assert tasks[0].source_path == "/待整理/专辑X"
    assert "作者A" in tasks[0].target_path


def test_generate_import_hits_prefers_specific_keyword_over_covered_alias(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("小桃shixiaotaone", "小桃"),
            ("狗爹和小桃", "狗爹和小桃"),
        ],
    )

    svc = OrganizeTaskService(db_session)
    result = svc.generate_tasks_from_import_hits(import_id=import_id, replace_existing=True)

    assert result.created_count == 1
    assert result.skipped_ambiguous_count == 0
    assert result.tasks[0].keyword_entry_id == keyword_ids[1]
    assert result.tasks[0].matched_canonical_name == "狗爹和小桃"
    assert "狗爹和小桃/专辑X" in result.tasks[0].target_path
    assert svc.list_ambiguous_conflicts(import_id=import_id) == []


def test_generate_import_hits_creates_combined_task_for_two_real_keywords(db_session: Session):
    import_id, _keyword_ids = _seed_import(
        db_session,
        hits=[
            ("小桃shixiaotaone", "小桃shixiaotaone"),
            ("狗爹和小桃", "狗爹和小桃"),
        ],
    )

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(
        import_id=import_id,
        replace_existing=True,
    )

    assert result.created_count == 1
    assert result.skipped_ambiguous_count == 0
    task = result.tasks[0]
    assert task.keyword_entry_id is None
    assert task.matched_canonical_name == "小桃shixiaotaone + 狗爹和小桃"
    assert "小桃shixiaotaone__狗爹和小桃/专辑X" in task.target_path


def test_generate_import_hits_creates_combined_task_for_three_real_keywords(db_session: Session):
    import_id, _keyword_ids = _seed_import(
        db_session,
        hits=[
            ("甜是甜甜老师的甜", "甜是甜甜老师的甜"),
            ("SAP", "SAP"),
            ("六花", "六花"),
        ],
    )

    svc = OrganizeTaskService(db_session)
    result = svc.generate_tasks_from_import_hits(import_id=import_id, replace_existing=True)

    assert result.created_count == 1
    assert result.skipped_ambiguous_count == 0
    task = result.tasks[0]
    assert task.keyword_entry_id is None
    assert task.matched_canonical_name == "SAP + 六花 + 甜是甜甜老师的甜"
    assert "SAP__六花__甜是甜甜老师的甜/专辑X" in task.target_path
    assert svc.list_ambiguous_conflicts(import_id=import_id) == []

def test_generate_import_hits_ignores_fallback_keyword_when_normal_keyword_matches(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("口巾SANG", "口巾SANG"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[1])
    assert fallback_entry is not None
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id == keyword_ids[0]
    assert task.matched_canonical_name == "口巾SANG"
    assert "口巾SANG/专辑X" in task.target_path
    assert "露脸_泄密_反差_电报" not in task.target_path


def test_generate_import_hits_uses_fallback_keyword_when_it_is_the_only_match(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[("露脸_泄密_反差_电报", "露脸_泄密_反差_电报")],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[0])
    assert fallback_entry is not None
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id == keyword_ids[0]
    assert task.matched_canonical_name == "露脸_泄密_反差_电报"
    assert "露脸_泄密_反差_电报/专辑X" in task.target_path


def test_generate_import_hits_combines_multiple_fallback_keywords_without_normal_match(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
            ("稀有主题合集", "稀有主题合集"),
        ],
    )
    for keyword_id in keyword_ids:
        entry = db_session.get(KeywordEntry, keyword_id)
        assert entry is not None
        entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id is None
    assert task.matched_canonical_name == "稀有主题合集 + 露脸_泄密_反差_电报"
    assert "稀有主题合集__露脸_泄密_反差_电报/专辑X" in task.target_path


def test_generate_import_hits_combines_normal_keywords_after_filtering_fallback(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("A", "A"),
            ("B", "B"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[2])
    assert fallback_entry is not None
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id is None
    assert task.matched_canonical_name == "A + B"
    assert "A__B/专辑X" in task.target_path
    assert "露脸_泄密_反差_电报" not in task.target_path


def test_list_ambiguous_conflicts_filters_fallback_keyword_when_normal_keywords_exist(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("A", "A"),
            ("B", "B"),
            ("C", "C"),
            ("D", "D"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[4])
    assert fallback_entry is not None
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    conflicts = OrganizeTaskService(db_session).list_ambiguous_conflicts(import_id=import_id)

    assert len(conflicts) == 1
    assert conflicts[0].keywords == ["A", "B", "C", "D"]
    assert "露脸_泄密_反差_电报" not in conflicts[0].keywords


def test_generate_keyword_hits_honors_explicit_fallback_selection(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("口巾SANG", "口巾SANG"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[1])
    assert fallback_entry is not None
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_keyword_hits(
        import_id=import_id,
        keyword_entry_id=keyword_ids[1],
        target_root="/自选整理",
    )

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id == keyword_ids[1]
    assert task.matched_canonical_name == "露脸_泄密_反差_电报"
    assert task.target_path == "/自选整理/专辑X"


def test_get_node_details_returns_cid_and_paths(db_session: Session):
    ti = TreeImport(source_filename="test2.txt", status="done")
    db_session.add(ti)
    db_session.flush()
    node = TreeNode(
        import_id=ti.id, raw_name="专辑Y", normalized_name="专辑y",
        raw_path="/待整理/专辑Y", depth=1, node_type="folder",
        fingerprint_hint="fp2", remote_cid="cid_abc",
    )
    db_session.add(node)
    db_session.flush()
    task = OrganizeTask(
        import_id=ti.id, node_id=node.id,
        source_path="/待整理/专辑Y", target_path="/根目录/已整理/专辑Y",
        status="pending",
    )
    db_session.add(task)
    db_session.commit()

    svc = OrganizeTaskService(db_session)
    details = svc.get_node_details(task_ids=[task.id])
    assert task.id in details
    item = details[task.id]
    assert item["raw_name"] == "专辑Y"
    assert item["raw_path"] == "/待整理/专辑Y"
    assert item["cid"] == "cid_abc"
