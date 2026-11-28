from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta
import importlib.util
import json
import logging
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services.nfo_retranslate import runs as runs_module
from app.services.nfo_retranslate.nfo_file import plot_body, read_nfo, sha256_text
from app.services.nfo_retranslate.runs import LedgerEntry, RunDir, TranslationRecord, append_ledger
from app.services.nfo_retranslate.translator import TranslateError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "nfo_retranslate.py"
_FIXTURE = Path(__file__).parent / "fixtures" / "sample.nfo"
_API_BASE = "https://example.invalid/v1"
_API_KEY = "sk-test-secret-key"
_MODEL = "qwen38"
_TITLE_OUT = "订婚后的我被两位上司低语诱惑"
_PLOT_OUT = "刚订婚的我被两位上司在耳边低语诱惑。\n严厉的前辈和温柔的前辈一左一右地夹着我。"
_CREATE_TASK = (
    "CREATE TABLE task (id INTEGER PRIMARY KEY, primary_task_id INTEGER, "
    "target_path TEXT, metadata_provider_info TEXT)"
)
# 标题、简介都来自日文站
_JP = {"Title": "javbus", "Outline": "dmm"}
# 标题来自中文站，只翻简介
_CN_TITLE = {"Title": "airav_io", "Outline": "dmm"}


class FakeTranslator:
    """假的翻译客户端：按字段回固定译文，记下每次收到的用户消息。"""

    calls: list[str] = []
    outputs: dict[str, object] = {}
    init_kwargs: dict[str, object] = {}

    def __init__(self, base_url, api_key, model, **kwargs):
        self.model = model
        FakeTranslator.init_kwargs = kwargs

    def translate(self, user_message: str) -> str:
        FakeTranslator.calls.append(user_message)
        field = "title" if user_message.startswith("类型：标题") else "plot"
        out = FakeTranslator.outputs.get(field, _TITLE_OUT if field == "title" else _PLOT_OUT)
        if callable(out) and not isinstance(out, BaseException):
            out = out(user_message)
        if isinstance(out, BaseException):
            raise out
        return out


class Env:
    """一次测试的环境：NFO 根目录、MDC 库、对照表、配置、运行记录根目录。"""

    def __init__(self, tmp_path: Path, cli) -> None:
        self.tmp = tmp_path
        self.cli = cli
        self.root = tmp_path / "302porn_tv1"
        self.root.mkdir()
        self.base = str(tmp_path / "nfo_retranslate")
        self.db = tmp_path / "mdc_ng.db"
        self.tasks: list[tuple] = []
        self.name_map = tmp_path / "mapping_actor.xml"
        self.name_map.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<actor>\n'
            '  <a zh_cn="森泽佳奈" zh_tw="森澤佳奈" jp="森沢かな" keyword=",森沢かな,"/>\n</actor>\n',
            encoding="utf-8",
        )
        self.settings = SimpleNamespace(
            nfo_translate_api_base=_API_BASE,
            nfo_translate_api_key=_API_KEY,
            nfo_translate_model=_MODEL,
            nfo_translate_root=str(self.root),
            nfo_translate_mdc_db=str(self.db),
            nfo_translate_name_map=str(self.name_map),
            media_library_strm_roots=[str(tmp_path / "local"), str(tmp_path / "strm" / "302porn_tv1")],
            jellyfin_base_url="http://jellyfin.invalid",
            jellyfin_api_key="jellyfin-test-key",
            jellyfin_timeout_seconds=15,
            jellyfin_page_size=500,
        )

    def nfo(self, rel: str, num: str, info: dict | None) -> str:
        """照样例写一个 NFO（番号换成 num）；info 不为 None 时登记一个 MDC 任务。返回绝对路径。"""
        text = _FIXTURE.read_bytes().decode("utf-8").replace("MIAA-759", num)
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        if info is not None:
            target = "/302video/302porn_tv1/" + os.path.splitext(rel)[0] + ".mp4"
            self.tasks.append((len(self.tasks) + 1, None, target, json.dumps(info)))
        return str(path)

    def build_db(self) -> None:
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(_CREATE_TASK)
            conn.executemany("INSERT INTO task VALUES (?, ?, ?, ?)", self.tasks)
            conn.commit()
        finally:
            conn.close()

    def run(self, *argv: str) -> int:
        if not self.db.exists():
            self.build_db()
        return self.cli.main(list(argv))

    def only_run(self) -> RunDir:
        ids = sorted(name for name in os.listdir(self.base) if os.path.isdir(os.path.join(self.base, name)))
        return RunDir.open(self.base, ids[-1])

    def runs(self) -> list[RunDir]:
        ids = sorted(name for name in os.listdir(self.base) if os.path.isdir(os.path.join(self.base, name)))
        return [RunDir.open(self.base, run_id) for run_id in ids]


