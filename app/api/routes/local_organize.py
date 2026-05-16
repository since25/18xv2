from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.api.deps import get_db
from app.schemas.local_organize import (
    LocalOrganizeDebugRequest,
    LocalOrganizeDebugResponse,
    LocalOrganizeExecuteRequest,
    LocalOrganizeExecuteResponse,
    LocalOrganizeScanRequest,
    LocalOrganizeScanResponse,
)
from app.services.local_organize_service import LocalOrganizeService
from sqlalchemy.orm import Session

router = APIRouter(prefix="/organize/local-folders", tags=["local-organize"])


@router.post("/scan", response_model=LocalOrganizeScanResponse)
def scan_local_folders(payload: LocalOrganizeScanRequest, db: Session = Depends(get_db)) -> LocalOrganizeScanResponse:
    try:
        return LocalOrganizeService(db).scan(
            root_path=payload.root_path,
            target_root=payload.target_root,
            whitelist_keywords=payload.whitelist_keywords,
            fuzzy_match=payload.fuzzy_match,
            max_results=payload.max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/execute", response_model=LocalOrganizeExecuteResponse)
def execute_local_organize(
    payload: LocalOrganizeExecuteRequest, db: Session = Depends(get_db)
) -> LocalOrganizeExecuteResponse:
    try:
        return LocalOrganizeService(db).execute(
            root_path=payload.root_path,
            target_root=payload.target_root,
            items=payload.items,
            dry_run=payload.dry_run,
            confirm_execute=payload.confirm_execute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/debug-match", response_model=LocalOrganizeDebugResponse)
def debug_local_organize_match(
    payload: LocalOrganizeDebugRequest, db: Session = Depends(get_db)
) -> LocalOrganizeDebugResponse:
    try:
        return LocalOrganizeService(db).debug_match(
            folder_name=payload.folder_name,
            whitelist_keywords=payload.whitelist_keywords,
            fuzzy_match=payload.fuzzy_match,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workbench", response_class=HTMLResponse)
def local_organize_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>本地整理台</title>
  <style>
    :root {
      --bg: #f5efe6;
      --card: #fffaf2;
      --ink: #1c2320;
      --muted: #5d665f;
      --accent: #115e59;
      --accent-soft: #dcefe9;
      --line: #ddd2c4;
      --warn: #9a6700;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "PingFang SC", "Noto Sans SC", sans-serif; background: linear-gradient(135deg, #f8f3eb 0%, #efe3d5 100%); color: var(--ink); }
    .shell { max-width: 1280px; margin: 0 auto; padding: 28px 18px 42px; }
    .hero, .panel { background: var(--card); border: 1px solid var(--line); border-radius: 24px; box-shadow: 0 12px 28px rgba(33,37,41,.06); }
    .hero { padding: 24px; background: linear-gradient(135deg, rgba(17,94,89,.95), rgba(15,92,138,.92)); color: #fff8f2; }
    .hero h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 40px); }
    .hero p { margin: 0; max-width: 860px; line-height: 1.65; color: rgba(255,248,242,.88); }
    .hero a { color: #fff8f2; display: inline-block; margin-top: 14px; text-decoration: none; font-weight: 600; }
    .grid { display: grid; grid-template-columns: 360px 1fr; gap: 18px; margin-top: 20px; }
    .panel { padding: 20px; }
    label { display: block; margin: 12px 0 6px; font-size: 13px; color: var(--muted); }
    input, textarea, button { width: 100%; border-radius: 14px; border: 1px solid var(--line); font: inherit; }
    input, textarea { padding: 11px 12px; background: white; }
    textarea { min-height: 120px; resize: vertical; }
    button { padding: 12px; cursor: pointer; border: none; background: var(--accent); color: white; font-weight: 600; }
    button.secondary { background: var(--accent-soft); color: var(--accent); border: 1px solid rgba(17,94,89,.18); }
    .inline { display: flex; gap: 10px; margin-top: 10px; }
    .inline button { flex: 1; }
    .path-picker { display: flex; gap: 10px; align-items: center; }
    .path-picker input { flex: 1; }
    .path-picker button { width: auto; white-space: nowrap; }
    .preset-row { display: flex; gap: 10px; margin-top: 8px; }
    .preset-row select {
      flex: 1;
      border-radius: 14px;
      border: 1px solid var(--line);
      padding: 11px 12px;
      background: white;
      font: inherit;
    }
    .preset-row button { width: auto; white-space: nowrap; }
    .box { margin-top: 14px; padding: 12px; border-radius: 16px; background: #f7efe6; white-space: pre-wrap; line-height: 1.6; font-size: 13px; }
    .list { display: grid; gap: 12px; }
    .item { display: flex; gap: 12px; align-items: flex-start; padding: 14px; border-radius: 18px; border: 1px solid var(--line); background: white; }
    .item.move { border-color: rgba(17,94,89,.22); }
    .item.ambiguous { border-color: rgba(154,103,0,.24); }
    .item input { width: 18px; height: 18px; margin-top: 4px; }
    .name { font-weight: 700; }
    .path { word-break: break-all; font-size: 13px; line-height: 1.55; margin-top: 4px; }
    .reason { font-size: 12px; color: var(--muted); margin-top: 8px; }
    .tag { display: inline-block; border-radius: 999px; padding: 4px 10px; font-size: 12px; margin-right: 8px; background: #f1e4d6; color: var(--muted); }
    .tag.move { background: #dcefe9; color: var(--accent); }
    .tag.ambiguous { background: #f4e7cc; color: var(--warn); }
    @media (max-width: 920px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>本地整理台</h1>
      <p>按白名单关键词扫描本地文件夹，生成移动预览，再决定是否真实整理。默认会自动读取数据库里的 active whitelist；当前只匹配“当前目录名”，不拿整条路径做匹配。</p>
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
        <label for="targetRoot">整理目标根路径</label>
        <div class="path-picker">
          <input id="targetRoot" placeholder="/Volumes/media/已整理" />
          <button type="button" class="secondary" id="pickTargetRootBtn">选择目录</button>
        </div>
        <div class="preset-row">
          <select id="targetRootPreset"><option value="">选择预设路径</option></select>
          <button type="button" class="secondary" id="applyTargetPresetBtn">使用预设</button>
        </div>
        <label for="whitelist">白名单关键词</label>
        <textarea id="whitelist" placeholder="可留空；留空时默认读取数据库 active whitelist"></textarea>
        <label for="debugFolderName">匹配调试目录名</label>
        <input id="debugFolderName" placeholder="粘贴一个目录名，查看它命中了哪个 whitelist 条目" />
        <label><input id="confirmExecute" type="checkbox" style="width:auto;margin-right:8px;" />确认我知道这会执行真实移动</label>
        <div class="inline">
          <button id="scanBtn">扫描整理候选</button>
          <button class="secondary" id="selectMoveBtn">全选 move</button>
        </div>
        <div class="inline">
          <button class="secondary" id="debugBtn">调试单个目录名</button>
        </div>
        <div class="inline">
          <button class="secondary" id="dryRunBtn">Dry Run 整理</button>
          <button id="executeBtn">真实整理</button>
        </div>
        <div class="box" id="statusBox">先输入扫描根路径和整理目标路径，再执行扫描。白名单可留空，默认读数据库。</div>
      </aside>
      <section class="panel">
        <div class="box" id="summaryBox">整理预览会显示在这里。</div>
        <div class="list" id="resultList"></div>
      </section>
    </div>
  </div>
  <script>
    const state = { items: [] };
    function lines(id) {
      return document.getElementById(id).value.split(/\\n|,/).map(item => item.trim()).filter(Boolean);
    }
    function selectedItems() {
      return [...document.querySelectorAll('input[data-role="pick"]:checked')].map(node => {
        return state.items.find(item => item.source_path === node.value);
      }).filter(Boolean);
    }
    function renderItems(items) {
      const root = document.getElementById('resultList');
      root.innerHTML = '';
      for (const item of items) {
        const article = document.createElement('article');
        article.className = `item ${item.status}`;
        article.innerHTML = `
          <input type="checkbox" data-role="pick" value="${item.source_path}" ${item.status === 'move' ? 'checked' : ''} />
          <div>
            <div><span class="tag ${item.status}">${item.status}</span></div>
            <div class="name">${item.source_name}</div>
            <div class="path">${item.source_path}</div>
            <div class="path">=> ${item.target_path || '-'}</div>
            <div class="reason">${item.reasons.join(' | ') || '无'}</div>
          </div>
        `;
        root.appendChild(article);
      }
    }
    async function scan() {
      const response = await fetch('/organize/local-folders/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_path: document.getElementById('rootPath').value.trim(),
          target_root: document.getElementById('targetRoot').value.trim(),
          whitelist_keywords: lines('whitelist'),
          fuzzy_match: true,
          max_results: 1000
        })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '扫描失败';
        return;
      }
      state.items = body.items || [];
      document.getElementById('summaryBox').textContent =
        `根路径: ${body.root_path}\\n目标路径: ${body.target_root}\\n候选总数: ${body.total_candidates}\\nmove: ${body.total_move_candidates}\\nambiguous: ${body.total_ambiguous}\\nskip: ${body.skipped_count}\\ntruncated: ${body.truncated_count}`;
      document.getElementById('statusBox').textContent = '扫描完成，可以先 review 再 dry-run。';
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
      for (const selectId of ['rootPathPreset', 'targetRootPreset']) {
        const select = document.getElementById(selectId);
        select.innerHTML = '<option value="">选择预设路径</option>';
        for (const item of body) {
          const option = document.createElement('option');
          option.value = item.path;
          option.textContent = `${item.label} · ${item.path}`;
          select.appendChild(option.cloneNode(true));
        }
      }
    }
    async function debugMatch() {
      const folderName = document.getElementById('debugFolderName').value.trim();
      if (!folderName) {
        document.getElementById('statusBox').textContent = '请先输入要调试的目录名。';
        return;
      }
      const response = await fetch('/organize/local-folders/debug-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder_name: folderName,
          whitelist_keywords: lines('whitelist'),
          fuzzy_match: true
        })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '调试失败';
        return;
      }
      const linesOut = [
        `folder_name: ${body.folder_name}`,
        `normalized: ${body.normalized_folder_name}`,
        `status: ${body.status}`,
        `matched_rule_count: ${body.matched_rule_count}`,
      ];
      for (const rule of body.matched_rules || []) {
        linesOut.push(`- entry_id: ${rule.keyword_entry_id ?? '-'}`);
        linesOut.push(`  canonical: ${rule.canonical_name}`);
        linesOut.push(`  matched_terms: ${rule.matched_terms.join(' | ')}`);
        linesOut.push(`  all_terms: ${rule.all_terms.join(' | ')}`);
      }
      document.getElementById('statusBox').textContent = linesOut.join('\\n');
    }
    async function execute(dryRun) {
      const response = await fetch('/organize/local-folders/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_path: document.getElementById('rootPath').value.trim(),
          target_root: document.getElementById('targetRoot').value.trim(),
          items: selectedItems(),
          dry_run: dryRun,
          confirm_execute: dryRun ? false : document.getElementById('confirmExecute').checked
        })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '执行失败';
        return;
      }
      document.getElementById('statusBox').textContent = body.items.map(item => `${item.status} | ${item.source_path} => ${item.target_path}${item.error_message ? ` | ${item.error_message}` : ''}`).join('\\n');
    }
    document.getElementById('scanBtn').addEventListener('click', scan);
    document.getElementById('pickRootPathBtn').addEventListener('click', () => chooseDirectory('rootPath', '选择本地整理扫描根路径'));
    document.getElementById('pickTargetRootBtn').addEventListener('click', () => chooseDirectory('targetRoot', '选择本地整理目标路径'));
    document.getElementById('applyRootPresetBtn').addEventListener('click', () => {
      const value = document.getElementById('rootPathPreset').value;
      if (value) document.getElementById('rootPath').value = value;
    });
    document.getElementById('applyTargetPresetBtn').addEventListener('click', () => {
      const value = document.getElementById('targetRootPreset').value;
      if (value) document.getElementById('targetRoot').value = value;
    });
    document.getElementById('debugBtn').addEventListener('click', debugMatch);
    loadPresets();
    document.getElementById('selectMoveBtn').addEventListener('click', () => {
      for (const checkbox of document.querySelectorAll('input[data-role="pick"]')) {
        const card = checkbox.closest('.item');
        checkbox.checked = card && card.classList.contains('move');
      }
    });
    document.getElementById('dryRunBtn').addEventListener('click', () => execute(true));
    document.getElementById('executeBtn').addEventListener('click', () => execute(false));
  </script>
</body>
</html>
"""
