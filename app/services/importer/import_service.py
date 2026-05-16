from __future__ import annotations

from sqlalchemy.orm import Session

from pathlib import Path

from app.models.tree import NodeFile, TreeImport, TreeNode
from app.services.classifier.keyword_classifier import normalize_folder_name
from app.services.importer.tree_parser import decode_tree_bytes, parse_tree_bytes


class TreeImportService:
    def __init__(self, db: Session):
        self.db = db

    def import_tree(self, filename: str, raw_bytes: bytes) -> TreeImport:
        parsed_nodes = parse_tree_bytes(raw_bytes)
        decoded_text = decode_tree_bytes(raw_bytes)
        tree_import = TreeImport(
            source_filename=filename,
            source_text=decoded_text,
            status="processing",
        )
        self.db.add(tree_import)
        self.db.flush()

        folder_path_to_id: dict[str, int] = {}
        db_nodes: list[TreeNode] = []
        db_files: list[NodeFile] = []
        seen_paths: set[str] = set()
        skipped_duplicates = 0
        for parsed in parsed_nodes:
            if parsed.raw_path in seen_paths:
                skipped_duplicates += 1
                continue
            seen_paths.add(parsed.raw_path)
            if parsed.node_type == "folder":
                node = TreeNode(
                    import_id=tree_import.id,
                    raw_name=parsed.name,
                    normalized_name=normalize_folder_name(parsed.name),
                    raw_path=parsed.raw_path,
                    parent_path=parsed.parent_path,
                    depth=parsed.depth,
                    node_type=parsed.node_type,
                    parent_id=folder_path_to_id.get(parsed.parent_path or ""),
                    fingerprint_hint=parsed.fingerprint_hint,
                )
                self.db.add(node)
                self.db.flush()
                folder_path_to_id[parsed.raw_path] = node.id
                db_nodes.append(node)
                continue

            node_file = NodeFile(
                import_id=tree_import.id,
                folder_node_id=folder_path_to_id.get(parsed.parent_path or ""),
                raw_name=parsed.name,
                normalized_name=parsed.name.strip(),
                raw_path=parsed.raw_path,
                parent_path=parsed.parent_path,
                depth=parsed.depth,
                file_ext=Path(parsed.name).suffix.lower() or None,
                fingerprint_hint=parsed.fingerprint_hint,
            )
            self.db.add(node_file)
            db_files.append(node_file)

        tree_import.status = "completed"
        tree_import.note = f"Imported {len(db_nodes)} folders and {len(db_files)} files"
        if skipped_duplicates:
            tree_import.note += f", skipped {skipped_duplicates} duplicate paths"
        self.db.commit()
        self.db.refresh(tree_import)
        return tree_import
