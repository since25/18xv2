from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GuardDecision:
    allowed: bool
    path: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class GuardDeleteResult:
    path: str
    entry_type: str
    status: str
    error_message: str | None = None


class PathGuard:
    def __init__(self, allowed_roots: list[str]) -> None:
        self.allowed_roots = [Path(item).expanduser().resolve() for item in allowed_roots]

    def classify(self, path: str) -> GuardDecision:
        resolved = Path(path).expanduser().resolve()
        for root in self.allowed_roots:
            if self._is_relative_to(resolved, root):
                return GuardDecision(True, str(resolved), None)
        return GuardDecision(False, str(resolved), "path_outside_allowed_roots")

    def delete_path(self, path: str, *, dry_run: bool) -> GuardDeleteResult:
        decision = self.classify(path)
        entry_type = self._entry_type(decision.path)
        if not decision.allowed:
            return GuardDeleteResult(decision.path, entry_type, "blocked", decision.reason)
        if entry_type == "dir":
            return GuardDeleteResult(decision.path, entry_type, "blocked", "directory_delete_not_allowed")
        if dry_run:
            return GuardDeleteResult(decision.path, entry_type, "dry_run")
        if entry_type == "missing":
            return GuardDeleteResult(decision.path, "missing", "not_found", "path_not_found")
        os.remove(decision.path)
        return GuardDeleteResult(decision.path, "file", "deleted")

    @staticmethod
    def _entry_type(path: str) -> str:
        if os.path.isdir(path):
            return "dir"
        if os.path.isfile(path):
            return "file"
        return "missing"

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