@pytest.fixture
def cli(monkeypatch):
    """按文件路径加载命令行脚本。"""
    spec = importlib.util.spec_from_file_location("nfo_retranslate_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # 脚本里有 dataclass，加载时模块要先登记在 sys.modules
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    FakeTranslator.calls = []
    FakeTranslator.outputs = {}
    monkeypatch.setattr(module, "TranslatorClient", FakeTranslator)
    return module


@pytest.fixture
def env(tmp_path, cli, monkeypatch):
    e = Env(tmp_path, cli)
    monkeypatch.setattr(cli, "BASE_DIR", e.base)
    monkeypatch.setattr(cli, "get_settings", lambda: e.settings)

    # 运行编号按秒取，同一测试里连跑几次要错开
    class Clock:
        current = datetime(2026, 11, 27, 10, 0, 0)

        @classmethod
        def now(cls):
            cls.current += timedelta(seconds=1)
            return cls.current

    monkeypatch.setattr(runs_module, "datetime", Clock)
    return e


def _two_groups(env: Env) -> tuple[list[str], str]:
    """一组两段（标题、简介都要翻），一组一个 NFO（只翻简介）。"""
    a1 = env.nfo("甲/ABC-001/ABC-001-cd1.nfo", "ABC-001", _JP)
    a2 = env.nfo("甲/ABC-001/ABC-001-cd2.nfo", "ABC-001", _JP)
    b = env.nfo("乙/DEF-002/DEF-002.nfo", "DEF-002", _CN_TITLE)
    return [a1, a2], b


def _snapshot(paths: list[str]) -> dict[str, bytes]:
    return {path: Path(path).read_bytes() for path in paths}


def test_translate_requires_config(env, capsys):
    env.settings.nfo_translate_api_key = None

    assert env.run("translate") == 1

    assert "NFO_TRANSLATE_API_KEY" in capsys.readouterr().out
    assert not os.path.exists(env.base)


def test_translate_stops_on_many_orphans(env, capsys):
    for i in range(101):
        env.nfo(f"旧/OLD-{i:03d}/OLD-{i:03d}.nfo", f"OLD-{i:03d}", None)

    assert env.run("translate") == 1
    assert "旧版残留" in capsys.readouterr().out
    assert FakeTranslator.calls == []

    assert env.run("translate", "--force", "--limit", "1") == 0
    assert len(FakeTranslator.calls) == 1


def test_translate_end_to_end_with_fake_model(env, capsys):
    group_a, b = _two_groups(env)
    before = _snapshot([*group_a, b])

    assert env.run("translate") == 0

    run = env.only_run()
    records = run.load_translations()
    assert sorted((rec.num, rec.field) for rec in records) == [
        ("ABC-001", "plot"),
        ("ABC-001", "title"),
        ("DEF-002", "plot"),
    ]
    by_key = {(rec.num, rec.field): rec for rec in records}
    title = by_key[("ABC-001", "title")]
    assert title.new_text == _TITLE_OUT and title.error is None
    assert title.targets == {path: sha256_text(before[path].decode("utf-8")) for path in group_a}
    assert title.source_text == "婚約したばかりの僕に耳元で囁いてくるW上司 森沢かな"
    assert title.old_text == "订婚后的我被两位上司在耳边低语诱惑"
    plot = by_key[("DEF-002", "plot")]
    assert plot.targets == {b: sha256_text(before[b].decode("utf-8"))}
    assert plot.new_text == _PLOT_OUT
    # 简介原文先过 plot_body：<br> 换成换行，旧标记去掉
    doc = read_nfo(b)
    assert plot.source_text == plot_body(doc.original_plot)
    assert plot.old_text == "刚订婚的我被两位上司用耳语挑逗。\n严厉的前辈和温柔的前辈一左一右。"
    plot_messages = [msg for msg in FakeTranslator.calls if msg.startswith("类型：简介")]
    assert len(plot_messages) == 2
    assert all("<br>" not in msg and "提供翻译" not in msg for msg in plot_messages)
    # 演员对照：本片演员的日文写法
    assert "森沢かな" in plot_messages[0]

    assert os.path.isfile(run.report_path)
    assert _snapshot([*group_a, b]) == before

    meta = json.loads(Path(run.path, "run.json").read_text(encoding="utf-8"))
    assert meta["model"] == _MODEL and meta["run_id"] == run.run_id

    out = capsys.readouterr().out
    assert run.run_id in out
    assert os.path.join(env.base, run.run_id, "report.html") in out
    # 接口地址和密钥不进任何输出
    texts = [out]
    for name in ("translations.jsonl", "run.json", "report.html"):
        texts.append(Path(run.path, name).read_text(encoding="utf-8"))
    for text in texts:
        assert _API_BASE not in text and "example.invalid" not in text
        assert _API_KEY not in text


def test_translate_quiets_httpx_logging(env):
    _two_groups(env)
    logging.getLogger("httpx").setLevel(logging.INFO)

    assert env.run("translate") == 0

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_failed_outputs_recorded_with_reason(env):
    _two_groups(env)
    FakeTranslator.outputs = {"title": "抱歉，我无法翻译", "plot": TranslateError("翻译接口请求失败（HTTP 500，已尝试 4 次）")}

    assert env.run("translate") == 0

    records = env.only_run().load_translations()
    assert len(records) == 3
    for rec in records:
        assert rec.new_text is None
        assert rec.error
    title = next(rec for rec in records if rec.field == "title")
    assert title.error == "译文是拒绝话术"
    assert {rec.error for rec in records if rec.field == "plot"} == {"翻译接口请求失败（HTTP 500，已尝试 4 次）"}


def test_translate_fields_option(env):
    _two_groups(env)

    assert env.run("translate", "--fields", "title") == 0

    assert [rec.field for rec in env.only_run().load_translations()] == ["title"]


def test_translate_skips_ledger_unless_redo(env):
    group_a, _ = _two_groups(env)
    sha = sha256_text(Path(group_a[0]).read_bytes().decode("utf-8"))
    os.makedirs(env.base)
    append_ledger(env.base, group_a[0], LedgerEntry(sha256_after=sha, fields=frozenset({"title", "plot"}), model="x"))

    assert env.run("translate") == 0
    first = env.runs()[-1].load_translations()
    assert all(group_a[0] not in rec.targets for rec in first)
    assert any(group_a[1] in rec.targets for rec in first)

    assert env.run("translate", "--redo") == 0
    second = env.runs()[-1].load_translations()
    assert any(group_a[0] in rec.targets for rec in second)


def test_resume_skips_done_groups(env, cli):
    group_a, b = _two_groups(env)
    env.build_db()
    run = RunDir.create(env.base)
    cli.write_run_meta(run, {"model": _MODEL, "run_id": run.run_id, "args": {}})
    # 乙组已翻完；甲组只记下了标题（末行断掉，简介丢了）
    for path, num, field in ((b, "DEF-002", "plot"), (group_a[0], "ABC-001", "title")):
        key = next(rec.key for rec in _groups(env) if rec.docs[0].num == num)
        run.append_translation(
            TranslationRecord(
                group_key=key,
                field=field,
                num=num,
                actors=[],
                source_text="原文",
                old_text="旧",
                new_text="新",
                error=None,
                targets={path: "x"},
            )
        )

    assert env.run("translate", "--resume", run.run_id) == 0

    # 只补翻甲组的简介
    assert len(FakeTranslator.calls) == 1
    assert FakeTranslator.calls[0].startswith("类型：简介")
    assert "番号：ABC-001" in FakeTranslator.calls[0]
    assert len(env.runs()) == 1
    assert os.path.isfile(run.report_path)


def test_resume_rejects_changed_model(env, cli, capsys):
    _two_groups(env)
    env.build_db()
    run = RunDir.create(env.base)
    cli.write_run_meta(run, {"model": "other-model", "run_id": run.run_id, "args": {}})

    assert env.run("translate", "--resume", run.run_id) == 1

    out = capsys.readouterr().out
    assert "other-model" in out and _MODEL in out
    assert FakeTranslator.calls == []


def test_resume_without_meta_fails(env, capsys):
    _two_groups(env)
    env.build_db()
    run = RunDir.create(env.base)

    assert env.run("translate", "--resume", run.run_id) == 1
    assert "run.json" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["apply", "restore"])
