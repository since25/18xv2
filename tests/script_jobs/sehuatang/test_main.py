from __future__ import annotations

import json

from app.services.script_jobs.sehuatang import main as main_module
from app.services.script_jobs.site_session import save_site_session

from tests.script_jobs.sehuatang.fakes import FORUM, FakeQb, FakeSite, ok
from tests.script_jobs.sehuatang.helpers import list_page, thread_page


MAGNET = "magnet:?xt=urn:btih:" + "D" * 40


def _write_input(tmp_path, **overrides):
    payload = {
        "dry_run": False,
        "pages": 1,
        "forum_url": FORUM,
        "qb_category": "国产BT",
        "terms": [["AI增强", "ai增强"]],
        "submitted_tids": [],
    }
    payload.update(overrides)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_main_without_session_file_writes_fatal_result(tmp_path, monkeypatch):
    monkeypatch.setenv("SEHUATANG_SESSION_PATH", str(tmp_path / "missing.json"))
    input_path = _write_input(tmp_path)
    result_path = tmp_path / "result.json"

    code = main_module.main(["--input", str(input_path), "--result", str(result_path)])

    assert code == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["fatal_reason"] == "尚未设置站点 cookie"
    assert result["items"] == []


def test_main_output_never_contains_secrets(tmp_path, monkeypatch, capsys):
    session_path = tmp_path / "site_session.json"
    save_site_session(session_path, "cf_clearance=SECRET-COOKIE-123", "Mozilla/5.0 Test")
    monkeypatch.setenv("SEHUATANG_SESSION_PATH", str(session_path))
    monkeypatch.setenv("QB_URL", "https://qb.invalid:16666")
    monkeypatch.setenv("QB_USERNAME", "user")
    monkeypatch.setenv("QB_PASSWORD", "SECRET-PW-456")
    site = FakeSite(
        {
            FORUM.format(page=1): ok(list_page([("21", "帖子甲")])),
            "https://sehuatang.org/thread-21-1-1.html": ok(thread_page(magnets=[MAGNET])),
        }
    )
    qb = FakeQb()
    seen_session = {}

    def fake_make_site(session):
        seen_session["cookies"] = session.cookies
        return site

    monkeypatch.setattr(main_module, "make_site", fake_make_site)
    monkeypatch.setattr(main_module, "make_qb", lambda: qb)
    monkeypatch.setattr(main_module, "SLEEP", lambda seconds: None)
    input_path = _write_input(tmp_path)
    result_path = tmp_path / "result.json"

    code = main_module.main(["--input", str(input_path), "--result", str(result_path)])

    assert code == 0
    assert seen_session["cookies"] == {"cf_clearance": "SECRET-COOKIE-123"}
    assert qb.magnets == [([MAGNET], "国产BT")]
    output = capsys.readouterr().out + result_path.read_text(encoding="utf-8")
    assert "SECRET-COOKIE-123" not in output
    assert "SECRET-PW-456" not in output
    assert json.loads(result_path.read_text(encoding="utf-8"))["counts"]["submitted"] == 1
    # 逐帖追加的进度文件，被打断时靠它找回已提交的帖子
    lines = (tmp_path / "items.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["tid"] for line in lines] == ["21"]
    assert "SECRET" not in "".join(lines)


def test_make_qb_returns_none_without_config(monkeypatch):
    monkeypatch.delenv("QB_URL", raising=False)
    monkeypatch.delenv("QB_USERNAME", raising=False)
    monkeypatch.delenv("QB_PASSWORD", raising=False)
    assert main_module.make_qb() is None
