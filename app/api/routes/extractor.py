from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.extractor import (
    ExtractedKeywordListResponse,
    ExtractedKeywordResponse,
    ManualPathRegexExtractRequest,
    ManualKeywordExtractRequest,
    RegexExtractPreviewResponse,
    RegexKeywordExtractRequest,
    RegexMatchPreviewResponse,
)
from app.services.classifier.keyword_extractor_service import KeywordExtractorService
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

router = APIRouter(prefix="/extractor", tags=["extractor"])


def _resolve_keyword_candidates(
    db: Session,
    items: list[tuple[str, int, str, list[str]]],
) -> tuple[list[dict], dict[str, dict]]:
    registry = KeywordRegistryService(db)
    ignore_entries, _ = registry.list_entries(keyword_type="ignore", status="active", limit=5000)
    ignore_tokens = {
        alias.alias_normalized
        for entry in ignore_entries
        for alias in entry.aliases
    } | {entry.canonical_name_normalized for entry in ignore_entries}

    resolved_items: list[dict] = []
    resolution_by_keyword: dict[str, dict] = {}

    for keyword, count, source, examples in items:
        normalized = normalize_keyword_text(keyword)
        if normalized in ignore_tokens:
            resolution = {
                "keyword": keyword,
                "count": count,
                "source": source,
                "examples": examples,
                "match_status": "ignored",
                "matched_entry_id": None,
                "matched_canonical_name": None,
                "similar_score": None,
            }
        else:
            matched_entry = registry.find_entry_by_keyword(normalized)
            if matched_entry is not None:
                resolution = {
                    "keyword": keyword,
                    "count": count,
                    "source": source,
                    "examples": examples,
                    "match_status": "existing",
                    "matched_entry_id": matched_entry.id,
                    "matched_canonical_name": matched_entry.canonical_name,
                    "similar_score": None,
                }
            else:
                similar_items = registry.suggest_similar(
                    [keyword],
                    threshold=0.75,
                    limit=1,
                    keyword_types=["whitelist", "tag"],
                )
                similar = similar_items[0] if similar_items else None
                resolution = {
                    "keyword": keyword,
                    "count": count,
                    "source": source,
                    "examples": examples,
                    "match_status": "similar" if similar else "new",
                    "matched_entry_id": similar.matched_entry_id if similar else None,
                    "matched_canonical_name": similar.matched_canonical_name if similar else None,
                    "similar_score": similar.score if similar else None,
                }

        resolved_items.append(resolution)
        resolution_by_keyword[keyword] = resolution

    return resolved_items, resolution_by_keyword


def _build_extracted_response(
    payload: ManualKeywordExtractRequest | RegexKeywordExtractRequest | ManualPathRegexExtractRequest,
    total_nodes: int,
    raw_items: list[tuple[str, int, str, list[str]]],
    db: Session,
) -> ExtractedKeywordListResponse:
    resolved_items, _ = _resolve_keyword_candidates(db, raw_items)
    actionable_items = [item for item in resolved_items if item["match_status"] in {"new", "similar"}]
    return ExtractedKeywordListResponse(
        import_id=payload.import_id,
        total_nodes=total_nodes,
        total_keywords=len(actionable_items),
        total_actionable_keywords=len(actionable_items),
        total_existing_keywords=sum(1 for item in resolved_items if item["match_status"] == "existing"),
        total_ignored_keywords=sum(1 for item in resolved_items if item["match_status"] == "ignored"),
        total_blacklisted_keywords=0,
        total_similar_keywords=sum(1 for item in resolved_items if item["match_status"] == "similar"),
        keywords=[ExtractedKeywordResponse(**item) for item in actionable_items[: payload.limit]],
    )


@router.post("/keywords/manual", response_model=ExtractedKeywordListResponse)
def extract_manual_keywords(
    payload: ManualKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    keywords, total_nodes = service.extract_manual_keywords(
        import_id=payload.import_id,
        keywords=payload.keywords,
        node_ids=payload.node_ids,
        case_sensitive=payload.case_sensitive,
        limit=payload.limit,
    )
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )


