from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.keywords import KeywordHit
from app.models.tree import NodeFile, TreeImport, TreeNode
from app.services.keywords.hit_rebuild_service import KeywordHitRebuildService
from app.services.keywords.registry_service import KeywordRegistryService


def test_rebuild_import_hits_matches_aliases_for_folders_and_files(db_session: Session):
    registry = KeywordRegistryService(db_session)
    entry = registry.create_entry(canonical_name="FENDI", keyword_type="whitelist", aliases=["FENDSON"])

    tree_import = TreeImport(source_filename="demo.txt", status="completed", note="test", source_type="file_upload")
    db_session.add(tree_import)
    db_session.flush()

    folder = TreeNode(
        import_id=tree_import.id,
        raw_name="根目录/FENDSON 合集",
        normalized_name="根目录/FENDSON 合集",
        raw_path="根目录/FENDSON 合集",
        parent_path="根目录",
        depth=1,
        node_type="folder",
        fingerprint_hint="folder-1",
    )
    db_session.add(folder)
    db_session.flush()

    file_row = NodeFile(
        import_id=tree_import.id,
        folder_node_id=folder.id,
        raw_name="FENDSON-001.mp4",
        normalized_name="FENDSON 001 mp4",
        raw_path="根目录/FENDSON 合集/FENDSON-001.mp4",
        parent_path="根目录/FENDSON 合集",
        depth=2,
        file_ext="mp4",
        fingerprint_hint="file-1",
    )
    db_session.add(file_row)
    db_session.commit()

    result = KeywordHitRebuildService(db_session).rebuild_import_hits(
        import_id=tree_import.id,
        include_folders=True,
        include_files=True,
        replace_existing=True,
    )

    hits = list(db_session.scalars(select(KeywordHit).order_by(KeywordHit.id.asc())).all())
    assert result.created_count == 2
    assert result.matched_keyword_count == 1
    assert len(hits) == 2
    assert all(hit.keyword_entry_id == entry.id for hit in hits)
    assert {hit.raw_keyword for hit in hits} == {"FENDSON"}


def test_rebuild_import_hits_replaces_existing_registry_rebuild_hits_only(db_session: Session):
    registry = KeywordRegistryService(db_session)
    entry = registry.create_entry(canonical_name="Alice", keyword_type="whitelist")

    tree_import = TreeImport(source_filename="demo.txt", status="completed", note="test", source_type="file_upload")
    db_session.add(tree_import)
    db_session.flush()

    folder = TreeNode(
        import_id=tree_import.id,
        raw_name="Alice",
        normalized_name="Alice",
        raw_path="根目录/Alice",
        parent_path="根目录",
        depth=1,
        node_type="folder",
        fingerprint_hint="folder-1",
    )
    db_session.add(folder)
    db_session.flush()

    db_session.add(
        KeywordHit(
            raw_keyword="Alice",
            normalized_keyword="Alice",
            keyword_entry_id=entry.id,
            canonical_name_snapshot=entry.canonical_name,
            source_path="根目录/Alice",
            source_folder_name="Alice",
            import_id=tree_import.id,
            match_rule="manual",
            match_source="manual",
        )
    )
    db_session.add(
        KeywordHit(
            raw_keyword="Alice",
            normalized_keyword="Alice",
            keyword_entry_id=entry.id,
            canonical_name_snapshot=entry.canonical_name,
            source_path="根目录/Alice",
            source_folder_name="Alice",
            import_id=tree_import.id,
            match_rule="folder:contains:Alice",
            match_source=KeywordHitRebuildService.MATCH_SOURCE,
        )
    )
    db_session.commit()

    result = KeywordHitRebuildService(db_session).rebuild_import_hits(
        import_id=tree_import.id,
        include_folders=True,
        include_files=False,
        replace_existing=True,
    )

    hits = list(db_session.scalars(select(KeywordHit).order_by(KeywordHit.id.asc())).all())
    assert result.deleted_count == 1
    assert len(hits) == 2
    assert sorted(hit.match_source for hit in hits) == ["manual", KeywordHitRebuildService.MATCH_SOURCE]


def test_rebuild_import_hits_does_not_match_parent_path_on_child_nodes(db_session: Session):
    registry = KeywordRegistryService(db_session)
    entry = registry.create_entry(canonical_name="cc", keyword_type="whitelist")

    tree_import = TreeImport(source_filename="demo.txt", status="completed", note="test", source_type="file_upload")
    db_session.add(tree_import)
    db_session.flush()

    parent = TreeNode(
        import_id=tree_import.id,
        raw_name="cc",
        normalized_name="cc",
        raw_path="/a/b/cc",
        parent_path="/a/b",
        depth=3,
        node_type="folder",
        fingerprint_hint="folder-parent",
    )
    db_session.add(parent)
    db_session.flush()

    for index in (1, 2):
        db_session.add(
            TreeNode(
                import_id=tree_import.id,
                raw_name=f"d{index}",
                normalized_name=f"d{index}",
                raw_path=f"/a/b/cc/d{index}",
                parent_path="/a/b/cc",
                depth=4,
                node_type="folder",
                parent_id=parent.id,
                fingerprint_hint=f"folder-child-{index}",
            )
        )
    db_session.commit()

    result = KeywordHitRebuildService(db_session).rebuild_import_hits(
        import_id=tree_import.id,
        include_folders=True,
        include_files=False,
        replace_existing=True,
    )

    hits = list(db_session.scalars(select(KeywordHit).order_by(KeywordHit.id.asc())).all())
    assert result.created_count == 1
    assert len(hits) == 1
    assert hits[0].source_path == "/a/b/cc"
    assert entry.id is not None