def test_bad_or_missing_run_id(env, command, capsys):
    assert env.run(command, "--run", "2026-11-27") == 1
    assert "运行编号" in capsys.readouterr().out
    assert env.run(command, "--run", "20991231-235959", "--no-refresh") == 1
    assert "运行编号" in capsys.readouterr().out
    assert env.run("translate", "--resume", "abc") == 1
    assert FakeTranslator.calls == []


def test_path_prefix_must_exist(env, capsys):
    _two_groups(env)

    assert env.run("translate", "--path-prefix", "不存在的演员") == 1
    assert "不存在的演员" in capsys.readouterr().out
    assert FakeTranslator.calls == []


def test_path_prefix_and_engine_filter(env):
    group_a, b = _two_groups(env)
    # 乙组简介标记改成 Google
    Path(b).write_bytes(Path(b).read_bytes().replace("由 OpenAI 提供翻译".encode(), "由 Google 提供翻译".encode()))

    assert env.run("translate", "--path-prefix", "甲") == 0
    assert {rec.num for rec in env.runs()[-1].load_translations()} == {"ABC-001"}

    assert env.run("translate", "--engine", "Google") == 0
    assert {rec.num for rec in env.runs()[-1].load_translations()} == {"DEF-002"}


def test_sample_and_limit(env, cli, monkeypatch):
    for i in range(5):
        env.nfo(f"丙/GRP-00{i}/GRP-00{i}.nfo", f"GRP-00{i}", _CN_TITLE)

    assert env.run("translate", "--limit", "2") == 0
    assert sorted(rec.num for rec in env.runs()[-1].load_translations()) == ["GRP-000", "GRP-001"]

    picked = []
    for _ in range(2):
        monkeypatch.setattr(cli, "RANDOM", random.Random(0))
        assert env.run("translate", "--sample", "2") == 0
        picked.append(sorted(rec.num for rec in env.runs()[-1].load_translations()))
    assert len(picked[0]) == 2 and len(set(picked[0])) == 2
    # 同一种子抽到同样的两部
    assert picked[0] == picked[1]


