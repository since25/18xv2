"""
ConflictDetector 单元测试。覆盖 noop、duplicate_target、invalid_target、none 四种情况。
"""
from __future__ import annotations

from collections import Counter

from app.services.planner.conflict_detector import ConflictDetector


class TestConflictDetector:
    def setup_method(self):
        self.detector = ConflictDetector()

    def test_same_paths_returns_noop(self):
        status, reason = self.detector.detect("/电影/A", "/电影/A", Counter({"/电影/A": 1}))
        assert status == "noop"

    def test_empty_target_returns_invalid(self):
        status, _ = self.detector.detect("/电影/A", "  ", Counter())
        assert status == "invalid_target"

    def test_duplicate_target_detected(self):
        # 两个节点都映射到同一 target path
        counts = Counter({"/目标/X": 2})
        status, _ = self.detector.detect("/电影/A", "/目标/X", counts)
        assert status == "duplicate_target"

    def test_valid_unique_path_returns_none(self):
        counts = Counter({"/目标/新路径": 1})
        status, reason = self.detector.detect("/电影/旧名", "/目标/新路径", counts)
        assert status == "none"
        assert reason is None

    def test_whitespace_target_is_invalid(self):
        status, _ = self.detector.detect("/A", "", Counter())
        assert status == "invalid_target"
