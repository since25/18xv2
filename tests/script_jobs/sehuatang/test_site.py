from __future__ import annotations

from app.services.script_jobs.sehuatang.site import CurlSiteClient


class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status
        self.content = text.encode()


class _Cookies(dict):
    def set(self, name, value, domain=None, path=None):
        self[name] = (value, domain, path)


class _Session:
    def __init__(self, responses):
        self.headers: dict = {}
        self.cookies = _Cookies()
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        return self.responses.pop(0)


SAFE = "<script src='static/safe/js/x.js'></script><script>var safeid='sid1';</script>"


def test_safe_page_sets_cookie_and_retries():
    session = _Session([_Resp(SAFE), _Resp("<html>真实内容</html>")])
    client = CurlSiteClient({"a": "1"}, "UA-Test", session=session, sleep=lambda s: None)
    response = client.get("https://sehuatang.org/x", timeout=5)
    assert response.text == "<html>真实内容</html>"
    assert session.cookies["_safe"] == ("sid1", "sehuatang.org", "/")
    assert session.headers["user-agent"] == "UA-Test"
    assert session.calls == 2


def test_safe_retries_are_bounded():
    session = _Session([_Resp(SAFE), _Resp(SAFE), _Resp(SAFE)])
    client = CurlSiteClient({}, "UA", session=session, sleep=lambda s: None)
    client.get("https://sehuatang.org/x", timeout=5)
    assert session.calls == 3
