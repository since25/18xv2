from __future__ import annotations

from contextlib import nullcontext
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.actresses import Actress, ActressDeleteCandidate, ActressMark, JellyfinMediaActor
from app.models.jellyfin import JellyfinMediaItem
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.actresses.archive_service import ActressError, ArchiveService
from app.services.actresses.emby_import import ImportRow, import_emby_lists
from app.services.actresses.names import normalize_actress_name
from app.services.keywords.registry_service import normalize_keyword_text


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "actress_import_emby_lists.py"


def _keyword(db_session, name: str, keyword_type: str, *, status: str = "active") -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=normalize_keyword_text(name),
        keyword_type=keyword_type,
        status=status,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


def _actress(db_session, name: str, status: str = "none") -> Actress:
    actress = ArchiveService().ensure_actresses(db_session, [name])[0]
    if status != "none":
        ArchiveService().set_status(db_session, [actress.id], status, source="web")
    return actress


def _add_film(db_session, root: Path, number: str, actors: tuple[str, ...]) -> str:
    """插入一部单段片子（一个 115 STRM 条目和它的 NFO 演员行），返回番号目录。"""
    film_dir = root / actors[0] / number
    item = JellyfinMediaItem(source="strm_115", path=str(film_dir / f"{number}.strm"), active=True)
    db_session.add(item)
    db_session.flush()
    for position, name in enumerate(actors):
        db_session.add(
            JellyfinMediaActor(
                media_item_id=item.id, position=position, raw_name=name, name_normalized=normalize_actress_name(name)
            )
        )
    db_session.commit()
    return str(film_dir)


def _statuses(db_session) -> dict[str, str]:
    return {actress.canonical_name: actress.status for actress in db_session.scalars(select(Actress))}


def _marks(db_session) -> list[tuple[str, str, str, str]]:
    rows = db_session.execute(
        select(Actress.canonical_name, ActressMark.from_status, ActressMark.to_status, ActressMark.source)
        .join(Actress, Actress.id == ActressMark.actress_id)
        .order_by(ActressMark.id)
    )
    return [tuple(row) for row in rows]


def test_dry_run_lists_without_writing(db_session):
    _keyword(db_session, "甲", "emby_blacklist")
    _keyword(db_session, "乙", "emby_whitelist")
    _keyword(db_session, "丙", "emby_blacklist")
    _keyword(db_session, "丁", "emby_whitelist")
    # 停用的、其他类型的关键词不导入
    _keyword(db_session, "戊", "emby_blacklist", status="disabled")
    _keyword(db_session, "己", "whitelist")
    _actress(db_session, "丙", "blacklist")
    _actress(db_session, "丁", "blacklist")
    marks_before = _marks(db_session)

    # 只列出时不要求根目录
    rows = import_emby_lists(db_session, apply=False, strm_roots=[])

    assert rows == [
        ImportRow(name="丙", target_status="blacklist", result="unchanged", note=None),
        ImportRow(name="甲", target_status="blacklist", result="will_set", note=None),
        ImportRow(name="丁", target_status="whitelist", result="will_set", note="档案里原为黑名单"),
        ImportRow(name="乙", target_status="whitelist", result="will_set", note=None),
    ]
    # 不建档、不改状态、不写标记、不建清单
    assert _statuses(db_session) == {"丙": "blacklist", "丁": "blacklist"}
    assert _marks(db_session) == marks_before
    assert db_session.scalars(select(ActressDeleteCandidate)).all() == []


def test_apply_sets_status_with_import_source(db_session, tmp_path):
    root = tmp_path / "strm"
    film_dir = _add_film(db_session, root, "ABC-001", ("甲",))
    _add_film(db_session, root, "ABC-002", ("乙",))
    _keyword(db_session, "甲", "emby_blacklist")
    _keyword(db_session, "乙", "emby_whitelist")
    _keyword(db_session, "丙", "emby_whitelist")
    _actress(db_session, "乙", "whitelist")

    rows = import_emby_lists(db_session, apply=True, strm_roots=[str(root)])

    assert [(row.name, row.target_status, row.result) for row in rows] == [
        ("甲", "blacklist", "set"),
        ("丙", "whitelist", "set"),
        ("乙", "whitelist", "unchanged"),
    ]
    assert _statuses(db_session) == {"甲": "blacklist", "乙": "whitelist", "丙": "whitelist"}
    # 只有真改了状态的写标记，来源记为导入
    assert _marks(db_session) == [
        ("乙", "none", "whitelist", "web"),
        ("甲", "none", "blacklist", "import"),
        ("丙", "none", "whitelist", "import"),
    ]
    # 导入后重算待删清单，按改状态加入
    candidates = db_session.scalars(select(ActressDeleteCandidate)).all()
    assert [(row.film_dir, row.added_by) for row in candidates] == [(film_dir, "mark")]


