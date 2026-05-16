from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.local_cleanup import (
    LocalCleanupDeleteRequest,
    LocalCleanupDeleteResponse,
    LocalCleanupScanRequest,
    LocalCleanupScanResponse,
)
from app.services.cleanup.local_cleanup_service import LocalCleanupService
from app.services.keywords.registry_service import KeywordRegistryService

router = APIRouter(prefix="/cleanup/local-files", tags=["local-cleanup"])


def _merged_blacklist_keywords(payload_keywords: list[str], db: Session) -> list[str]:
    service = KeywordRegistryService(db)
    entries, _ = service.list_entries(keyword_type="blacklist", status="active", limit=5000)

    merged: list[str] = []
    seen: set[str] = set()

    def append_keyword(value: str) -> None:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        merged.append(value.strip())

    for keyword in payload_keywords:
        append_keyword(keyword)

    for entry in entries:
        append_keyword(entry.canonical_name)
        for alias in entry.aliases:
            append_keyword(alias.alias)

    return merged


@router.post("/scan", response_model=LocalCleanupScanResponse)
def scan_local_files(payload: LocalCleanupScanRequest, db: Session = Depends(get_db)) -> LocalCleanupScanResponse:
    try:
        return LocalCleanupService().scan(
            root_path=payload.root_path,
            blacklist_keywords=_merged_blacklist_keywords(payload.blacklist_keywords, db),
            fuzzy_match=payload.fuzzy_match,
            suffix_filter=payload.suffix_filter,
            max_file_size_mb=payload.max_file_size_mb,
            include_files=payload.include_files,
            include_directories=payload.include_directories,
            max_results=payload.max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/delete", response_model=LocalCleanupDeleteResponse)
def delete_local_files(payload: LocalCleanupDeleteRequest) -> LocalCleanupDeleteResponse:
    try:
        return LocalCleanupService().delete(
            root_path=payload.root_path,
            paths=payload.paths,
            dry_run=payload.dry_run,
            confirm_delete=payload.confirm_delete,
            remove_empty_dirs=payload.remove_empty_dirs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workbench", response_class=HTMLResponse)
def local_cleanup_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>本地清理台</title>
  <style>
    :root {
      --bg: #f5efe6;
      --card: #fffaf2;
      --ink: #1c2320;
      --muted: #5d665f;
      --accent: #8a4b17;
      --accent-soft: #f1dfcf;
      --line: #ddd2c4;
      --danger: #8f2d23;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", sans-serif;
      background: linear-gradient(135deg, #f8f3eb 0%, #efe3d5 100%);
      color: var(--ink);
    }
    .shell { max-width: 1280px; margin: 0 auto; padding: 28px 18px 42px; }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 12px 28px rgba(33,37,41,.06);
    }
    .hero {
      padding: 24px;
      background: linear-gradient(135deg, rgba(138,75,23,.96), rgba(95,54,28,.92));
      color: #fff8f2;
    }
    .hero h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 40px); }
    .hero p { margin: 0; max-width: 860px; line-height: 1.65; color: rgba(255,248,242,.88); }
    .hero a {
      color: #fff8f2;
      display: inline-block;
      margin-top: 14px;
      text-decoration: none;
      font-weight: 600;
    }
    .grid {
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 18px;
      margin-top: 20px;
    }
    .panel { padding: 20px; }
    label { display: block; margin: 12px 0 6px; font-size: 13px; color: var(--muted); }
    input, textarea, button {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      font: inherit;
    }
    input, textarea { padding: 11px 12px; background: white; }
    textarea { min-height: 110px; resize: vertical; }
    button {
      padding: 12px;
      cursor: pointer;
      border: none;
      background: var(--accent);
      color: white;
      font-weight: 600;
    }
    button.secondary {
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(138,75,23,.16);
    }
    .inline {
      display: flex;
      gap: 10px;
      margin-top: 10px;
    }
    .inline button { flex: 1; }
    .path-picker {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .path-picker input { flex: 1; }
    .path-picker button { width: auto; white-space: nowrap; }
    .preset-row {
      display: flex;
      gap: 10px;
      margin-top: 8px;
    }
    .preset-row select {
      flex: 1;
      border-radius: 14px;
      border: 1px solid var(--line);
      padding: 11px 12px;
      background: white;
      font: inherit;
    }
    .preset-row button { width: auto; white-space: nowrap; }
    .box {
      margin-top: 14px;
      padding: 12px;
      border-radius: 16px;
      background: #f7efe6;
      white-space: pre-wrap;
      line-height: 1.6;
      font-size: 13px;
    }
    .list {
      display: grid;
      gap: 12px;
    }
    .item {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: white;
    }
    .item.delete { border-color: rgba(143,45,35,.22); }
    .item input { width: 18px; height: 18px; margin-top: 4px; }
    .name { font-weight: 700; }
    .path { word-break: break-all; font-size: 13px; line-height: 1.55; margin-top: 4px; }
    .reason { font-size: 12px; color: var(--muted); margin-top: 8px; }
    .tag {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      margin-right: 8px;
      background: #f1e4d6;
      color: var(--muted);
    }
    .tag.delete { background: #f7dedb; color: var(--danger); }
    @media (max-width: 920px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>本地清理台</h1>
      <p>面向本地目录的扫描与删除入口。它只根据黑名单关键词扫描文件和文件夹命中项，不再附带任何内置去重或杂项清理规则，默认先 dry-run，再决定是否真实删除。</p>
      <a href="/workbench">返回统一工作台</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <label for="rootPath">扫描根路径</label>
        <div class="path-picker">
          <input id="rootPath" placeholder="/Volumes/media/待整理" />
          <button type="button" class="secondary" id="pickRootPathBtn">选择目录</button>
        </div>
        <div class="preset-row">
          <select id="rootPathPreset"><option value="">选择预设路径</option></select>
          <button type="button" class="secondary" id="applyRootPresetBtn">使用预设</button>
        </div>

        <label for="blacklist">黑名单关键词</label>
        <textarea id="blacklist" placeholder="每行一个，支持文件名或路径片段"></textarea>

        <label for="suffixFilter">后缀过滤</label>
        <input id="suffixFilter" placeholder=".mp4,.txt,.nfo" />

        <label for="maxSize">最大文件大小 MB（0 表示不限）</label>
        <input id="maxSize" type="number" min="0" step="0.1" value="0" />

        <label><input id="includeDirs" type="checkbox" checked style="width:auto;margin-right:8px;" />扫描文件夹名</label>
        <label><input id="removeEmptyDirs" type="checkbox" checked style="width:auto;margin-right:8px;" />删除后清理空目录</label>
        <label><input id="confirmDelete" type="checkbox" style="width:auto;margin-right:8px;" />确认我知道这会执行真实删除</label>

        <div class="inline">
          <button id="scanBtn">扫描候选</button>
          <button id="selectDeleteBtn" class="secondary">全选 delete</button>
        </div>
        <div class="inline">
          <button id="dryRunBtn" class="secondary">Dry Run 删除</button>
          <button id="deleteBtn">真实删除</button>
        </div>
        <div class="box" id="statusBox">先输入根路径和关键词，再执行扫描。</div>
      </aside>

      <section class="panel">
        <div class="box" id="summaryBox">扫描结果会显示在这里。</div>
        <div class="list" id="resultList"></div>
      </section>
    </div>
  </div>

  <script>
    const state = { items: [] };

    function lines(id) {
      return document.getElementById(id).value
        .split(/\\n|,/)
        .map(item => item.trim())
        .filter(Boolean);
    }

    function payloadBase() {
      return {
        root_path: document.getElementById('rootPath').value.trim(),
        blacklist_keywords: lines('blacklist'),
        suffix_filter: lines('suffixFilter'),
        max_file_size_mb: Number(document.getElementById('maxSize').value || 0),
        include_directories: document.getElementById('includeDirs').checked,
        include_files: true,
        fuzzy_match: true,
        max_results: 1000
      };
    }

    function selectedPaths() {
      return [...document.querySelectorAll('input[data-role="pick"]:checked')].map(node => node.value);
    }

    function renderItems(items) {
      const root = document.getElementById('resultList');
      root.innerHTML = '';
      for (const item of items) {
        const article = document.createElement('article');
        article.className = `item ${item.decision}`;
        article.innerHTML = `
          <input type="checkbox" data-role="pick" value="${item.path}" ${item.decision === 'delete' ? 'checked' : ''} />
          <div>
            <div>
              <span class="tag ${item.decision}">${item.decision}</span>
              <span class="tag">${item.entry_type}</span>
            </div>
            <div class="name">${item.name}</div>
            <div class="path">${item.path}</div>
            <div class="reason">${item.reasons.join(' | ') || '无'}</div>
          </div>
        `;
        root.appendChild(article);
      }
    }

    async function scan() {
      const response = await fetch('/cleanup/local-files/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payloadBase())
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '扫描失败';
        return;
      }
      state.items = body.items || [];
      document.getElementById('statusBox').textContent = '扫描完成，现在展示的都是黑名单命中的 delete 候选。';
      document.getElementById('summaryBox').textContent =
        `根路径: ${body.root_path}\\n候选总数: ${body.total_candidates}\\ndelete: ${body.total_delete_candidates}\\nskip/truncated: ${body.skipped_count}`;
      renderItems(state.items);
    }
    async function chooseDirectory(inputId, title) {
      const input = document.getElementById(inputId);
      const response = await fetch('/system/path-picker/directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, initial_path: input.value.trim() || null })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '打开目录选择失败';
        return;
      }
      input.value = body.path;
    }
    async function loadPresets() {
      const response = await fetch('/system/path-picker/presets');
      const body = await response.json();
      const select = document.getElementById('rootPathPreset');
      select.innerHTML = '<option value="">选择预设路径</option>';
      for (const item of body) {
        const option = document.createElement('option');
        option.value = item.path;
        option.textContent = `${item.label} · ${item.path}`;
        select.appendChild(option);
      }
    }

    async function loadBlacklistKeywords() {
      const response = await fetch('/keywords?keyword_type=blacklist&status=active&limit=5000');
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '加载黑名单失败';
        return;
      }
      const keywords = [];
      for (const entry of body.entries || []) {
        if (entry.canonical_name) keywords.push(entry.canonical_name);
        for (const alias of entry.aliases || []) {
          if (alias.alias) keywords.push(alias.alias);
        }
      }
      const uniqueKeywords = [...new Set(keywords.map(item => item.trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
      document.getElementById('blacklist').value = uniqueKeywords.join('\\n');
      document.getElementById('statusBox').textContent = uniqueKeywords.length
        ? `已自动载入 ${uniqueKeywords.length} 个黑名单关键词，扫描时会一并参与匹配。`
        : '当前数据库里还没有 active 黑名单关键词，可手动输入后扫描。';
    }

    async function executeDelete(dryRun) {
      const response = await fetch('/cleanup/local-files/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_path: document.getElementById('rootPath').value.trim(),
          paths: selectedPaths(),
          dry_run: dryRun,
          confirm_delete: dryRun ? false : document.getElementById('confirmDelete').checked,
          remove_empty_dirs: document.getElementById('removeEmptyDirs').checked
        })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '执行失败';
        return;
      }
      document.getElementById('summaryBox').textContent =
        `${dryRun ? 'Dry Run' : '真实删除'} 完成\\n处理数量: ${body.total_processed}/${body.total_requested}\\n空目录处理: ${body.removed_empty_dirs}`;
      document.getElementById('statusBox').textContent = body.items
        .map(item => `${item.status} | ${item.path}${item.error_message ? ` | ${item.error_message}` : ''}`)
        .join('\\n');
    }

    document.getElementById('scanBtn').addEventListener('click', scan);
    document.getElementById('pickRootPathBtn').addEventListener('click', () => chooseDirectory('rootPath', '选择本地清理根路径'));
    document.getElementById('applyRootPresetBtn').addEventListener('click', () => {
      const value = document.getElementById('rootPathPreset').value;
      if (value) document.getElementById('rootPath').value = value;
    });
    loadPresets();
    loadBlacklistKeywords();
    document.getElementById('selectDeleteBtn').addEventListener('click', () => {
      for (const checkbox of document.querySelectorAll('input[data-role="pick"]')) {
        const card = checkbox.closest('.item');
        checkbox.checked = card && card.classList.contains('delete');
      }
    });
    document.getElementById('dryRunBtn').addEventListener('click', () => executeDelete(true));
    document.getElementById('deleteBtn').addEventListener('click', () => executeDelete(false));
  </script>
</body>
</html>
"""
