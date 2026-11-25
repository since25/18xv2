"""sehuatang 主流程测试用的假站点和假 qB。"""

from __future__ import annotations

from app.services.script_jobs.sehuatang.qb import QbError
from app.services.script_jobs.sehuatang.site import SiteResponse


FORUM = "https://sehuatang.org/forum.php?mod=forumdisplay&fid=2&page={page}"


def ok(text: str = "", content: bytes | None = None) -> SiteResponse:
    return SiteResponse(status=200, text=text, content=content if content is not None else text.encode())


class FakeSite:
    """url → 响应（或异常）；记录访问顺序。"""

    def __init__(self, pages: dict[str, SiteResponse | Exception]):
        self.pages = pages
        self.visited: list[str] = []

    def get(self, url: str, timeout: int) -> SiteResponse:
        self.visited.append(url)
        value = self.pages.get(url, SiteResponse(status=404, text="", content=b""))
        if isinstance(value, Exception):
            raise value
        return value


class FakeQb:
    def __init__(self, *, login_fail: bool = False, add_fail: bool = False):
        self.login_fail = login_fail
        self.add_fail = add_fail
        self.logged_in = False
        self.torrents: list[tuple[bytes, str, str]] = []
        self.magnets: list[tuple[list[str], str]] = []

    def login(self) -> None:
        if self.login_fail:
            raise QbError("qB 登录失败（HTTP 403）")
        self.logged_in = True

    def add_torrent(self, data: bytes, filename: str, category: str) -> None:
        if self.add_fail:
            raise QbError("qB 拒收（HTTP 200：Fails.）")
        self.torrents.append((data, filename, category))

    def add_magnets(self, urls: list[str], category: str) -> None:
        if self.add_fail:
            raise QbError("qB 拒收（HTTP 200：Fails.）")
        self.magnets.append((urls, category))