def test_apply_without_roots_writes_nothing(db_session):
    _keyword(db_session, "甲", "emby_blacklist")

    with pytest.raises(ActressError):
        import_emby_lists(db_session, apply=True, strm_roots=["  "])

    assert _statuses(db_session) == {}
    assert _marks(db_session) == []


def test_conflicting_names_are_skipped(db_session, tmp_path):
    root = tmp_path / "strm"
    _add_film(db_session, root, "ABC-001", ("甲乙",))
    # 写法不同（空格）但归一化后是同一人，一边黑一边白
    _keyword(db_session, "甲 乙", "emby_blacklist")
    _keyword(db_session, "甲乙", "emby_whitelist")
    # 档案里丁是丙的别名，也算同一人
    bing = _actress(db_session, "丙")
    ArchiveService().add_alias(db_session, bing.id, "丁")
    _keyword(db_session, "丙", "emby_blacklist")
    _keyword(db_session, "丁", "emby_whitelist")
    # 名字只有标点，归一化后为空
    _keyword(db_session, "！！", "emby_blacklist")
    _keyword(db_session, "戊", "emby_blacklist")

    rows = import_emby_lists(db_session, apply=True, strm_roots=[str(root)])

    by_name = {row.name: row for row in rows}
    for name in ("甲 乙", "甲乙", "丙", "丁", "！！"):
        assert by_name[name].result == "conflict", name
        assert by_name[name].note
    assert "名字为空" in by_name["！！"].note
    assert by_name["戊"].result == "set"
    # 冲突的人不建档、不改状态，也不进待删清单
    assert _statuses(db_session) == {"丙": "none", "戊": "blacklist"}
    assert _marks(db_session) == [("戊", "none", "blacklist", "import")]
    assert db_session.scalars(select(ActressDeleteCandidate)).all() == []


def test_keyword_entries_untouched(db_session, tmp_path):
    _keyword(db_session, "甲", "emby_blacklist")
    white = _keyword(db_session, "乙", "emby_whitelist")
    db_session.add(KeywordAlias(keyword_entry_id=white.id, alias="丙", alias_normalized="丙"))
    db_session.commit()

    def snapshot():
        entries = db_session.execute(
            select(
                KeywordEntry.id,
                KeywordEntry.canonical_name,
                KeywordEntry.canonical_name_normalized,
                KeywordEntry.keyword_type,
                KeywordEntry.status,
                KeywordEntry.note,
                KeywordEntry.updated_at,
            ).order_by(KeywordEntry.id)
        ).all()
        aliases = db_session.execute(
            select(KeywordAlias.id, KeywordAlias.keyword_entry_id, KeywordAlias.alias).order_by(KeywordAlias.id)
        ).all()
        return [tuple(row) for row in entries], [tuple(row) for row in aliases]

    before = snapshot()
    import_emby_lists(db_session, apply=True, strm_roots=[str(tmp_path / "strm")])
    db_session.expire_all()

    assert snapshot() == before
    # 女优名只写进女优自己的表
    assert _statuses(db_session) == {"甲": "blacklist", "乙": "whitelist"}


@pytest.fixture
def cli(db_session, monkeypatch, tmp_path):
    """按文件路径加载命令行脚本，数据库会话换成测试库，配置换成测试值。"""
    spec = importlib.util.spec_from_file_location("actress_import_emby_lists_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(media_library_strm_roots=[str(tmp_path / "strm")])
    )
    monkeypatch.setattr(module, "actress_enabled", lambda _settings: True)
    monkeypatch.setattr("sys.argv", ["actress_import_emby_lists.py"])
    return module


def test_cli_lists_by_default_and_writes_with_apply(cli, db_session, monkeypatch, capsys):
    _keyword(db_session, "甲", "emby_blacklist")

    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "将设置 甲 → 黑名单" in output
    assert "未写入" in output
    assert _statuses(db_session) == {}

    monkeypatch.setattr("sys.argv", ["actress_import_emby_lists.py", "--apply"])
    assert cli.main() == 0
    assert "已设置 甲 → 黑名单" in capsys.readouterr().out
    assert _statuses(db_session) == {"甲": "blacklist"}


def test_cli_apply_refused_when_actress_disabled(cli, db_session, monkeypatch, capsys):
    _keyword(db_session, "甲", "emby_blacklist")
    monkeypatch.setattr(cli, "actress_enabled", lambda _settings: False)
    monkeypatch.setattr("sys.argv", ["actress_import_emby_lists.py", "--apply"])

    assert cli.main() == 1
    assert "未开启" in capsys.readouterr().out
    assert _statuses(db_session) == {}
