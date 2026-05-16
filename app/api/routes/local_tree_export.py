from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.schemas.local_tree_export import (
    LocalTreeExportFileResponse,
    LocalTreeExportRequest,
    LocalTreeExportResponse,
)
from app.services.local_tree_export_service import LocalTreeExportService

router = APIRouter(prefix="/local-tree-export", tags=["local-tree-export"])


@router.post("/generate", response_model=LocalTreeExportResponse)
def generate_local_tree(payload: LocalTreeExportRequest) -> LocalTreeExportResponse:
    try:
        return LocalTreeExportService().export(
            root_path=payload.root_path,
            root_name=payload.root_name,
            output_name=payload.output_name,
            include_files=payload.include_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/files", response_model=list[LocalTreeExportFileResponse])
def list_local_tree_exports() -> list[LocalTreeExportFileResponse]:
    return LocalTreeExportService().list_exports()


@router.get("/workbench", response_class=HTMLResponse)
def local_tree_export_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>本地目录树导出</title>
  <style>
    :root {
      --bg: #f5efe6;
      --card: #fffaf2;
      --ink: #1c2320;
      --muted: #5d665f;
      --accent: #0f5c8a;
      --accent-soft: #dcebf4;
      --line: #ddd2c4;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "PingFang SC", "Noto Sans SC", sans-serif; background: linear-gradient(135deg, #f8f3eb 0%, #efe3d5 100%); color: var(--ink); }
    .shell { max-width: 1280px; margin: 0 auto; padding: 28px 18px 42px; }
    .hero, .panel { background: var(--card); border: 1px solid var(--line); border-radius: 24px; box-shadow: 0 12px 28px rgba(33,37,41,.06); }
    .hero { padding: 24px; background: linear-gradient(135deg, rgba(15,92,138,.95), rgba(17,94,89,.92)); color: #fff8f2; }
    .hero h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 40px); }
    .hero p { margin: 0; max-width: 860px; line-height: 1.65; color: rgba(255,248,242,.88); }
    .hero a { color: #fff8f2; display: inline-block; margin-top: 14px; text-decoration: none; font-weight: 600; }
    .grid { display: grid; grid-template-columns: 360px 1fr; gap: 18px; margin-top: 20px; }
    .panel { padding: 20px; }
    label { display: block; margin: 12px 0 6px; font-size: 13px; color: var(--muted); }
    input, button { width: 100%; border-radius: 14px; border: 1px solid var(--line); font: inherit; }
    input { padding: 11px 12px; background: white; }
    button { padding: 12px; cursor: pointer; border: none; background: var(--accent); color: white; font-weight: 600; }
    button.secondary { background: var(--accent-soft); color: var(--accent); border: 1px solid rgba(15,92,138,.18); }
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
    .item { padding: 14px; border-radius: 18px; border: 1px solid var(--line); background: white; }
    .name { font-weight: 700; }
    .path { word-break: break-all; font-size: 13px; line-height: 1.55; margin-top: 4px; }
    @media (max-width: 920px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>本地目录树导出</h1>
      <p>把本地路径扫描成和 115 目录树文本兼容的层级格式，并固定保存到 `collect/generated_trees/` 目录。</p>
      <a href="/workbench">返回统一工作台</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <label for="rootPath">本地根路径</label>
        <div class="path-picker">
          <input id="rootPath" placeholder="/data/source-root" />
          <button type="button" class="secondary" id="pickRootPathBtn">选择目录</button>
        </div>
        <div class="preset-row">
          <select id="rootPathPreset"><option value="">选择预设路径</option></select>
          <button type="button" class="secondary" id="applyRootPresetBtn">使用预设</button>
        </div>
        <label for="rootName">目录树根名称</label>
        <input id="rootName" placeholder="留空则默认用最后一级目录名" />
        <label for="outputName">输出文件名</label>
        <input id="outputName" placeholder="留空则自动生成时间戳文件名" />
        <div class="inline">
          <button id="generateBtn">生成目录树</button>
          <button class="secondary" id="refreshBtn">刷新文件列表</button>
        </div>
        <div class="box" id="statusBox">填写本地路径后点击生成，文件会固定保存到 `collect/generated_trees/`。</div>
      </aside>
      <section class="panel">
        <div class="box" id="summaryBox">导出结果会显示在这里。</div>
        <div class="list" id="fileList"></div>
      </section>
    </div>
  </div>
  <script>
    async function refreshFiles() {
      const response = await fetch('/local-tree-export/files');
      const body = await response.json();
      const root = document.getElementById('fileList');
      root.innerHTML = '';
      for (const item of body) {
        const article = document.createElement('article');
        article.className = 'item';
        article.innerHTML = `
          <div class="name">${item.filename}</div>
          <div class="path">${item.path}</div>
          <div class="path">size: ${item.size_bytes} bytes</div>
        `;
        root.appendChild(article);
      }
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
    async function generate() {
      const response = await fetch('/local-tree-export/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_path: document.getElementById('rootPath').value.trim(),
          root_name: document.getElementById('rootName').value.trim() || null,
          output_name: document.getElementById('outputName').value.trim() || null,
          include_files: true
        })
      });
      const body = await response.json();
      if (!response.ok) {
        document.getElementById('statusBox').textContent = body.detail || '生成失败';
        return;
      }
      document.getElementById('summaryBox').textContent =
        `根路径: ${body.root_path}\\n根名称: ${body.root_name}\\n输出文件: ${body.output_filename}\\n输出路径: ${body.output_path}\\n目录数: ${body.folder_count}\\n文件数: ${body.file_count}\\n总行数: ${body.line_count}`;
      document.getElementById('statusBox').textContent = '目录树已生成并保存到固定目录。';
      await refreshFiles();
    }
    document.getElementById('generateBtn').addEventListener('click', generate);
    document.getElementById('pickRootPathBtn').addEventListener('click', () => chooseDirectory('rootPath', '选择目录树导出根路径'));
    document.getElementById('applyRootPresetBtn').addEventListener('click', () => {
      const value = document.getElementById('rootPathPreset').value;
      if (value) document.getElementById('rootPath').value = value;
    });
    document.getElementById('refreshBtn').addEventListener('click', refreshFiles);
    loadPresets();
    refreshFiles();
  </script>
</body>
</html>
"""