def test_resume_keeps_selected_groups(env, cli, monkeypatch):
    for i in range(5):
        env.nfo(f"丙/GRP-00{i}/GRP-00{i}.nfo", f"GRP-00{i}", _CN_TITLE)
    # 第一部翻完后第二部时按了 Ctrl-C
    FakeTranslator.outputs = {"plot": lambda msg: KeyboardInterrupt() if "GRP-001" in msg else _PLOT_OUT}

    assert env.run("translate", "--limit", "2", "--workers", "1") == 130
    run = env.only_run()
    FakeTranslator.outputs = {}
    FakeTranslator.calls = []

    assert [rec.num for rec in run.load_translations()] == ["GRP-000"]

    assert env.run("translate", "--limit", "2", "--resume", run.run_id) == 0

    # 续跑仍只翻当初选中的两部，不会再往后取
    assert len(FakeTranslator.calls) == 1
    assert sorted(rec.num for rec in run.load_translations()) == ["GRP-000", "GRP-001"]


def _groups(env: Env):
    from app.services.nfo_retranslate.scope import group_films

    return group_films(str(env.root))[0]


def _fake_refresher(calls: list):
    def factory(db, client_factory, *, root, strm_root, **_kwargs):
        calls.append({"root": root, "strm_root": strm_root})

        def refresh(paths):
            calls.append(list(paths))
            return len(paths), [], []

        return refresh

    return factory


