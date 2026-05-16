from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["home"])


def _render_home_page(*, client_ready: bool = True, client_error: str | None = None) -> str:
    auth_banner = ""
    if not client_ready:
        err_text = f"原因：{client_error}" if client_error else "token 不存在或已失效"
        auth_banner = f"""
    <div style="background:#fff0ee;border:1px solid rgba(140,32,16,.22);border-radius:18px;padding:16px 20px;margin-bottom:18px;color:#8c2010;font-size:14px;line-height:1.6;">
      <strong>⚠ 115 账号未授权</strong>，{err_text}。<br>
      请通过 <a href="/auth-center/open-api-qr" style="color:#8c2010;font-weight:600;">Open API 扫码授权</a>
      完成授权后再使用。Cookie 扫码登录仍可用于独立的目录导出场景。
    </div>"""
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>统一工作台</title>
  <style>
    :root {
      --bg: #f6efe5;
      --card: #fffaf3;
      --ink: #1f2421;
      --muted: #5b645f;
      --accent: #0f5c8a;
      --accent-2: #115e59;
      --accent-soft: #dcebf4;
      --line: #ddd3c4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15,92,138,.12), transparent 28%),
        radial-gradient(circle at top right, rgba(17,94,89,.12), transparent 26%),
        linear-gradient(135deg, #f8f3ea 0%, #efe4d6 100%);
      min-height: 100vh;
    }
    .shell {
      max-width: 1240px;
      margin: 0 auto;
      padding: 32px 18px 48px;
    }
    .hero {
      border-radius: 28px;
      padding: 28px;
      color: #f8f4ee;
      background: linear-gradient(135deg, rgba(15,92,138,.96), rgba(17,94,89,.92));
      box-shadow: 0 22px 56px rgba(33,37,41,.14);
    }
    .hero h1 {
      margin: 0 0 10px;
      font-size: clamp(30px, 4vw, 46px);
      letter-spacing: .02em;
    }
    .hero p {
      margin: 0;
      max-width: 820px;
      line-height: 1.7;
      color: rgba(248,244,238,.88);
    }
    .meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .pill {
      border-radius: 999px;
      padding: 6px 12px;
      background: rgba(255,255,255,.12);
      color: rgba(255,255,255,.92);
      font-size: 12px;
      border: 1px solid rgba(255,255,255,.14);
    }
    .grid {
      margin-top: 22px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }
    .card, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 12px 28px rgba(33,37,41,.06);
    }
    .card {
      padding: 20px;
      display: grid;
      gap: 14px;
    }
    .card h2 {
      margin: 0;
      font-size: 20px;
    }
    .card p {
      margin: 0;
      line-height: 1.6;
      color: var(--muted);
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    a.button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 14px;
      border-radius: 14px;
      text-decoration: none;
      font-weight: 600;
      border: 1px solid transparent;
    }
    a.primary {
      background: var(--accent);
      color: white;
    }
    a.secondary {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(15,92,138,.18);
    }
    .panel {
      margin-top: 18px;
      padding: 20px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 18px;
    }
    .steps {
      display: grid;
      gap: 10px;
      color: var(--muted);
      line-height: 1.6;
    }
    .step {
      padding: 12px 14px;
      border-radius: 16px;
      background: #f5efe5;
      border: 1px solid #e7ddcf;
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <!-- __AUTH_BANNER__ -->
    <section class="hero">
      <h1>统一工作台</h1>
      <p>云端工作流程：115导出目录树，目录树提取关键词，目录树白名单关键词重建，生成整理计划，执行基于目录树的整理计划；<br>本地工作流程：生成本地目录树，执行本地清理工作，执行本地整理</p>
      <div class="meta">
        <span class="pill">导入 -> 提取 -> 治理 -> 执行</span>
        <span class="pill">默认 dry-run</span>
      </div>
    </section>

    <div class="grid">
      <section class="card">
        <h2>节点与导入</h2>
        <p>辅助查看目录树批次、节点列表和底层数据，用于排查导入或命中异常。</p>
        <div class="actions">
          <a class="button primary" href="/imports">导入批次</a>
        </div>
      </section>
      <section class="card">
        <h2>关键词提取器</h2>
        <p>适合导入目录树、手工关键词和正则提取，作为整个流程的起点。</p>
        <div class="actions">
          <a class="button primary" href="/extractor/keywords/workbench">打开提取器</a>
        </div>
      </section>

      <section class="card">
        <h2>关键词管理台</h2>
        <p>集中维护白名单、黑名单、标签、别名、命中重建和目录树命中排行。</p>
        <div class="actions">
          <a class="button primary" href="/keywords/workbench">打开关键词管理台</a>
        </div>
      </section>


      <section class="card">
        <h2>计划执行台</h2>
        <p>集中处理整理任务、生成计划和执行记录。默认先 dry-run，确认后再真实执行。</p>
        <div class="actions">
          <a class="button primary" href="/plans/workbench">打开计划执行台</a>
        </div>
      </section>

      <section class="card">
        <h2>噪声清理台</h2>
        <p>面向既有噪声文件规则的预览和删除入口，适合处理旧链路里的噪声样本清理。</p>
        <div class="actions">
          <a class="button primary" href="/cleanup/noise-files/workbench">打开噪声清理台</a>
        </div>
      </section>



      <section class="card">
        <h2>本地清理台</h2>
        <p>面向本地目录扫描，支持黑名单匹配、白名单豁免、旧杂项规则和删除后空目录清理。</p>
        <div class="actions">
          <a class="button primary" href="/cleanup/local-files/workbench">打开本地清理台</a>
        </div>
      </section>

      <section class="card">
        <h2>本地整理台</h2>
        <p>面向本地文件夹整理，按白名单关键词生成移动预览，再决定是否真实归档。</p>
        <div class="actions">
          <a class="button primary" href="/organize/local-folders/workbench">打开本地整理台</a>
        </div>
      </section>

      <section class="card">
        <h2>本地目录树导出</h2>
        <p>从本地路径生成与 115 目录树兼容的文本，并固定保存到工作区里的导出目录。</p>
        <div class="actions">
          <a class="button primary" href="/local-tree-export/workbench">打开目录树导出台</a>
        </div>
      </section>

      <section class="card">
        <h2>磁力下载台</h2>
        <p>从文章数据库搜索磁力资源，检查 115 重复后，批量提交离线下载任务。</p>
        <div class="actions">
          <a class="button primary" href="/magnet-tasks/workbench">打开磁力下载台</a>
        </div>
      </section>
    </div>

    <section class="panel">
      <h2>推荐流程</h2>
      <div class="steps">
        <div class="step">1. 先导入目录树，再在统一工作台选择对应分析入口。</div>
        <div class="step">2. 在关键词管理台做标准词、别名、命中和排行治理。</div>
        <div class="step">3. 进入计划执行台生成任务和计划，再优先 dry-run。</div>
        <div class="step">4. 只有白名单目录才允许真实执行或真实删除。</div>
      </div>
    </section>
  </div>
</body>
</html>
""".replace("<!-- __AUTH_BANNER__ -->", auth_banner)


@router.get("/", response_class=HTMLResponse)
@router.get("/workbench", response_class=HTMLResponse)
def home_workbench(request: Request) -> str:
    return _render_home_page(
        client_ready=getattr(request.app.state, "client_115_ready", False),
        client_error=getattr(request.app.state, "client_115_last_error", None),
    )
