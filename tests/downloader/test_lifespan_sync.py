from __future__ import annotations

from types import SimpleNamespace

from app.main import _downloader_integration_enabled


def test_downloader_sweeper_only_starts_when_explicitly_enabled():
    assert _downloader_integration_enabled(SimpleNamespace(downloader_enabled=False, downloader_base_url="http://rn")) is False
    assert _downloader_integration_enabled(SimpleNamespace(downloader_enabled=True, downloader_base_url="")) is False
    assert _downloader_integration_enabled(SimpleNamespace(downloader_enabled=True, downloader_base_url="http://rn")) is True
