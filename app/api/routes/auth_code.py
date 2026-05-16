"""
授权码换 token 路由。当启动时 token 失效，用户可人工粘贴授权码通过此接口换取新 token。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services.client_115.client import Client115Error

router = APIRouter(prefix="/tools/auth-code", tags=["tools"])


class AuthCodeRequest(BaseModel):
    auth_code: str


class AuthCodeResponse(BaseModel):
    success: bool
    message: str


@router.post("", response_model=AuthCodeResponse)
def exchange_auth_code_route(payload: AuthCodeRequest, request: Request) -> AuthCodeResponse:
    client = request.app.state.client_115
    try:
        token = client.exchange_auth_code(payload.auth_code)
        # 换码成功后持久化 token 并标记 client 为就绪
        client._persist_tokens(token)
        request.app.state.client_115_ready = True
        request.app.state.client_115_last_error = None
        return AuthCodeResponse(success=True, message="授权成功，token 已保存。")
    except Client115Error as exc:
        return AuthCodeResponse(success=False, message=f"授权失败：{exc}")


@router.get("", response_class=HTMLResponse)
def auth_code_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>授权码换 Token</title>
  <style>
    :root{--bg:#f4efe7;--card:#fffaf4;--ink:#1e2320;--muted:#66706a;--accent:#125f54;--line:#ded4c6}
    *{box-sizing:border-box}
    body{margin:0;font-family:"PingFang SC","Noto Sans SC",sans-serif;background:linear-gradient(135deg,#f8f2ea,#ebe0d2);color:var(--ink)}
    .shell{max-width:640px;margin:0 auto;padding:40px 18px}
    .hero{padding:24px;color:#fff;background:linear-gradient(135deg,rgba(18,95,84,.95),rgba(15,92,138,.92));border-radius:24px;margin-bottom:22px}
    .hero h1{margin:0 0 6px;font-size:20px}
    .hero p{margin:0;opacity:.85;font-size:14px}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px}
    label{display:block;margin:10px 0 5px;font-size:13px;color:var(--muted)}
    textarea{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:12px;font:inherit;background:#fff;min-height:80px;resize:vertical}
    button{width:100%;padding:12px;margin-top:12px;border:none;border-radius:14px;cursor:pointer;font:inherit;font-weight:600;background:var(--accent);color:#fff}
    .result{margin-top:14px;padding:12px;border-radius:12px;font-size:13px;background:#f3ece2;white-space:pre-wrap}
    a{color:var(--accent)}
  </style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <h1>授权码换 Token</h1>
    <p>将从 115 获取的授权码粘贴到下方，换取 access token 并持久化到 data/tokens.json。</p>
  </section>
  <div class="panel">
    <label for="codeInput">授权码</label>
    <textarea id="codeInput" placeholder="粘贴授权码…"></textarea>
    <button id="submitBtn">提交授权码</button>
    <div class="result" id="result">等待提交…</div>
    <p style="margin-top:16px;font-size:13px;color:var(--muted)">
      也可以用 <a href="/tools/qr-login">扫码登录</a> 获取 Cookie。
    </p>
  </div>
</div>
<script>
document.getElementById("submitBtn").addEventListener("click", async () => {
  const code = document.getElementById("codeInput").value.trim();
  const result = document.getElementById("result");
  if (!code) { result.textContent = "请先粘贴授权码。"; return; }
  result.textContent = "提交中…";
  try {
    const r = await fetch("/tools/auth-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auth_code: code }),
    });
    const data = await r.json();
    result.textContent = data.message;
  } catch (e) {
    result.textContent = "请求失败：" + e.message;
  }
});
</script>
</body>
</html>"""