def test_apply_then_restore_cli(env, cli, monkeypatch, capsys):
    group_a, b = _two_groups(env)
    paths = [*group_a, b]
    before = _snapshot(paths)
    # 根目录写成未规范化的样子，脚本要先 abspath
    env.settings.nfo_translate_root = str(env.tmp / "x" / ".." / "302porn_tv1")
    calls: list = []
    monkeypatch.setattr(cli, "make_refresher", _fake_refresher(calls))
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(None))

    assert env.run("translate") == 0
    run = env.only_run()
    # apply 用 run.json 里记下的模型，不用当前配置
    env.settings.nfo_translate_model = "changed-model"

    assert env.run("apply", "--run", run.run_id) == 0

    for path in paths:
        assert Path(path).read_bytes() != before[path]
    doc = read_nfo(b)
    assert doc.plot.endswith(f"由 {_MODEL} 提供翻译")
    assert read_nfo(group_a[1]).title == f"ABC-001 {_TITLE_OUT}"
    assert calls[0] == {
        "root": str(env.root),
        "strm_root": str(env.tmp / "strm" / "302porn_tv1"),
    }
    assert sorted(calls[1]) == sorted(paths)

    assert env.run("restore", "--run", run.run_id, "--no-refresh") == 0
    assert _snapshot(paths) == before
    assert "Jellyfin" in capsys.readouterr().out


def test_apply_requires_model_in_meta(env, capsys):
    _two_groups(env)
    assert env.run("translate") == 0
    run = env.only_run()
    os.remove(os.path.join(run.path, "run.json"))

    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 1
    assert "模型" in capsys.readouterr().out


