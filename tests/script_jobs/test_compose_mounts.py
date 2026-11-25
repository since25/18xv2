"""页面上能选的媒体根目录，必须在 18x 容器里以相同路径、可写方式挂载。"""

from __future__ import annotations

import yaml

from app.services.script_jobs.definitions import ALLOWED_ROOTS
from app.services.script_jobs.media_task import PROJECT_ROOT


def test_allowed_roots_are_mounted_at_same_path():
    compose = yaml.safe_load((PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    volumes = compose["services"]["app"]["volumes"]
    for root in ALLOWED_ROOTS:
        assert f"{root}:{root}" in volumes, root
        assert f"{root}:{root}:ro" not in volumes