@router.post("/keywords/regex", response_model=ExtractedKeywordListResponse)
def extract_regex_keywords(
    payload: RegexKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    try:
        keywords, _, total_nodes = service.extract_regex_keywords(
            import_id=payload.import_id,
            pattern=payload.pattern,
            node_ids=payload.node_ids,
            flags=payload.flags,
            group_index=payload.group_index,
            min_count=payload.min_count,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )


@router.post("/keywords/regex-preview", response_model=RegexExtractPreviewResponse)
def preview_regex_keywords(
    payload: RegexKeywordExtractRequest,
    db: Session = Depends(get_db),
) -> RegexExtractPreviewResponse:
    service = KeywordExtractorService(db)
    try:
        _, preview, total_nodes = service.extract_regex_keywords(
            import_id=payload.import_id,
            pattern=payload.pattern,
            node_ids=payload.node_ids,
            flags=payload.flags,
            group_index=payload.group_index,
            min_count=payload.min_count,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, resolution_by_keyword = _resolve_keyword_candidates(
        db,
        [
            (
                item.extracted_keyword,
                1,
                "regex",
                [item.raw_path],
            )
            for item in preview
        ],
    )
    actionable_preview = [item for item in preview if resolution_by_keyword[item.extracted_keyword]["match_status"] in {"new", "similar"}]
    return RegexExtractPreviewResponse(
        import_id=payload.import_id,
        pattern=payload.pattern,
        flags=payload.flags,
        total_nodes=total_nodes,
        total_matches=len(preview),
        total_actionable_matches=len(actionable_preview),
        preview=[
            RegexMatchPreviewResponse(
                node_id=item.node_id,
                folder_name=item.folder_name,
                raw_path=item.raw_path,
                extracted_keyword=item.extracted_keyword,
                match_status=resolution_by_keyword[item.extracted_keyword]["match_status"],
                matched_entry_id=resolution_by_keyword[item.extracted_keyword]["matched_entry_id"],
                matched_canonical_name=resolution_by_keyword[item.extracted_keyword]["matched_canonical_name"],
                similar_score=resolution_by_keyword[item.extracted_keyword]["similar_score"],
            )
            for item in actionable_preview[: payload.limit]
        ],
    )


@router.post("/keywords/manual-path-regex", response_model=RegexExtractPreviewResponse)
def preview_manual_path_regex_keywords(
    payload: ManualPathRegexExtractRequest,
    db: Session = Depends(get_db),
) -> RegexExtractPreviewResponse:
    service = KeywordExtractorService(db)
    try:
        _, preview, total_nodes = service.extract_regex_keywords_from_path(
            raw_path=payload.raw_path,
            pattern=payload.pattern,
            flags=payload.flags,
            group_index=payload.group_index,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, resolution_by_keyword = _resolve_keyword_candidates(
        db,
        [
            (
                item.extracted_keyword,
                1,
                "manual_path_regex",
                [item.raw_path],
            )
            for item in preview
        ],
    )
    actionable_preview = [item for item in preview if resolution_by_keyword[item.extracted_keyword]["match_status"] in {"new", "similar"}]
    return RegexExtractPreviewResponse(
        import_id=payload.import_id,
        pattern=payload.pattern,
        flags=payload.flags,
        total_nodes=total_nodes,
        total_matches=len(preview),
        total_actionable_matches=len(actionable_preview),
        preview=[
            RegexMatchPreviewResponse(
                node_id=item.node_id,
                folder_name=item.folder_name,
                raw_path=item.raw_path,
                extracted_keyword=item.extracted_keyword,
                match_status=resolution_by_keyword[item.extracted_keyword]["match_status"],
                matched_entry_id=resolution_by_keyword[item.extracted_keyword]["matched_entry_id"],
                matched_canonical_name=resolution_by_keyword[item.extracted_keyword]["matched_canonical_name"],
                similar_score=resolution_by_keyword[item.extracted_keyword]["similar_score"],
            )
            for item in actionable_preview[: payload.limit]
        ],
    )


@router.post("/keywords/manual-path-regex/summary", response_model=ExtractedKeywordListResponse)
def extract_manual_path_regex_keywords(
    payload: ManualPathRegexExtractRequest,
    db: Session = Depends(get_db),
) -> ExtractedKeywordListResponse:
    service = KeywordExtractorService(db)
    try:
        keywords, _, total_nodes = service.extract_regex_keywords_from_path(
            raw_path=payload.raw_path,
            pattern=payload.pattern,
            flags=payload.flags,
            group_index=payload.group_index,
            limit=payload.limit,
        )
    except (ValueError, re.error) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_extracted_response(
        payload,
        total_nodes,
        [(item.keyword, item.count, item.source, item.examples) for item in keywords],
        db,
    )


@router.get("/keywords/workbench", response_class=HTMLResponse)
def extractor_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>关键词提取器</title>
  <style>
    :root {
      --bg: #f4efe6;
      --card: #fffaf2;
      --ink: #1e2320;
      --muted: #606963;
      --accent: #0f766e;
      --accent-soft: #d7ece8;
      --line: #ddd3c4;
      --warn: #b45309;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background: linear-gradient(135deg, #f8f2e8 0%, #efe5d7 100%);
    }
    .shell { max-width: 1280px; margin: 0 auto; padding: 28px 18px 40px; }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 26px;
      box-shadow: 0 12px 28px rgba(33, 37, 41, .07);
    }
    .hero {
      padding: 26px;
      background: linear-gradient(135deg, rgba(15,118,110,.95), rgba(34,51,46,.9));
      color: #f8f4ee;
    }
    .hero h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 42px); }
    .hero p { margin: 0; max-width: 820px; line-height: 1.6; color: rgba(248,244,238,.88); }
    .grid {
      margin-top: 22px;
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 18px;
    }
    .panel { padding: 20px; }
    h2 { margin: 0 0 14px; font-size: 18px; }
    label { display: block; margin: 12px 0 6px; font-size: 13px; color: var(--muted); }
    input, textarea, select, button {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      font: inherit;
    }
    input, textarea, select { padding: 12px 14px; background: #fff; }
    textarea { min-height: 110px; resize: vertical; }
    button {
      padding: 12px 14px;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border: none;
      font-weight: 600;
    }
    a.button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 0 14px;
      border-radius: 14px;
      text-decoration: none;
      font-weight: 600;
      background: rgba(255,255,255,.14);
      color: #fff;
      border: 1px solid rgba(255,255,255,.18);
    }
    button.secondary {
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(15,118,110,.18);
    }
    .actions, .subactions {
      display: flex;
      gap: 10px;
      margin-top: 14px;
    }
    .actions button, .subactions button { flex: 1; }
    .hint, .status, .summary {
      margin-top: 14px;
      padding: 12px;
      border-radius: 16px;
      background: #f3ece2;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
    }
    .stack { display: grid; gap: 16px; }
    .card {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(244,237,226,.98));
    }
    .card h3 { margin: 0 0 10px; font-size: 20px; }
    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .badge {
      background: #ece4d7;
      color: var(--muted);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
    }
    .examples, .preview-list {
      font-size: 13px;
      line-height: 1.5;
      color: var(--muted);
      display: grid;
      gap: 8px;
    }
    .preview-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: #fff;
    }
    .preview-item strong { color: var(--ink); }
    .section-title {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }
    .hero-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }
    .toolbar {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin: 14px 0 16px;
    }
    .toolbar-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .toolbar-row button { flex: 1; min-width: 140px; }
    .keyword-row {
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }
    .keyword-body {
      flex: 1;
    }
    .keyword-row input[type="checkbox"] {
      width: 18px;
      height: 18px;
      margin-top: 4px;
      accent-color: var(--accent);
    }
    .keyword-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    .keyword-actions button {
      flex: 1;
      min-width: 140px;
    }
    .library-list {
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }
    .library-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: #fff;
    }
    .library-item-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 8px;
    }
    .library-meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .pager {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: flex-end;
      margin: 12px 0 4px;
    }
    .pager button {
      width: auto;
      min-width: 96px;
      padding: 8px 12px;
    }
    .pager span {
      color: var(--muted);
      font-size: 13px;
    }
    .floating-actions {
      position: fixed;
      right: 18px;
      top: 120px;
      width: 220px;
      display: grid;
      gap: 10px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 250, 242, 0.96);
      box-shadow: 0 12px 28px rgba(33, 37, 41, .12);
      backdrop-filter: blur(8px);
      z-index: 10;
    }
    .floating-actions .floating-title {
      font-size: 13px;
      color: var(--muted);
      line-height: 1.5;
    }
    .floating-actions .selection-count {
      font-weight: 700;
      color: var(--accent);
    }
    @media (max-width: 940px) {
      .grid { grid-template-columns: 1fr; }
      .floating-actions {
        position: static;
        width: auto;
        margin-top: 14px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>关键词提取器</h1>
      <p>这是一套独立于现有候选词分析的提取工作台。你可以手动导入关键词做命中校验，也可以通过可视化正则从目录树中的文件夹名称直接抽取关键词。提取阶段会自动过滤已存在关键词和忽略清单，只把需要人工确认的新词或相似词留下来。</p>
      <div class="hero-actions">
        <a class="button-link" href="/workbench">返回统一工作台</a>
        <a class="button-link" href="/keywords/workbench">打开关键词管理台</a>
      </div>
    </section>
    <div class="grid">
      <aside class="panel">
        <h2>导入批次</h2>
        <label for="treeFile">上传目录树</label>
        <input id="treeFile" type="file" accept=".txt,.text" />
        <div class="actions">
          <button id="uploadBtn">导入目录树</button>
          <button class="secondary" id="refreshImportsBtn">刷新批次</button>
        </div>
        <label for="importSelect">选择导入批次</label>
        <select id="importSelect"></select>
        <div class="hint" id="importHint">请先选择一个导入批次。</div>

        <h2 style="margin-top:22px;">手动关键词</h2>
        <label for="keywordFile">导入关键词文件</label>
        <input id="keywordFile" type="file" accept=".txt,.text,.csv" />
        <label for="manualKeywords">手动导入关键词</label>
        <textarea id="manualKeywords" placeholder="每行一个关键词，例如：&#10;狮子座&#10;天蝎座&#10;布丁"></textarea>
        <label for="manualLimit">返回数量</label>
        <input id="manualLimit" type="number" min="1" value="100" />
        <div class="actions">
          <button id="manualRunBtn">运行手动匹配</button>
        </div>

        <h2 style="margin-top:22px;">正则提取</h2>
        <label for="regexPattern">正则表达式</label>
        <input id="regexPattern" value="[【「『［\\[]([^】」』］\\]]+)[】」』］\\]]" />
        <label for="groupIndex">提取分组</label>
        <input id="groupIndex" type="number" min="0" value="1" />
        <label for="regexFlags">flags</label>
        <input id="regexFlags" value="" placeholder="例如 i 或 im" />
        <label for="regexMinCount">最小出现次数</label>
        <input id="regexMinCount" type="number" min="1" value="1" />
        <label for="regexLimit">返回数量</label>
        <input id="regexLimit" type="number" min="1" value="100" />
        <div class="actions">
          <button id="regexPreviewBtn">预览正则提取</button>
          <button class="secondary" id="regexRunBtn">汇总正则结果</button>
        </div>

        <div class="status" id="statusBox">准备就绪。</div>
      </aside>

      <section class="panel">
        <div class="section-title">
          <h2>提取结果</h2>
        </div>
        <div class="summary" id="summaryBox">提取结果会显示在这里。</div>
        <div class="toolbar">
          <input id="keywordFilterInput" placeholder="筛选当前结果，例如：空姐 / 学妹 / 摄影" />
          <div class="toolbar-row">
            <button class="secondary" id="selectVisibleBtn">全选当前页</button>
            <button class="secondary" id="clearKeywordSelectionBtn">清空勾选</button>
          </div>
          <div class="toolbar-row">
            <button id="saveWhitelistBtn">存入白名单</button>
            <button class="secondary" id="saveIgnoreBtn">存入忽略名单</button>
            <button class="secondary" id="saveBlacklistBtn">存入黑名单</button>
            <button class="secondary" id="refreshLibraryBtn">刷新关键词库</button>
          </div>
        </div>
        <div class="pager" id="keywordPager"></div>
        <div class="stack" id="keywordResults"></div>

        <div class="section-title" style="margin-top:22px;">
          <h2>正则预览</h2>
        </div>
        <div class="summary" id="previewSummaryBox">正则命中的目录预览会显示在这里。</div>
        <div class="pager" id="previewPager"></div>
        <div class="preview-list" id="regexPreviewList">
          <div class="hint">正则命中的目录预览会显示在这里。</div>
        </div>

        <div class="section-title" style="margin-top:22px;">
          <h2>关键词库</h2>
        </div>
        <div class="summary" id="librarySummaryBox">已保存的白名单 / 黑名单 / 忽略名单会显示在这里。</div>
        <div class="library-list" id="libraryList"></div>
        <div class="section-title" style="margin-top:22px;">
          <h2>相似匹配提示</h2>
        </div>
        <div class="summary" id="similarSummaryBox">选中关键词后可查看相似提示。</div>
        <div class="preview-list" id="similarList"></div>
      </section>
    </div>
    <aside class="floating-actions">
      <div class="floating-title">批量操作
        <div class="selection-count" id="selectionCountBox">已勾选 0 项</div>
      </div>
      <button class="secondary" id="floatingSelectVisibleBtn">全选当前页</button>
      <button class="secondary" id="floatingClearSelectionBtn">清空勾选</button>
      <button id="floatingSaveWhitelistBtn">存入白名单</button>
      <button class="secondary" id="floatingSaveIgnoreBtn">存入忽略名单</button>
      <button class="secondary" id="floatingSaveBlacklistBtn">存入黑名单</button>
    </aside>
  </div>
  <script>
    const importSelect = document.getElementById('importSelect');
    const importHint = document.getElementById('importHint');
    const statusBox = document.getElementById('statusBox');
    const summaryBox = document.getElementById('summaryBox');
    const keywordResults = document.getElementById('keywordResults');
    const regexPreviewList = document.getElementById('regexPreviewList');
    const libraryList = document.getElementById('libraryList');
    const librarySummaryBox = document.getElementById('librarySummaryBox');
    const similarSummaryBox = document.getElementById('similarSummaryBox');
    const similarList = document.getElementById('similarList');
    const keywordPager = document.getElementById('keywordPager');
    const previewPager = document.getElementById('previewPager');
    const previewSummaryBox = document.getElementById('previewSummaryBox');
    const keywordFilterInput = document.getElementById('keywordFilterInput');
    const selectionCountBox = document.getElementById('selectionCountBox');
    const PAGE_SIZE = 10;
    const state = {
      resultKeywords: [],
      regexPreviewItems: [],
      selectedKeywords: new Set(),
      activeSource: 'manual',
      libraryEntries: [],
      summaryTitle: '提取结果',
      summaryTotalNodes: 0,
      summaryStats: null,
      previewStats: null,
      keywordPage: 1,
      previewPage: 1
    };

    function currentImportId() {
      return importSelect.value ? Number(importSelect.value) : null;
    }

    async function loadImports(preferredId = null) {
      const response = await fetch('/imports/data?limit=100');
      const body = await response.json();
      const items = body.items || [];
      importSelect.innerHTML = '';
      for (const item of items) {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = `#${item.id} · ${item.source_filename} · ${item.status}`;
        importSelect.appendChild(option);
      }
      if (preferredId && items.some(item => item.id === preferredId)) {
        importSelect.value = String(preferredId);
      }
      importHint.textContent = importSelect.value ? `当前批次：#${importSelect.value}` : '请先选择一个导入批次。';
    }

    async function uploadTree() {
      const input = document.getElementById('treeFile');
      const file = input.files[0];
      if (!file) {
        statusBox.textContent = '请先选择目录树文件。';
        return;
      }
      statusBox.textContent = '正在导入目录树...';
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch('/imports/tree', { method: 'POST', body: formData });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '导入失败';
        return;
      }
      statusBox.textContent = `导入完成，批次 ID: ${body.id}`;
      await loadImports(body.id);
    }

    function filteredKeywords() {
      const needle = keywordFilterInput.value.trim().toLowerCase();
      if (!needle) {
        return state.resultKeywords;
      }
      return state.resultKeywords.filter(item =>
        item.keyword.toLowerCase().includes(needle) ||
        item.examples.some(example => example.toLowerCase().includes(needle))
      );
    }

    function pagedItems(items, page) {
      const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
      const safePage = Math.min(Math.max(page, 1), totalPages);
      const start = (safePage - 1) * PAGE_SIZE;
      return {
        items: items.slice(start, start + PAGE_SIZE),
        totalPages,
        page: safePage,
        totalVisible: items.length
      };
    }

    function currentKeywordPageItems() {
      return pagedItems(filteredKeywords(), state.keywordPage).items;
    }

    function updateSelectionCount() {
      selectionCountBox.textContent = `已勾选 ${state.selectedKeywords.size} 项`;
    }

    function renderPager(container, page, totalPages, onChange) {
      container.innerHTML = '';
      if (totalPages <= 1) {
        return;
      }
      const prev = document.createElement('button');
      prev.className = 'secondary';
      prev.textContent = '上一页';
      prev.disabled = page <= 1;
      prev.addEventListener('click', () => onChange(page - 1));
      const next = document.createElement('button');
      next.className = 'secondary';
      next.textContent = '下一页';
      next.disabled = page >= totalPages;
      next.addEventListener('click', () => onChange(page + 1));
      const label = document.createElement('span');
      label.textContent = `第 ${page} / ${totalPages} 页`;
      container.appendChild(prev);
      container.appendChild(label);
      container.appendChild(next);
    }

    function renderKeywords(body, title, source) {
      state.resultKeywords = body.keywords;
      state.activeSource = source;
      state.summaryTitle = title;
      state.summaryTotalNodes = body.total_nodes;
      state.summaryStats = {
        totalKeywords: body.total_keywords,
        totalActionableKeywords: body.total_actionable_keywords || body.total_keywords,
        totalExistingKeywords: body.total_existing_keywords || 0,
        totalIgnoredKeywords: body.total_ignored_keywords || 0,
        totalSimilarKeywords: body.total_similar_keywords || 0
      };
      state.keywordPage = 1;
      renderKeywordResults();
    }

    function renderKeywordResults() {
      const stats = state.summaryStats || {
        totalKeywords: state.resultKeywords.length,
        totalActionableKeywords: state.resultKeywords.length,
        totalExistingKeywords: 0,
        totalIgnoredKeywords: 0,
        totalSimilarKeywords: 0
      };
      const filtered = filteredKeywords();
      const pageData = pagedItems(filtered, state.keywordPage);
      state.keywordPage = pageData.page;
      summaryBox.textContent = `${state.summaryTitle}\\n扫描文件夹: ${state.summaryTotalNodes}\\n待处理关键词: ${stats.totalActionableKeywords}\\n已入库自动过滤: ${stats.totalExistingKeywords}\\n忽略清单自动过滤: ${stats.totalIgnoredKeywords}\\n相似待确认: ${stats.totalSimilarKeywords}\\n当前筛选结果: ${filtered.length}`;
      keywordResults.innerHTML = '';
      renderPager(keywordPager, pageData.page, pageData.totalPages, nextPage => {
        state.keywordPage = nextPage;
        renderKeywordResults();
      });
      if (!pageData.items.length) {
        keywordResults.innerHTML = '<div class="hint">没有命中结果。</div>';
        updateSelectionCount();
        return;
      }
      for (const item of pageData.items) {
        const article = document.createElement('article');
        article.className = 'card';
        article.innerHTML = `
          <div class="keyword-row">
            <input type="checkbox" ${state.selectedKeywords.has(item.keyword) ? 'checked' : ''} />
            <div class="keyword-body">
              <h3>${item.keyword}</h3>
              <div class="badges">
                <span class="badge">命中 ${item.count}</span>
                <span class="badge">来源 ${item.source}</span>
                <span class="badge">${item.match_status === 'similar' ? '相似待确认' : '新词'}</span>
                ${item.matched_canonical_name ? `<span class="badge">近似 ${item.matched_canonical_name}</span>` : ''}
              </div>
              <div class="examples">${item.examples.slice(0, 5).map(example => `<div>${example}</div>`).join('')}</div>
              <div class="keyword-actions">
                <button data-role="save-one" data-type="whitelist">存入白名单</button>
                <button class="secondary" data-role="save-one" data-type="ignore">存入忽略名单</button>
                <button class="secondary" data-role="save-one" data-type="blacklist">存入黑名单</button>
              </div>
            </div>
          </div>
        `;
        article.querySelector('input').addEventListener('change', event => {
          if (event.target.checked) {
            state.selectedKeywords.add(item.keyword);
          } else {
            state.selectedKeywords.delete(item.keyword);
          }
          renderSimilarSuggestions();
          updateSelectionCount();
        });
        article.querySelectorAll('[data-role="save-one"]').forEach(button => {
          button.addEventListener('click', async () => {
            await saveKeywords([item.keyword], button.dataset.type);
          });
        });
        keywordResults.appendChild(article);
      }
      updateSelectionCount();
    }

    function renderRegexPreview(body) {
      state.regexPreviewItems = body.preview;
      state.previewStats = {
        totalMatches: body.total_matches,
        totalActionableMatches: body.total_actionable_matches || body.preview.length
      };
      state.previewPage = 1;
      rerenderRegexPreview();
    }

    function rerenderRegexPreview() {
      regexPreviewList.innerHTML = '';
      const pageData = pagedItems(state.regexPreviewItems, state.previewPage);
      state.previewPage = pageData.page;
      const stats = state.previewStats || { totalMatches: 0, totalActionableMatches: 0 };
      previewSummaryBox.textContent = `正则预览\\n原始命中: ${stats.totalMatches}\\n需要人工处理: ${stats.totalActionableMatches}\\n当前展示: ${pageData.totalVisible}`;
      renderPager(previewPager, pageData.page, pageData.totalPages, nextPage => {
        state.previewPage = nextPage;
        rerenderRegexPreview();
      });
      if (!pageData.items.length) {
        regexPreviewList.innerHTML = '<div class="hint">当前正则没有需要人工处理的目录预览。</div>';
        return;
      }
      for (const item of pageData.items) {
        const article = document.createElement('article');
        article.className = 'preview-item';
        article.innerHTML = `
          <div><strong>${item.extracted_keyword}</strong></div>
          <div class="badges" style="margin:8px 0;">
            <span class="badge">${item.match_status === 'similar' ? '相似待确认' : '新词'}</span>
            ${item.matched_canonical_name ? `<span class="badge">近似 ${item.matched_canonical_name}</span>` : ''}
          </div>
          <div>${item.folder_name}</div>
          <div>${item.raw_path}</div>
        `;
        regexPreviewList.appendChild(article);
      }
    }

    function manualKeywordsPayload() {
      return document.getElementById('manualKeywords').value
        .split('\\n')
        .map(item => item.trim())
        .filter(Boolean);
    }

    function loadKeywordFile() {
      const input = document.getElementById('keywordFile');
      const file = input.files[0];
      if (!file) {
        statusBox.textContent = '请先选择关键词文件。';
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const raw = String(reader.result || '');
        const merged = raw
          .split(/\\r?\\n|,/)
          .map(item => item.trim())
          .filter(Boolean)
          .join('\\n');
        document.getElementById('manualKeywords').value = merged;
        statusBox.textContent = `已导入 ${merged ? merged.split('\\n').length : 0} 个关键词。`;
      };
      reader.readAsText(file, 'utf-8');
    }

    async function runManualKeywords() {
      const importId = currentImportId();
      if (!importId) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const keywords = manualKeywordsPayload();
      if (!keywords.length) {
        statusBox.textContent = '请先输入手动关键词。';
        return;
      }
      statusBox.textContent = '正在运行手动关键词匹配...';
      const response = await fetch('/extractor/keywords/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          import_id: importId,
          keywords,
          limit: Number(document.getElementById('manualLimit').value)
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '手动关键词匹配失败';
        return;
      }
      renderKeywords(body, '手动关键词匹配', 'manual');
      statusBox.textContent = '手动关键词匹配完成。';
    }

    function regexPayload() {
      return {
        import_id: currentImportId(),
        pattern: document.getElementById('regexPattern').value,
        group_index: Number(document.getElementById('groupIndex').value),
        flags: document.getElementById('regexFlags').value.trim(),
        min_count: Number(document.getElementById('regexMinCount').value),
        limit: Number(document.getElementById('regexLimit').value)
      };
    }

    async function fetchRegexSummary() {
      const response = await fetch('/extractor/keywords/regex', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(regexPayload())
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.detail || '正则提取失败');
      }
      return body;
    }

    async function previewRegex() {
      const importId = currentImportId();
      if (!importId) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      statusBox.textContent = '正在预览正则提取...';
      const response = await fetch('/extractor/keywords/regex-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(regexPayload())
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '正则预览失败';
        return;
      }
      renderRegexPreview(body);
      try {
        state.selectedKeywords = new Set();
        const summary = await fetchRegexSummary();
        renderKeywords(summary, '正则提取汇总', 'regex');
        summaryBox.textContent += `\\n命中预览: ${body.total_matches}\\npattern: ${body.pattern}`;
        statusBox.textContent = '正则预览完成，已同步生成可勾选结果。';
      } catch (error) {
        statusBox.textContent = error.message || '正则汇总失败';
      }
    }

    async function runRegexExtraction() {
      const importId = currentImportId();
      if (!importId) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      statusBox.textContent = '正在汇总正则提取结果...';
      try {
        state.selectedKeywords = new Set();
        const body = await fetchRegexSummary();
        renderKeywords(body, '正则提取汇总', 'regex');
        statusBox.textContent = '正则提取完成。';
      } catch (error) {
        statusBox.textContent = error.message || '正则提取失败';
        return;
      }
    }

    function selectVisibleKeywords() {
      for (const item of currentKeywordPageItems()) {
        state.selectedKeywords.add(item.keyword);
      }
      renderKeywordResults();
      renderSimilarSuggestions();
      updateSelectionCount();
    }

    function clearKeywordSelection() {
      state.selectedKeywords = new Set();
      renderKeywordResults();
      renderSimilarSuggestions();
      updateSelectionCount();
    }

    async function loadKeywordLibrary() {
      const response = await fetch('/keywords');
      const body = await response.json();
      state.libraryEntries = body.entries;
      const counts = body.entries.reduce((result, item) => {
        result[item.keyword_type] = (result[item.keyword_type] || 0) + 1;
        return result;
      }, {});
      librarySummaryBox.textContent = `已保存关键词: ${body.total}\\n白名单: ${counts.whitelist || 0}\\n黑名单: ${counts.blacklist || 0}\\n忽略名单: ${counts.ignore || 0}\\n标签: ${counts.tag || 0}`;
      libraryList.innerHTML = '';
      if (!body.entries.length) {
        libraryList.innerHTML = '<div class="hint">关键词库还是空的。</div>';
        return;
      }
      for (const item of body.entries) {
        const article = document.createElement('article');
        article.className = 'library-item';
        article.innerHTML = `
          <div class="library-item-header">
            <strong>${item.canonical_name}</strong>
            <button class="secondary" style="width:auto;padding:8px 12px;" data-role="delete">删除</button>
          </div>
          <div class="badges">
            <span class="badge">${item.keyword_type}</span>
            <span class="badge">${item.status}</span>
            ${item.aliases.map(alias => `<span class="badge">${alias.alias}</span>`).join('')}
          </div>
          <div class="library-meta">${item.note || '无备注'}</div>
        `;
        article.querySelector('[data-role="delete"]').addEventListener('click', async () => {
          await fetch(`/keywords/${item.id}`, { method: 'DELETE' });
          await loadKeywordLibrary();
        });
        libraryList.appendChild(article);
      }
    }

    async function renderSimilarSuggestions() {
      const keywords = Array.from(state.selectedKeywords);
      similarList.innerHTML = '';
      if (!keywords.length) {
        similarSummaryBox.textContent = '选中关键词后可查看相似提示。';
        return;
      }
      const response = await fetch('/keywords/similar-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keywords, threshold: 0.75, limit: 50 })
      });
      const body = await response.json();
      similarSummaryBox.textContent = `相似提示数量: ${body.total}`;
      if (!body.suggestions.length) {
        similarList.innerHTML = '<div class="hint">没有发现需要人工确认的相似词。</div>';
        return;
      }
      for (const item of body.suggestions) {
        const article = document.createElement('article');
        article.className = 'preview-item';
        article.innerHTML = `<div><strong>${item.keyword}</strong> ~ ${item.matched_canonical_name}</div><div>相似度: ${item.score.toFixed(2)}</div>`;
        similarList.appendChild(article);
      }
    }

    async function saveKeywords(keywords, listType) {
      const importId = currentImportId();
      if (!importId) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      if (!keywords.length) {
        statusBox.textContent = '请先勾选要保存的关键词。';
        return;
      }
      statusBox.textContent = `正在保存到 ${listType}...`;
      const keywordObjects = state.resultKeywords.filter(item => state.selectedKeywords.has(item.keyword));
      const examplesByKeyword = Object.fromEntries(keywordObjects.map(item => [item.keyword, item.examples]));
      const sourceFolderNameByKeyword = Object.fromEntries(
        keywordObjects.map(item => [item.keyword, item.examples[0] ? item.examples[0].split('/').filter(Boolean).slice(-1)[0] : item.keyword])
      );
      const payload = {
        keywords,
        keyword_type: listType,
        source: state.activeSource,
        import_id: importId,
        pattern: state.activeSource === 'regex' ? document.getElementById('regexPattern').value : null,
        flags: state.activeSource === 'regex' ? document.getElementById('regexFlags').value.trim() : null,
        examples_by_keyword: examplesByKeyword,
        source_folder_name_by_keyword: sourceFolderNameByKeyword
      };
      const response = await fetch('/keywords/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || `保存到 ${listType} 失败`;
        return;
      }
      statusBox.textContent = `已保存到 ${listType}，新增 ${body.created_count} 条，已存在 ${body.existing_count} 条。`;
      const savedKeywords = new Set(keywords);
      state.resultKeywords = state.resultKeywords.filter(item => !savedKeywords.has(item.keyword));
      state.regexPreviewItems = state.regexPreviewItems.filter(item => !savedKeywords.has(item.extracted_keyword));
      state.selectedKeywords = new Set([...state.selectedKeywords].filter(item => !savedKeywords.has(item)));
      if (state.summaryStats) {
        state.summaryStats.totalActionableKeywords = state.resultKeywords.length;
        state.summaryStats.totalKeywords = state.resultKeywords.length;
        state.summaryStats.totalSimilarKeywords = state.resultKeywords.filter(item => item.match_status === 'similar').length;
      }
      if (state.previewStats) {
        state.previewStats.totalActionableMatches = state.regexPreviewItems.length;
      }
      renderKeywordResults();
      rerenderRegexPreview();
      await loadKeywordLibrary();
      await renderSimilarSuggestions();
    }

    async function saveSelectedKeywords(listType) {
      await saveKeywords(Array.from(state.selectedKeywords), listType);
    }

    document.getElementById('uploadBtn').addEventListener('click', uploadTree);
    document.getElementById('refreshImportsBtn').addEventListener('click', () => loadImports());
    document.getElementById('keywordFile').addEventListener('change', loadKeywordFile);
    document.getElementById('manualRunBtn').addEventListener('click', runManualKeywords);
    document.getElementById('regexPreviewBtn').addEventListener('click', previewRegex);
    document.getElementById('regexRunBtn').addEventListener('click', runRegexExtraction);
    document.getElementById('selectVisibleBtn').addEventListener('click', selectVisibleKeywords);
    document.getElementById('clearKeywordSelectionBtn').addEventListener('click', clearKeywordSelection);
    document.getElementById('saveWhitelistBtn').addEventListener('click', () => saveSelectedKeywords('whitelist'));
    document.getElementById('saveIgnoreBtn').addEventListener('click', () => saveSelectedKeywords('ignore'));
    document.getElementById('saveBlacklistBtn').addEventListener('click', () => saveSelectedKeywords('blacklist'));
    document.getElementById('floatingSelectVisibleBtn').addEventListener('click', selectVisibleKeywords);
    document.getElementById('floatingClearSelectionBtn').addEventListener('click', clearKeywordSelection);
    document.getElementById('floatingSaveWhitelistBtn').addEventListener('click', () => saveSelectedKeywords('whitelist'));
    document.getElementById('floatingSaveIgnoreBtn').addEventListener('click', () => saveSelectedKeywords('ignore'));
    document.getElementById('floatingSaveBlacklistBtn').addEventListener('click', () => saveSelectedKeywords('blacklist'));
    document.getElementById('refreshLibraryBtn').addEventListener('click', loadKeywordLibrary);
    keywordFilterInput.addEventListener('input', () => {
      state.keywordPage = 1;
      renderKeywordResults();
      renderSimilarSuggestions();
    });
    importSelect.addEventListener('change', () => {
      importHint.textContent = importSelect.value ? `当前批次：#${importSelect.value}` : '请先选择一个导入批次。';
    });
    loadImports();
    loadKeywordLibrary();
    updateSelectionCount();
  </script>
</body>
</html>"""
