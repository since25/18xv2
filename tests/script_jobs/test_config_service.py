from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.script_runs import ScriptJobConfigChange
from app.services.script_jobs.config_service import ensure_default_configs, get_config, list_configs, update_config
from app.services.script_jobs.definitions import JOB_NAMES


def _update(db, job_name, **changes):
    values = {"enabled": None, "run_time": None, "executor": None, "params": None}
    values.update(changes)
    return update_config(db, job_name, **values)


def test_default_configs_are_seeded_in_job_order(db_session):
    ensure_default_configs(db_session)
    configs = list_configs(db_session)
    assert [config.job_name for config in configs] == list(JOB_NAMES)
    assert {config.executor for config in configs} == {"unraid"}
    assert get_config(db_session, "sehuatang").params["pages"] == 4


def test_update_rejects_dir_outside_allowed_roots(db_session):
    ensure_default_configs(db_session)
    with pytest.raises(ValueError, match="挂载"):
        _update(
            db_session,
            "MOVE_SSD_CACHE_TO_DISK2",
            params={"source_dir": "/mnt/user/other", "target_dir": "/mnt/disk2/qbbtdn/已整理"},
        )


def test_update_rejects_parent_traversal(db_session):
    ensure_default_configs(db_session)
    with pytest.raises(ValueError):
        _update(
            db_session,
            "MOVE_SSD_CACHE_TO_DISK2",
            params={"source_dir": "/mnt/disk2/qbbtdn/../x", "target_dir": "/mnt/disk2/qbbtdn/已整理"},
        )


def test_update_accepts_allowed_root_itself(db_session):
    ensure_default_configs(db_session)
    config = _update(
        db_session,
        "MOVE_SSD_CACHE_TO_DISK2",
        params={"source_dir": "/mnt/cache/docker1/SSD_cache", "target_dir": "/mnt/disk2/qbbtdn/已整理"},
    )
    assert config.params["source_dir"] == "/mnt/cache/docker1/SSD_cache"


def test_update_rejects_18x_executor_for_unrunnable_job(db_session, monkeypatch):
    # 三个脚本现在都能在 18x 执行；用一个改成不可执行的定义验证这道保护仍然有效
    from dataclasses import replace

    from app.services.script_jobs import config_service, definitions

    unrunnable = replace(definitions.get_definition("DEL_SOMETHING"), runnable=False)
    monkeypatch.setattr(config_service, "get_definition", lambda name: unrunnable)
    ensure_default_configs(db_session)
    with pytest.raises(ValueError, match="尚未支持在 18x 执行"):
        _update(db_session, "DEL_SOMETHING", executor="18x")


def test_move_and_del_can_switch_to_18x(db_session):
    ensure_default_configs(db_session)
    for name in ("MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING"):
        assert _update(db_session, name, executor="18x").executor == "18x"


def test_update_records_change_with_before_and_after(db_session):
    ensure_default_configs(db_session)
    params = dict(get_config(db_session, "sehuatang").params, pages=6)
    _update(db_session, "sehuatang", params=params)
    changes = db_session.scalars(select(ScriptJobConfigChange)).all()
    assert len(changes) == 1
    assert changes[0].job_name == "sehuatang"
    assert changes[0].before["params"]["pages"] == 4
    assert changes[0].after["params"]["pages"] == 6


def test_update_without_change_writes_no_record(db_session):
    ensure_default_configs(db_session)
    _update(db_session, "sehuatang", run_time="01:28", enabled=False)
    assert db_session.scalars(select(ScriptJobConfigChange)).all() == []


@pytest.mark.parametrize("value", ["1:28", "24:00", "aa", "01:60", ""])
def test_run_time_must_be_hh_mm(db_session, value):
    ensure_default_configs(db_session)
    with pytest.raises(ValueError):
        _update(db_session, "sehuatang", run_time=value)


def test_run_time_valid_value_saved(db_session):
    ensure_default_configs(db_session)
    assert _update(db_session, "sehuatang", run_time="02:30").run_time == "02:30"


def test_forum_url_requires_page_placeholder(db_session):
    ensure_default_configs(db_session)
    params = dict(get_config(db_session, "sehuatang").params, forum_url="https://sehuatang.org/forum.php?page=1")
    with pytest.raises(ValueError):
        _update(db_session, "sehuatang", params=params)


def test_pages_limited_to_twenty(db_session):
    ensure_default_configs(db_session)
    params = dict(get_config(db_session, "sehuatang").params, pages=21)
    with pytest.raises(ValueError):
        _update(db_session, "sehuatang", params=params)


def test_unknown_job_raises_key_error(db_session):
    ensure_default_configs(db_session)
    with pytest.raises(KeyError):
        get_config(db_session, "NOPE")