def test_apply_skip_file_by_num_and_path(env, monkeypatch, capsys):
    group_a, b = _two_groups(env)
    before = _snapshot([*group_a, b])
    assert env.run("translate") == 0
    run = env.only_run()
    monkeypatch.chdir(env.tmp)
    skip = env.tmp / "skip.txt"
    skip.write_text(
        f"# 不要写的\n\nABC-001\n{os.path.relpath(b, env.tmp)}\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    assert env.run("apply", "--run", run.run_id, "--skip", str(skip), "--no-refresh") == 0

    assert _snapshot([*group_a, b]) == before
    out = capsys.readouterr().out
    assert "跳过名单：3" in out
    assert "手动扫描" in out


def test_apply_summary_splits_skip_reasons(env, capsys):
    group_a, b = _two_groups(env)
    FakeTranslator.outputs = {"plot": TranslateError("翻译接口请求失败（HTTP 500，已尝试 4 次）")}
    assert env.run("translate", "--path-prefix", "乙") == 0
    FakeTranslator.outputs = {}
    first = env.runs()[-1]
    assert env.run("translate", "--path-prefix", "甲") == 0
    second = env.runs()[-1]
    # 甲组一段在 translate 之后被改过
    Path(group_a[0]).write_bytes(Path(group_a[0]).read_bytes().replace(b"<rating>7.0</rating>", b"<rating>8.0</rating>"))
    capsys.readouterr()

    assert env.run("apply", "--run", first.run_id, "--no-refresh") == 0
    out = capsys.readouterr().out
    assert "翻译失败不写：1" in out
    assert "文件被改动或读写出错：0" in out

    assert env.run("apply", "--run", second.run_id, "--no-refresh") == 0
    out = capsys.readouterr().out
    assert "写入：1" in out
    assert "翻译失败不写：0" in out
    assert "文件被改动或读写出错：1" in out


def _fingerprint_case(env: Env, cli):
    group_a, b = _two_groups(env)
    paths = [*group_a, b]
    before = _snapshot(paths)
    assert env.run("translate") == 0
    run = env.only_run()
    return run, paths, before


def test_apply_refuses_without_report_fingerprint(env, cli, capsys):
    run, paths, before = _fingerprint_case(env, cli)
    meta = cli.read_run_meta(run)
    del meta["report"]
    # 模拟 translate 被杀、没生成报告
    cli.write_run_meta(run, meta)
    capsys.readouterr()

    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 1

    assert f"--resume {run.run_id}" in capsys.readouterr().out
    assert _snapshot(paths) == before


def test_apply_refuses_when_records_changed_after_report(env, cli):
    run, paths, before = _fingerprint_case(env, cli)
    last = run.load_translations()[-1]
    run.append_translation(last)

    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 1
    assert _snapshot(paths) == before


def test_resume_drops_old_fingerprint_until_new_report(env, cli, monkeypatch):
    run, paths, before = _fingerprint_case(env, cli)
    assert "report" in cli.read_run_meta(run)

    def killed(*_args, **_kwargs):
        raise SystemExit("被杀")

    # 续跑在写新报告之前就被杀
    monkeypatch.setattr(cli, "write_report", killed)
    with pytest.raises(SystemExit):
        env.run("translate", "--resume", run.run_id)

    assert "report" not in cli.read_run_meta(run)
    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 1
    assert _snapshot(paths) == before


# ---------- 整体审查修复 ----------


def test_script_configures_mappers_in_fresh_interpreter():
    """C1：单独运行脚本时 ORM 映射能配置成功（Jellyfin 条目查询要用）。"""
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('nfo_cli', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules['nfo_cli'] = m\n"
        "spec.loader.exec_module(m)\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "print('ok')\n"
    )
    repo = SCRIPT.parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo)}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def _raising_refresher(calls: list):
    def factory(db, client_factory, *, root, strm_root, **_kwargs):
        def refresh(paths):
            calls.append(list(paths))
            raise RuntimeError("映射配置失败")

        return refresh

    return factory


def test_refresh_exception_is_recorded_not_raised(env, cli, monkeypatch, capsys):
    """C1：刷新阶段抛普通异常时，apply/restore 照常结束、打印汇总，NFO 不回滚。"""
    group_a, b = _two_groups(env)
    paths = [*group_a, b]
    before = _snapshot(paths)
    calls: list = []
    monkeypatch.setattr(cli, "make_refresher", _raising_refresher(calls))
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(None))
    assert env.run("translate") == 0
    run = env.only_run()
    capsys.readouterr()

    assert env.run("apply", "--run", run.run_id) == 0

    out = capsys.readouterr().out
    assert "写入：3" in out
    assert "刷新出错：RuntimeError" in out
    assert "兜底" in out
    assert all(Path(path).read_bytes() != before[path] for path in paths)
    refresh_row = run.load_apply()[-1]["refresh"]
    assert refresh_row["refreshed"] == 0
    assert "RuntimeError" in refresh_row["failed"][0][1]

    assert env.run("restore", "--run", run.run_id) == 0
    out = capsys.readouterr().out
    assert "还原：3" in out and "兜底" in out
    assert _snapshot(paths) == before
    assert len(calls) == 2


