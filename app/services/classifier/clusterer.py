from __future__ import annotations

from collections import defaultdict

from app.models.tree import TreeNode
from app.services.classifier.keyword_classifier import normalize_folder_name


def cluster_nodes(nodes: list[TreeNode]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for node in nodes:
        grouped[normalize_folder_name(node.raw_name)].append(node.id)
    return dict(grouped)
