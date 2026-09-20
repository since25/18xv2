from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tree import NodeFile
from app.schemas.cleanup import (
    NoiseFileDeleteItemResponse,
    NoiseFileDeleteResponse,
    NoiseFilePreviewGroupResponse,
    NoiseFilePreviewItemResponse,
    NoiseFilePreviewResponse,
)
from app.services.client_115.client import Client115Error


class NoiseCleanupService:
    def __init__(self, db: Session, client=None):
        self.db = db
        self.client = client
        self.settings = get_settings()

    def preview_files(self, import_id: int, filenames: list[str], limit_per_filename: int = 50) -> NoiseFilePreviewResponse:
        cleaned_filenames = [item.strip() for item in filenames if item.strip()]
        query = (
            select(NodeFile)
            .where(NodeFile.import_id == import_id, NodeFile.raw_name.in_(cleaned_filenames))
            .order_by(NodeFile.raw_name.asc(), NodeFile.raw_path.asc())
        )
        nodes = list(self.db.scalars(query).all())

        groups: list[NoiseFilePreviewGroupResponse] = []
        total_selected_files = 0
        for filename in cleaned_filenames:
            matched = [node for node in nodes if node.raw_name == filename]
            total_selected_files += len(matched)
            groups.append(
                NoiseFilePreviewGroupResponse(
                    filename=filename,
                    count=len(matched),
                    items=[
                        NoiseFilePreviewItemResponse(
                            file_id=node.id,
                            filename=node.raw_name,
                            raw_path=node.raw_path,
                            parent_path=node.parent_path,
                        )
                        for node in matched[:limit_per_filename]
                    ],
                )
            )

        return NoiseFilePreviewResponse(import_id=import_id, total_selected_files=total_selected_files, groups=groups)

    def delete_files(self, import_id: int, file_ids: list[int], dry_run: bool = True, confirm_delete: bool = False) -> NoiseFileDeleteResponse:
        if len(file_ids) > self.settings.cleanup_max_delete_items:
            raise ValueError(
                f"Request has {len(file_ids)} items, exceeding CLEANUP_MAX_DELETE_ITEMS={self.settings.cleanup_max_delete_items}"
            )
        if not dry_run and not confirm_delete:
            raise ValueError("confirm_delete must be true for real deletion")

        query = (
            select(NodeFile)
            .where(NodeFile.import_id == import_id, NodeFile.id.in_(file_ids))
            .order_by(NodeFile.id.asc())
        )
        nodes = list(self.db.scalars(query).all())
        items: list[NoiseFileDeleteItemResponse] = []

        for node in nodes:
            try:
                self._ensure_allowed(node.raw_path, dry_run=dry_run)
                remote_file_id = self._resolve_path_to_id(node.raw_path)
                if dry_run:
                    items.append(
                        NoiseFileDeleteItemResponse(
                            file_id=node.id,
                            raw_path=node.raw_path,
                            remote_file_id=remote_file_id,
                            success=True,
                            status="dry_run",
                        )
                    )
                    continue

                self.client.delete_node(remote_file_id, dry_run=False)
                items.append(
                    NoiseFileDeleteItemResponse(
                        file_id=node.id,
                        raw_path=node.raw_path,
                        remote_file_id=remote_file_id,
                        success=True,
                        status="deleted",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                items.append(
                    NoiseFileDeleteItemResponse(
                        file_id=node.id,
                        raw_path=node.raw_path,
                        success=False,
                        status="blocked",
                        error_message=str(exc),
                    )
                )

        return NoiseFileDeleteResponse(
            import_id=import_id,
            dry_run=dry_run,
            total_requested=len(file_ids),
            total_processed=len(items),
            items=items,
        )

    @staticmethod
    def _normalize_for_prefix_check(path: str) -> str:
        cleaned = path.strip().strip("/")
        if not cleaned:
            return ""
        return "/".join(part for part in cleaned.split("/") if part)

    def _ensure_allowed(self, source_path: str, dry_run: bool) -> None:
        if dry_run:
            return
        # 与 executor 同一套边界规则：规范化后按路径段比较，
        # 避免 "/根目录/测试2/x" 被 "/根目录/测试" 前缀误放行。
        normalized_source = self._normalize_for_prefix_check(source_path)
        normalized_prefixes = [
            self._normalize_for_prefix_check(prefix) for prefix in self.settings.test_allowed_path_prefixes
        ]
        if "" in normalized_prefixes:
            return
        if not any(
            normalized_source == prefix or normalized_source.startswith(f"{prefix}/")
            for prefix in normalized_prefixes
        ):
            raise PermissionError(f"Real deletion is not allowed for path: {source_path}")

    @staticmethod
    def _path_parts(path: str) -> list[str]:
        cleaned = path.strip().strip("/")
        if not cleaned:
            return []
        parts = [part for part in cleaned.split("/") if part]
        if parts and parts[0] == "根目录":
            parts = parts[1:]
        return parts

    def _resolve_path_to_id(self, path: str) -> str:
        parts = self._path_parts(path)
        if not parts:
            raise Client115Error("Path is empty")
        current_id = "0"
        for part in parts:
            matched_id = self._find_child_id(current_id, part)
            if matched_id is None:
                raise Client115Error(f"Path not found: {path}")
            current_id = matched_id
        return current_id

    def _find_child_id(self, parent_id: str, name: str) -> str | None:
        """分页遍历子节点，目录超过一页（500 项）时也能找到目标。"""
        offset = 0
        limit = 500
        while True:
            listing = self.client.list_files(cid=parent_id, limit=limit, offset=offset, show_dir=1)
            data = listing.get("data", [])
            for item in data:
                if item.get("fn") == name:
                    return str(item.get("fid"))
            count = int(listing.get("count") or len(data) or 0)
            offset += len(data)
            if not data or offset >= count:
                return None
