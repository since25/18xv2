from __future__ import annotations

import time

from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.script_runs import ScriptRun
from app.services.script_jobs.config_service import ensure_default_configs
from app.services.script_jobs.runner import ScriptJobRunner


def test_real_subprocess_runs_from_run_dir_and_reports_missing_cookie(db_session, tmp_path, monkeypatch):
    """不碰网络：没有站点 cookie 时子进程应正常启动、写结果，并以“尚未设置站点 cookie”失败。"""
    monkeypatch.setenv("SEHUATANG_SESSION_PATH", str(tmp_path / "missing.json"))
    get_settings.cache_clear()
    try:
        ensure_default_configs(db_session)
        factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
        runner = ScriptJobRunner(factory, tmp_path / "jobs")
        run_id = runner.start("sehuatang", trigger="manual", dry_run=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            runner.poll()
            db_session.expire_all()
            run = db_session.get(ScriptRun, run_id)
            if run.status not in ("queued", "running"):
                break
            time.sleep(0.2)
    finally:
        get_settings.cache_clear()

    assert run.status == "failed", run.error_reason
    assert run.error_reason == "尚未设置站点 cookie"
    assert run.exit_code == 0
    log_text = (tmp_path / "jobs" / "sehuatang" / str(run_id) / "output.log").read_text(encoding="utf-8")
    assert "开始：演练" in log_text
