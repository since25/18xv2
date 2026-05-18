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
        # 不在此处 flush，让 tree_import 与 folder_nodes 在同一次 flush 中写入

        seen_paths: set[str] = set()
        skipped_duplicates = 0
        folder_parsed = []
        file_parsed = []
        for parsed in parsed_nodes:
            if parsed.raw_path in seen_paths:
                skipped_duplicates += 1
                continue
            seen_paths.add(parsed.raw_path)
            if parsed.node_type == "folder":
                folder_parsed.append(parsed)
            else:
                file_parsed.append(parsed)

        # 阶段 1：批量插入全部 folder 节点（parent_id 暂为 None），一次 flush 拿到所有 id
        # 使用 tree_import 关联对象而非 import_id，避免在 flush 之前读取未赋值的 id
        folder_nodes = [
            TreeNode(
                tree_import=tree_import,
                raw_name=p.name,
                normalized_name=normalize_folder_name(p.name),
                raw_path=p.raw_path,
                parent_path=p.parent_path,
                depth=p.depth,
                node_type="folder",
                parent_id=None,
                fingerprint_hint=p.fingerprint_hint,
            )
            for p in folder_parsed
        ]
        self.db.add_all(folder_nodes)
        self.db.flush()  # 唯一一次显式 flush，同时拿到 tree_import.id 和所有 folder node id

        # 阶段 2：回填 parent_id（利用已有 id）
        path_to_id: dict[str, int] = {n.raw_path: n.id for n in folder_nodes}
        for node in folder_nodes:
            node.parent_id = path_to_id.get(node.parent_path or "")

        # 阶段 3：批量插入 file 节点，统一 commit
        file_nodes = [
            NodeFile(
                tree_import=tree_import,
                folder_node_id=path_to_id.get(p.parent_path or ""),
                raw_name=p.name,
                normalized_name=p.name.strip(),
                raw_path=p.raw_path,
                parent_path=p.parent_path,
                depth=p.depth,
                file_ext=Path(p.name).suffix.lower() or None,
                fingerprint_hint=p.fingerprint_hint,
            )
            for p in file_parsed
        ]
        self.db.add_all(file_nodes)

        tree_import.status = "completed"
        tree_import.note = f"folders={len(folder_nodes)}, files={len(file_nodes)}"
        if skipped_duplicates:
            tree_import.note += f", skipped={skipped_duplicates}"
        self.db.commit()
        self.db.refresh(tree_import)
        return tree_import
