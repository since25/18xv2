from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class Decoded115Path:
    mount_name: str
    remote_path: str


@dataclass(frozen=True, slots=True)
class LocalStrmMatch:
    path: str
    path_role: str
    root_name: str
    root_path: str
    file_size: int | None
    inode: int | None
    link_count: int | None


def normalize_stream_url(value: str) -> str:
    cleaned = value.strip()
    parts = urlsplit(cleaned)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def decode_115_open_path(url: str) -> Decoded115Path:
    parts = urlsplit(normalize_stream_url(url))
    prefix = "/d/"
    if not parts.path.startswith(prefix):
        raise ValueError("stream URL is not an Alist /d/ path")
    remaining = parts.path[len(prefix) :]
    mount_name, _, encoded_path = remaining.partition("/")
    if mount_name != "115_OPEN":
        raise ValueError("stream URL is not under /d/115_OPEN")
    remote_path = "/" + unquote(encoded_path).lstrip("/")
    return Decoded115Path(mount_name=mount_name, remote_path=remote_path)


class StrmMappingService:
    def __init__(self, *, strm_roots: list[str], source_roots: list[str], organized_roots: list[str]) -> None:
        self.strm_roots = [Path(item).expanduser().resolve() for item in strm_roots]
        self.source_roots = [Path(item).expanduser().resolve() for item in source_roots]
        self.organized_roots = [Path(item).expanduser().resolve() for item in organized_roots]

    def scan_for_url(self, url: str) -> list[LocalStrmMatch]:
        target = normalize_stream_url(url)
        matches: list[LocalStrmMatch] = []
        for root in self.strm_roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.strm")):
                if self._read_first_line(path) != target:
                    continue
                stat = path.stat()
                matches.append(
                    LocalStrmMatch(
                        path=str(path),
                        path_role=self._classify_path(path),
                        root_name=self._root_name(path),
                        root_path=str(self._matching_root(path) or root),
                        file_size=stat.st_size,
                        inode=stat.st_ino,
                        link_count=stat.st_nlink,
                    )
                )
        role_order = {"source_strm": 0, "organized_strm": 1, "unknown_strm": 2}
        return sorted(matches, key=lambda item: (role_order.get(item.path_role, 99), item.path))

    @staticmethod
    def _read_first_line(path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as file:
                return normalize_stream_url(file.readline())
        except OSError:
            return ""

    def _classify_path(self, path: Path) -> str:
        resolved = path.resolve()
        if any(self._is_relative_to(resolved, root) for root in self.source_roots):
            return "source_strm"
        if any(self._is_relative_to(resolved, root) for root in self.organized_roots):
            return "organized_strm"
        return "unknown_strm"

    def _matching_root(self, path: Path) -> Path | None:
        resolved = path.resolve()
        for root in self.source_roots + self.organized_roots + self.strm_roots:
            if self._is_relative_to(resolved, root):
                return root
        return None

    def _root_name(self, path: Path) -> str:
        root = self._matching_root(path)
        return root.name if root is not None else path.parent.name

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