def test_translate_thinking_flag(env, cli, capsys):
    """思考默认关；--thinking 打开，记进 run.json，续跑沿用原运行的开关。"""
    _two_groups(env)
    assert env.run("translate", "--limit", "1") == 0
    assert FakeTranslator.init_kwargs.get("thinking") is False
    assert "思考关" in capsys.readouterr().out

    FakeTranslator.outputs = {"plot": KeyboardInterrupt()}
    assert env.run("translate", "--thinking", "--workers", "1") == 130
    assert FakeTranslator.init_kwargs.get("thinking") is True
    run = env.only_run()
    meta = json.loads(Path(run.path, "run.json").read_text(encoding="utf-8"))
    assert meta["args"]["thinking"] is True

    FakeTranslator.outputs = {}
    FakeTranslator.init_kwargs = {}
    assert env.run("translate", "--resume", run.run_id) == 0
    assert FakeTranslator.init_kwargs.get("thinking") is True


def test_resume_reuses_original_args(env, cli, capsys):
    """I1：原运行带 --engine，续跑不带参数也只处理原来筛中的组。"""
    group_a, b = _two_groups(env)
    for path in group_a:
        Path(path).write_bytes(Path(path).read_bytes().replace("由 OpenAI 提供翻译".encode(), "由 Google 提供翻译".encode()))
    # 甲组标题翻完、简介时按了 Ctrl-C
    FakeTranslator.outputs = {"plot": KeyboardInterrupt()}
    assert env.run("translate", "--engine", "Google", "--workers", "1") == 130
    run = env.only_run()
    FakeTranslator.outputs = {}
    FakeTranslator.calls = []

    assert env.run("translate", "--resume", run.run_id) == 0

    assert len(FakeTranslator.calls) == 1
    assert "番号：ABC-001" in FakeTranslator.calls[0]
    assert {rec.num for rec in run.load_translations()} == {"ABC-001"}


def test_resume_rejects_changed_args(env, cli, capsys):
    """I1：续跑时给了和原运行不同的参数就拒绝；给相同的值可以。"""
    _two_groups(env)
    assert env.run("translate", "--engine", "OpenAI") == 0
    run = env.only_run()
    capsys.readouterr()
    FakeTranslator.calls = []

    for extra in (["--engine", "Google"], ["--limit", "1"], ["--fields", "title"], ["--path-prefix", "甲"], ["--redo"],
                  ["--thinking"]):
        assert env.run("translate", "--resume", run.run_id, *extra) == 1
        assert "续跑沿用原运行参数" in capsys.readouterr().out
    assert FakeTranslator.calls == []

    assert env.run("translate", "--resume", run.run_id, "--engine", "OpenAI") == 0


def test_translate_fingerprint_matches_report_bytes(env, cli, monkeypatch, capsys):
    """I2：报告写完、记指纹前文件被追加，指纹仍是报告用的那份，apply 拒绝。"""
    group_a, b = _two_groups(env)
    paths = [*group_a, b]
    before = _snapshot(paths)
    real_write_report = cli.write_report

    def write_then_append(path, records, **kwargs):
        real_write_report(path, records, **kwargs)
        run = env.only_run()
        extra = run.load_translations()[-1]
        run.append_translation(extra)

    monkeypatch.setattr(cli, "write_report", write_then_append)
    assert env.run("translate") == 0
    run = env.only_run()
    meta = cli.read_run_meta(run)
    current = Path(run.path, "translations.jsonl").read_bytes()
    assert meta["report"]["size"] < len(current)

    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 1
    assert _snapshot(paths) == before


def test_apply_uses_checked_records_only(env, cli, monkeypatch):
    """I2：apply 核对指纹之后文件被追加，新追加的记录不会写进 NFO。"""
    _, b = _two_groups(env)
    assert env.run("translate") == 0
    run = env.only_run()
    real_apply_run = cli.apply_run

    def append_then_apply(run_dir, **kwargs):
        late = next(rec for rec in run_dir.load_translations() if rec.num == "DEF-002")
        late.new_text = "核对之后才追加的译文，不该写进去。"
        run_dir.append_translation(late)
        return real_apply_run(run_dir, **kwargs)

    monkeypatch.setattr(cli, "apply_run", append_then_apply)

    assert env.run("apply", "--run", run.run_id, "--no-refresh") == 0

    plot = read_nfo(b).plot
    assert "不该写进去" not in plot
    assert plot.startswith(_PLOT_OUT.replace("\n", "<br>"))


