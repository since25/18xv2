from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from app.schemas.local_tree_export import LocalTreeExportFileResponse, LocalTreeExportResponse


EXPORT_DIR = Path("generated_trees")


@dataclass(slots=True)
class _TreeBuildResult:
    text: str
    folder_count: int
    file_count: int
    line_count: int


class LocalTreeExportService:
    def export(
        self,
        *,
        root_path: str,
        root_name: str | None = None,
        output_name: str | None = None,
        include_files: bool = True,
    ) -> LocalTreeExportResponse:
        resolved_root = self._resolve_root(root_path)
        export_root = self._export_dir()
        actual_root_name = (root_name or resolved_root.name or "根目录").strip()
        build = self._build_tree_text(resolved_root, actual_root_name, include_files=include_files)
        filename = self._build_output_filename(resolved_root, output_name)
        output_path = export_root / filename
        output_path.write_text(build.text, encoding="utf-8")
        return LocalTreeExportResponse(
            root_path=str(resolved_root),
            root_name=actual_root_name,
            output_path=str(output_path.resolve()),
            output_filename=filename,
            folder_count=build.folder_count,
            file_count=build.file_count,
            line_count=build.line_count,
        )

    def list_exports(self) -> list[LocalTreeExportFileResponse]:
        export_root = self._export_dir()
        items: list[LocalTreeExportFileResponse] = []
        for file_path in sorted(export_root.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = file_path.stat()
            items.append(
                LocalTreeExportFileResponse(
                    filename=file_path.name,
                    path=str(file_path.resolve()),
                    size_bytes=stat.st_size,
                    updated_at=stat.st_mtime,
                )
            )
        return items

    def _build_tree_text(self, root: Path, root_name: str, *, include_files: bool) -> _TreeBuildResult:
        lines = [f"|——{root_name}"]
        folder_count = 1
        file_count = 0

        def walk(current: Path, depth: int) -> None:
            nonlocal folder_count, file_count
            entries = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.casefold()))
            for entry in entries:
                prefix = "| " * depth
                lines.append(f"{prefix}|-{entry.name}")
                if entry.is_dir():
                    folder_count += 1
                    walk(entry, depth + 1)
                elif include_files:
                    file_count += 1
                else:
                    lines.pop()

        walk(root, 1)
        text = "\n".join(lines) + "\n"
        return _TreeBuildResult(
            text=text,
            folder_count=folder_count,
            file_count=file_count,
            line_count=len(lines),
        )

    @staticmethod
    def _resolve_root(root_path: str) -> Path:
        candidate = Path(root_path).expanduser().resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"root_path does not exist or is not a directory: {root_path}")
        return candidate

    @staticmethod
    def _sanitize_stem(raw: str) -> str:
        cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", raw.strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "目录树"

    def _build_output_filename(self, root: Path, output_name: str | None) -> str:
        if output_name and output_name.strip():
            stem = self._sanitize_stem(Path(output_name).stem or output_name)
        else:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            stem = f"{self._sanitize_stem(root.name)}_{timestamp}_目录树"
        return f"{stem}.txt"

    @staticmethod
    def _export_dir() -> Path:
        export_root = EXPORT_DIR
        export_root.mkdir(parents=True, exist_ok=True)
        return export_root
