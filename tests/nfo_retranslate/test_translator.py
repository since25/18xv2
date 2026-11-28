from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from app.services.nfo_retranslate.prompts import SYSTEM_PROMPT
from app.services.nfo_retranslate.translator import (
    TranslateError,
    TranslateJob,
    TranslatorClient,
    translate_all,
)

_BASE = "https://llm.test/v1"


def _reply(text: str) -> httpx.Response:
    """模拟 OpenAI 兼容接口的成功返回。"""
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


def _client(handler, *, retries: int = 3, sleeps: list[float] | None = None) -> TranslatorClient:
    """用 MockTransport 建客户端；退避只记录秒数，不真等。"""
    return TranslatorClient(
        _BASE + "/",
        "test-key",
        "qwen38",
        retries=retries,
        transport=httpx.MockTransport(handler),
        sleep_fn=(sleeps.append if sleeps is not None else lambda _seconds: None),
    )


def test_translate_posts_chat_completion():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _reply("  被同事看见的那一晚\n")

    result = _client(handler).translate("用户消息")

    assert result == "被同事看见的那一晚"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{_BASE}/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "qwen38"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"][1] == {"role": "user", "content": "用户消息"}
    assert body["temperature"] == 0.3


def test_translate_retries_429_and_5xx_then_succeeds():
    statuses = [429, 502]
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if statuses:
            return httpx.Response(statuses.pop(0))
        return _reply("译文")

    assert _client(handler, sleeps=sleeps).translate("用户消息") == "译文"
    assert len(calls) == 3
    # 退避 2**attempt 秒
    assert sleeps == [1, 2]


def test_translate_gives_up_after_retries():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="服务器内部错误")

    with pytest.raises(TranslateError) as excinfo:
        _client(handler, retries=2).translate("用户消息")

    assert len(calls) == 3
    message = str(excinfo.value)
    assert "500" in message
    # 地址和密钥不得出现在错误信息里
    assert "test-key" not in message
    assert "llm.test" not in message


def test_translate_all_respects_worker_limit():
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "in_callback": 0, "max_in_callback": 0}
    requests_by_message: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)["messages"][1]["content"]
        with lock:
            requests_by_message[message] = requests_by_message.get(message, 0) + 1
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        # 让请求在处理函数里停一会儿，制造并发重叠
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        if message == "m4":
            return httpx.Response(400, json={"error": "bad request"})
        return _reply(f"译:{message}")

    results: list[tuple[TranslateJob, str | None, str | None]] = []

    def on_result(job: TranslateJob, text: str | None, reason: str | None) -> None:
        # 不加锁地改计数：如果回调被并发调用，这里会记到大于 1
        state["in_callback"] += 1
        state["max_in_callback"] = max(state["max_in_callback"], state["in_callback"])
        time.sleep(0.005)
        results.append((job, text, reason))
        state["in_callback"] -= 1

    jobs = [TranslateJob(key=f"k{i}", field="title", user_message=f"m{i}") for i in range(10)]
    translate_all(_client(handler), jobs, workers=3, on_result=on_result)

    assert 2 <= state["max_active"] <= 3
    assert state["max_in_callback"] == 1
    assert sorted(job.key for job, _text, _reason in results) == sorted(job.key for job in jobs)
    for job, text, reason in results:
        if job.user_message == "m4":
            assert text is None
            assert reason is not None and "400" in reason
        else:
            assert text == f"译:{job.user_message}"
            assert reason is None
    # 400 不重试
    assert requests_by_message["m4"] == 1


def test_translate_all_stops_when_callback_fails():
    lock = threading.Lock()
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            calls.append(1)
        # 停一会儿，让队列里还有没开始的任务
        time.sleep(0.02)
        return _reply("译文")

    def on_result(job: TranslateJob, text: str | None, reason: str | None) -> None:
        raise RuntimeError("写记录失败")

    jobs = [TranslateJob(key=f"k{i}", field="plot", user_message=f"m{i}") for i in range(20)]
    with pytest.raises(RuntimeError, match="写记录失败"):
        translate_all(_client(handler), jobs, workers=2, on_result=on_result)

    # 回调出错后取消还没开始的任务，不再继续请求接口
    assert len(calls) < 20
