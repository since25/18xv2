"""
tree_parser 单元测试。覆盖根节点解析、嵌套节点、文件节点和边界情况。
根节点格式：|———— 名称（需要 2+ 个 em-dash），子节点格式：|- 名称。
"""
from __future__ import annotations

from app.services.importer.tree_parser import parse_tree_text, infer_node_type, normalize_name

# 根节点必须用 2+ 个 em-dash，如 "|————"
_ROOT = "\u2014\u2014\u2014\u2014"  # 4 个 em-dash


class TestParseTreeText:
    def test_empty_text_returns_empty(self):
        assert parse_tree_text("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_tree_text("   \n\n  ") == []

    def test_root_node_parsed(self):
        text = f"|{_ROOT} 电影\n"
        nodes = parse_tree_text(text)
        assert len(nodes) == 1
        assert nodes[0].name == "电影"
        assert nodes[0].depth == 0
        assert nodes[0].parent_path is None
        assert nodes[0].node_type == "folder"

    def test_nested_folder_parsed(self):
        # `|- 子目录` depth=0，`| |- 孙目录` depth=1
        text = f"|{_ROOT} 根\n|- 子目录\n| |- 孙目录\n"
        nodes = parse_tree_text(text)
        assert len(nodes) == 3
        child = nodes[1]
        assert child.name == "子目录"
        assert child.depth == 0
        grandchild = nodes[2]
        assert grandchild.name == "孙目录"
        assert grandchild.depth == 1
        assert grandchild.parent_path == "子目录"
        assert grandchild.raw_path == "子目录/孙目录"

    def test_file_node_inferred(self):
        text = f"|{_ROOT} 根\n|- 动作\n| |- movie.mp4\n"
        nodes = parse_tree_text(text)
        file_node = nodes[-1]
        assert file_node.name == "movie.mp4"
        assert file_node.node_type == "file"

    def test_fingerprint_is_16_chars(self):
        nodes = parse_tree_text(f"|{_ROOT} 根\n")
        assert len(nodes[0].fingerprint_hint) == 16

    def test_deeply_nested(self):
        # `| | | |- D` → count(|)=4, depth=3，raw_path="A/B/C/D"
        text = f"|{_ROOT} 根\n|- A\n| |- B\n| | |- C\n| | | |- D\n"
        nodes = parse_tree_text(text)
        last = nodes[-1]
        assert last.name == "D"
        assert last.depth == 3
        assert last.raw_path == "A/B/C/D"

    def test_null_bytes_stripped(self):
        text = f"|{_ROOT} \x00电影\x00\n"
        nodes = parse_tree_text(text)
        assert nodes[0].name == "电影"


class TestInferNodeType:
    def test_video_extensions_are_files(self):
        for ext in [".mp4", ".mkv", ".avi", ".mov"]:
            assert infer_node_type(f"sample{ext}") == "file"

    def test_unknown_extension_is_folder(self):
        assert infer_node_type("SomeSeries") == "folder"
        assert infer_node_type("2024年新片") == "folder"


class TestNormalizeName:
    def test_strips_whitespace(self):
        assert normalize_name("  abc  ") == "abc"

    def test_collapses_internal_spaces(self):
        assert normalize_name("a  b   c") == "a b c"