def test_title_output_strips_num_and_rejects_newline(env):
    """I3：标题译文开头的番号去掉；含换行的判失败。"""
    _two_groups(env)
    FakeTranslator.outputs = {"title": f"ABC-001 {_TITLE_OUT}"}
    assert env.run("translate", "--fields", "title") == 0
    rec = env.runs()[-1].load_translations()[0]
    assert rec.new_text == _TITLE_OUT and rec.error is None

    FakeTranslator.outputs = {"title": f"{_TITLE_OUT}\n（注：人名保留原文）"}
    assert env.run("translate", "--fields", "title") == 0
    rec = env.runs()[-1].load_translations()[0]
    assert rec.new_text is None
    assert rec.error == "标题译文含换行"


def test_plot_strips_leading_num(env):
    """简介原文开头的番号（含 FC2-PPV 写法）送翻译前去掉；模型输出的简介开头带番号也去掉。"""
    path = env.nfo("乙/FC2-4343195/FC2-4343195.nfo", "FC2-4343195", _JP)
    raw = Path(path).read_bytes().decode("utf-8")
    Path(path).write_bytes(raw.replace("<originalplot>", "<originalplot>FC2-PPV-4343195 ", 1).encode("utf-8"))
    FakeTranslator.outputs = {"plot": f"FC2-PPV-4343195 {_PLOT_OUT}"}

    assert env.run("translate", "--fields", "plot") == 0

    rec = env.runs()[-1].load_translations()[0]
    assert not rec.source_text.startswith("FC2-PPV")
    assert all("FC2-PPV-4343195" not in msg for msg in FakeTranslator.calls)
    assert rec.new_text == _PLOT_OUT and rec.error is None


def test_translate_prints_progress(env, capsys):
    """I4：翻译过程中打印进度。"""
    _two_groups(env)

    assert env.run("translate") == 0

    assert "已完成 3/3，失败 0" in capsys.readouterr().out


def test_mdc_copy_not_kept_in_run_dir(env):
    """I5：MDC 库副本读完即删，运行目录里没有 mdc/ 和 .db 文件。"""
    _two_groups(env)

    assert env.run("translate") == 0

    run = env.only_run()
    assert not os.path.exists(os.path.join(run.path, "mdc"))
    for _dirpath, _dirs, files in os.walk(run.path):
        assert not [name for name in files if ".db" in name]


def test_source_doc_is_first_target(env):
    """M1：组内第一个 NFO 被已写入记录跳过时，原文和旧译文取实际要写的那个。"""
    group_a, _ = _two_groups(env)
    second = Path(group_a[1])
    second.write_bytes(second.read_bytes().replace("订婚后的我被两位上司在耳边低语诱惑".encode(), "第二段的旧标题".encode(), 1))
    sha = sha256_text(Path(group_a[0]).read_bytes().decode("utf-8"))
    os.makedirs(env.base)
    append_ledger(env.base, group_a[0], LedgerEntry(sha256_after=sha, fields=frozenset({"title", "plot"}), model="x"))

    assert env.run("translate", "--fields", "title") == 0

    rec = env.only_run().load_translations()[0]
    assert list(rec.targets) == [group_a[1]]
    assert rec.old_text == "第二段的旧标题"


def test_strm_root_matches_directory_name(env, cli, monkeypatch):
    """M2：只认目录名正好是 302porn_tv1 的那一项。"""
    _two_groups(env)
    wanted = str(env.tmp / "strm" / "302porn_tv1")
    env.settings.media_library_strm_roots = [str(env.tmp / "old" / "302porn_tv1_backup"), wanted]
    calls: list = []
    monkeypatch.setattr(cli, "make_refresher", _fake_refresher(calls))
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(None))
    assert env.run("translate") == 0

    assert env.run("apply", "--run", env.only_run().run_id) == 0

    assert calls[0]["strm_root"] == wanted
