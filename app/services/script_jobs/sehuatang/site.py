"""站点访问：curl_cffi 模拟 Chrome 指纹，并自动处理“安全验证 / 18 岁确认”页。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from app.services.script_jobs.sehuatang.pages import extract_safeid


# 请求头沿用原 gc.py，只把 User-Agent 换成页面上设置的（cf_clearance 与它绑定）
BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "zh-CN,zh;q=0.9",
    "referer": "https://sehuatang.org/",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
SAFE_RETRIES = 2


@dataclass(frozen=True)
class SiteResponse:
    status: int
    text: str
    content: bytes


class SiteClient(Protocol):
    def get(self, url: str, timeout: int) -> SiteResponse: ...


class CurlSiteClient:
    def __init__(self, cookies: dict[str, str], user_agent: str, *, session=None, sleep=time.sleep):
        if session is None:
            from curl_cffi import requests as curl_requests

            session = curl_requests.Session(impersonate="chrome110")
        session.headers.update({**BASE_HEADERS, "user-agent": user_agent})
        session.cookies.update(cookies)
        self._session = session
        self._sleep = sleep

    def get(self, url: str, timeout: int) -> SiteResponse:
        response = self._session.get(url, timeout=timeout)
        for _ in range(SAFE_RETRIES):
            safeid = extract_safeid(response.text)
            if safeid is None:
                break
            # 验证页由前端 JS 设置 _safe cookie 后重新访问才返回真实内容
            self._session.cookies.set("_safe", safeid, domain="sehuatang.org", path="/")
            self._sleep(1)
            response = self._session.get(url, timeout=timeout)
        return SiteResponse(status=response.status_code, text=response.text, content=response.content)
