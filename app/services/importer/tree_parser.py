from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re


ROOT_RE = re.compile(r"^\|[—-]{2,}(?P<name>.+?)\s*$")
LINE_RE = re.compile(r"^(?P<prefix>(?:\|\s)*)\|-(?P<name>.+?)\s*$")
FILE_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".txt",
    ".srt",
    ".ass",
    ".url",
    ".jpg",
    ".jpeg",
    ".png",
    ".nfo",
    ".html",
    ".mhtml",
    ".chm",
    ".iso",
}


@dataclass(slots=True)
class ParsedTreeNode:
    name: str
    parent_path: str | None
    depth: int
    raw_path: str
    node_type: str
    fingerprint_hint: str


def detect_encoding(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        return "utf-16"
    return "utf-8"


def decode_tree_bytes(raw_bytes: bytes) -> str:
    encoding = detect_encoding(raw_bytes)
    return raw_bytes.decode(encoding, errors="ignore")


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    return cleaned.strip()


def infer_node_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return "file" if suffix in FILE_EXTENSIONS else "folder"


def parse_tree_text(text: str) -> list[ParsedTreeNode]:
    nodes: list[ParsedTreeNode] = []
    stack: dict[int, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.replace("\x00", "").rstrip()
        if not line.strip():
            continue
        root_match = ROOT_RE.match(line)
        if root_match:
            name = normalize_name(root_match.group("name"))
            raw_path = name
            stack[0] = raw_path
            digest = hashlib.sha1(f"{raw_path}:folder".encode("utf-8")).hexdigest()[:16]
            nodes.append(
                ParsedTreeNode(
                    name=name,
                    parent_path=None,
                    depth=0,
                    raw_path=raw_path,
                    node_type="folder",
                    fingerprint_hint=digest,
                )
            )
            continue
        match = LINE_RE.match(line)
        if not match:
            continue

        name = normalize_name(match.group("name"))
        depth = line.count("|") - 1
        parent_path = stack.get(depth - 1) if depth > 0 else None
        raw_path = f"{parent_path}/{name}" if parent_path else name
        node_type = infer_node_type(name)
        stack[depth] = raw_path

        digest = hashlib.sha1(f"{raw_path}:{node_type}".encode("utf-8")).hexdigest()[:16]
        nodes.append(
            ParsedTreeNode(
                name=name,
                parent_path=parent_path,
                depth=depth,
                raw_path=raw_path,
                node_type=node_type,
                fingerprint_hint=digest,
            )
        )
    return nodes


def parse_tree_bytes(raw_bytes: bytes) -> list[ParsedTreeNode]:
    return parse_tree_text(decode_tree_bytes(raw_bytes))
