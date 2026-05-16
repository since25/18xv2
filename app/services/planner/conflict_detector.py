from __future__ import annotations

from collections import Counter


class ConflictDetector:
    def detect(self, source_path: str, target_path: str, target_counts: Counter[str]) -> tuple[str, str | None]:
        if not target_path.strip():
            return "invalid_target", "Target path is empty"
        if source_path == target_path:
            return "noop", "Source and target paths are identical"
        if target_counts[target_path] > 1:
            return "duplicate_target", "Multiple nodes mapped to the same target path"
        return "none", None
