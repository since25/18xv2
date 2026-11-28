"""翻译接口调用：把拼好的用户消息发给 OpenAI 兼容的 /chat/completions，带重试与有限并发。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time

import httpx

from app.services.nfo_retranslate.prompts import SYSTEM_PROMPT

# 固定温度：要稳定，不要发挥
_TEMPERATURE = 0.3


class TranslateError(Exception):
    """翻译接口请求失败或返回不可用；消息只写状态码、尝试次数，不写地址和密钥。"""


@dataclass(frozen=True)
class TranslateJob:
    """一次翻译：key 用来找回原文和目标 NFO，field 是 title 或 plot。"""

    key: str
    field: str
    user_message: str


class TranslatorClient:
    """OpenAI 兼容翻译接口的同步客户端；每个线程复用自己的 httpx.Client。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 60.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = str(base_url).rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self.model = model
        self.timeout = float(timeout)
        self.retries = int(retries)
        self._transport = transport
        self._sleep = sleep_fn
        self._local = threading.local()

    def _session(self) -> httpx.Client:
        """取当前线程的 httpx.Client，没有就新建一个。"""
        session = getattr(self._local, "session", None)
        if session is None:
            session = httpx.Client(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self._api_key}"},
                transport=self._transport,
            )
            self._local.session = session
        return session

    def translate(self, user_message: str) -> str:
        """发一条用户消息，返回去掉首尾空白的译文；连接错误、429、5xx 退避 2**attempt 秒重试，其他 4xx 直接失败。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": _TEMPERATURE,
        }
        attempts = self.retries + 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = self._session().post(self._url, json=payload)
            except httpx.RequestError as exc:
                if not last:
                    self._sleep(2**attempt)
                    continue
                # from None：httpx 的异常里可能带请求地址，不往外带
                raise TranslateError(f"翻译接口连接失败（{type(exc).__name__}，已尝试 {attempts} 次）") from None

            status = response.status_code
            if status < 400:
                return self._content(response)
            if (status == 429 or status >= 500) and not last:
                self._sleep(2**attempt)
                continue
            raise TranslateError(f"翻译接口请求失败（HTTP {status}，已尝试 {attempt + 1} 次）")
        raise TranslateError("翻译接口请求失败")

    @staticmethod
    def _content(response: httpx.Response) -> str:
        """取 choices[0].message.content 并去掉首尾空白。"""
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, LookupError, TypeError):
            raise TranslateError("翻译接口返回格式无效") from None
        if not isinstance(content, str):
            raise TranslateError("翻译接口返回格式无效")
        return content.strip()


def translate_all(
    client: TranslatorClient,
    jobs: Sequence[TranslateJob],
    *,
    workers: int,
    on_result: Callable[[TranslateJob, str | None, str | None], None],
) -> None:
    """最多 workers 个线程并发翻译；每个任务回调一次 on_result(job, 译文, 错误原因)，回调加锁串行，写记录不交错。"""
    lock = threading.Lock()

    def run(job: TranslateJob) -> None:
        try:
            text, reason = client.translate(job.user_message), None
        except TranslateError as exc:
            text, reason = None, str(exc)
        with lock:
            on_result(job, text, reason)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, job) for job in jobs]
    # 线程池已等全部任务结束；回调或意外错误在这里抛出
    for future in futures:
        future.result()
