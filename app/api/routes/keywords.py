from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.keywords import KeywordEntry, KeywordLibraryEntry
from app.schemas.keywords import (
    KeywordAliasAddRequest,
    KeywordDuplicateScanRequest,
    KeywordDuplicateScanResponse,
    KeywordDuplicatePairResponse,
    KeywordEntryBatchImportRequest,
    KeywordEntryBatchImportResponse,
    KeywordEntryCreateRequest,
    KeywordEntryListResponse,
    KeywordEntryMergeRequest,
    KeywordEntryResponse,
    KeywordEntryUpdateRequest,
    KeywordHitResponse,
    KeywordHitRebuildRequest,
    KeywordHitRebuildResponse,
    KeywordLibraryBatchCreateRequest,
    KeywordLibraryBatchCreateResponse,
    KeywordLibraryEntryResponse,
    KeywordOperationLogResponse,
    KeywordTreeHitSummaryListResponse,
    KeywordTreeHitSummaryResponse,
    SimilarKeywordPreviewRequest,
    SimilarKeywordPreviewResponse,
    SimilarKeywordSuggestionResponse,
)
from app.services.keywords.hit_rebuild_service import KeywordHitRebuildService
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

router = APIRouter(tags=["keywords"])


def _to_entry_response(entry: KeywordEntry) -> KeywordEntryResponse:
    return KeywordEntryResponse.model_validate(entry)


@router.get("/keywords", response_model=KeywordEntryListResponse)
def list_keywords(
    keyword_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> KeywordEntryListResponse:
    service = KeywordRegistryService(db)
    entries, total_count = service.list_entries(keyword_type=keyword_type, status=status, query=query, skip=skip, limit=limit)
    return KeywordEntryListResponse(total=total_count, entries=[_to_entry_response(item) for item in entries])


@router.post("/keywords", response_model=KeywordEntryResponse)
def create_keyword(payload: KeywordEntryCreateRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    entry = service.create_entry(
        canonical_name=payload.canonical_name,
        keyword_type=payload.keyword_type,
        note=payload.note,
        aliases=payload.aliases,
        source="manual",
    )
    service.sync_legacy_library()
    return _to_entry_response(entry)


@router.patch("/keywords/{entry_id}", response_model=KeywordEntryResponse)
def update_keyword(entry_id: int, payload: KeywordEntryUpdateRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    try:
        entry = service.update_entry(
            entry_id,
            canonical_name=payload.canonical_name,
            keyword_type=payload.keyword_type,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service.sync_legacy_library()
    return _to_entry_response(entry)


@router.post("/keywords/import", response_model=KeywordEntryBatchImportResponse)
def batch_import_keywords(payload: KeywordEntryBatchImportRequest, db: Session = Depends(get_db)) -> KeywordEntryBatchImportResponse:
    service = KeywordRegistryService(db)
    existing_before = {normalize_keyword_text(item): service.find_entry_by_keyword(item) for item in payload.keywords}
    entries = service.record_hits(
        keywords=payload.keywords,
        import_id=payload.import_id,
        examples_by_keyword=payload.examples_by_keyword,
        source_folder_name_by_keyword=payload.source_folder_name_by_keyword,
        match_rule=payload.pattern,
        match_source=payload.source,
        keyword_type=payload.keyword_type,
    )
    service.sync_legacy_library()
    existing_count = sum(1 for item in existing_before.values() if item is not None)
    unique_entries: dict[int, KeywordEntry] = {entry.id: entry for entry in entries}
    return KeywordEntryBatchImportResponse(
        created_count=max(0, len(unique_entries) - existing_count),
        existing_count=existing_count,
        entries=[_to_entry_response(item) for item in unique_entries.values()],
    )


@router.post("/keywords/{entry_id}/aliases", response_model=KeywordEntryResponse)
def add_keyword_aliases(entry_id: int, payload: KeywordAliasAddRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    service = KeywordRegistryService(db)
    try:
        service.add_aliases(entry_id, payload.aliases, source=payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service.sync_legacy_library()
    entry = db.scalar(select(KeywordEntry).where(KeywordEntry.id == entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Keyword entry not found")
    return _to_entry_response(entry)


@router.post("/keywords/merge", response_model=KeywordEntryResponse)
def merge_keywords(payload: KeywordEntryMergeRequest, db: Session = Depends(get_db)) -> KeywordEntryResponse:
    try:
        entry = KeywordRegistryService(db).merge_entries(
            canonical_entry_id=payload.canonical_entry_id,
            merge_entry_ids=payload.merge_entry_ids,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    KeywordRegistryService(db).sync_legacy_library()
    return _to_entry_response(entry)


@router.get("/keywords/hits", response_model=list[KeywordHitResponse])
def list_keyword_hits(
    import_id: int | None = None,
    keyword_entry_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[KeywordHitResponse]:
    hits = KeywordRegistryService(db).list_hits(import_id=import_id, keyword_entry_id=keyword_entry_id, limit=limit)
    return [KeywordHitResponse.model_validate(item) for item in hits]


@router.post("/keywords/hits/rebuild", response_model=KeywordHitRebuildResponse)
def rebuild_keyword_hits(payload: KeywordHitRebuildRequest, db: Session = Depends(get_db)) -> KeywordHitRebuildResponse:
    try:
        result = KeywordHitRebuildService(db).rebuild_import_hits(
            import_id=payload.import_id,
            include_files=payload.include_files,
            include_folders=payload.include_folders,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KeywordHitRebuildResponse(
        import_id=result.import_id,
        deleted_count=result.deleted_count,
        created_count=result.created_count,
        scanned_folder_count=result.scanned_folder_count,
        scanned_file_count=result.scanned_file_count,
        matched_keyword_count=result.matched_keyword_count,
    )


@router.get("/keywords/tree-hit-summary", response_model=KeywordTreeHitSummaryListResponse)
def list_keyword_tree_hit_summary(
    import_id: int | None = None,
    tree_path: str | None = None,
    keyword_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> KeywordTreeHitSummaryListResponse:
    items = KeywordRegistryService(db).summarize_tree_hits(
        import_id=import_id,
        tree_path=tree_path,
        keyword_type=keyword_type,
        status=status,
        query=query,
        limit=limit,
    )
    return KeywordTreeHitSummaryListResponse(
        total=len(items),
        items=[KeywordTreeHitSummaryResponse.model_validate(item) for item in items],
    )


@router.get("/keywords/operation-logs", response_model=list[KeywordOperationLogResponse])
def list_keyword_operation_logs(
    keyword_entry_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[KeywordOperationLogResponse]:
    logs = KeywordRegistryService(db).list_operation_logs(keyword_entry_id=keyword_entry_id, limit=limit)
    return [KeywordOperationLogResponse.model_validate(item) for item in logs]


@router.post("/keywords/similar-preview", response_model=SimilarKeywordPreviewResponse)
def preview_similar_keywords(payload: SimilarKeywordPreviewRequest, db: Session = Depends(get_db)) -> SimilarKeywordPreviewResponse:
    suggestions = KeywordRegistryService(db).suggest_similar(payload.keywords, threshold=payload.threshold, limit=payload.limit)
    return SimilarKeywordPreviewResponse(
        total=len(suggestions),
        suggestions=[SimilarKeywordSuggestionResponse.model_validate(item) for item in suggestions],
    )


@router.delete("/keywords/{entry_id}")
def delete_keyword(entry_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    service = KeywordRegistryService(db)
    deleted = service.delete_entry(entry_id)
    service.sync_legacy_library()
    return {"deleted": deleted}


legacy_router = APIRouter(prefix="/keyword-library", tags=["keyword-library"])


@legacy_router.get("", response_model=list[KeywordLibraryEntryResponse])
def list_keyword_library(
    list_type: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> list[KeywordLibraryEntryResponse]:
    query_stmt = select(KeywordLibraryEntry).order_by(KeywordLibraryEntry.id.desc())
    if list_type:
        query_stmt = query_stmt.where(KeywordLibraryEntry.list_type == list_type)
    if keyword:
        normalized = normalize_keyword_text(keyword)
        query_stmt = query_stmt.where(KeywordLibraryEntry.keyword_normalized.contains(normalized))
    rows = list(db.scalars(query_stmt).all())
    return [KeywordLibraryEntryResponse.model_validate(row) for row in rows]


@legacy_router.post("", response_model=KeywordLibraryBatchCreateResponse)
def create_keyword_library_entries(
    payload: KeywordLibraryBatchCreateRequest,
    db: Session = Depends(get_db),
) -> KeywordLibraryBatchCreateResponse:
    service = KeywordRegistryService(db)
    created = []
    seen: set[str] = set()
    skipped_count = 0
    for keyword in payload.keywords:
        normalized = normalize_keyword_text(keyword)
        if len(normalized) < 2:
            skipped_count += 1
            continue
        if normalized in seen:
            skipped_count += 1
            continue
        seen.add(normalized)
        existed_before = service.find_entry_by_keyword(normalized) is not None
        entry = service.create_entry(
            canonical_name=keyword,
            keyword_type=payload.list_type,
            note=payload.note,
            aliases=[],
            source=payload.source,
        )
        created.append(entry)
        if existed_before:
            skipped_count += 1
    service.sync_legacy_library()
    rows = list(
        db.scalars(
            select(KeywordLibraryEntry)
            .where(KeywordLibraryEntry.list_type == payload.list_type)
            .where(KeywordLibraryEntry.keyword_normalized.in_(list(seen)))
        ).all()
    )
    return KeywordLibraryBatchCreateResponse(
        created_count=len(rows),
        skipped_count=skipped_count,
        entries=[KeywordLibraryEntryResponse.model_validate(item) for item in rows],
    )


@legacy_router.delete("/{entry_id}")
def delete_keyword_library_entry(entry_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    entry = db.get(KeywordLibraryEntry, entry_id)
    if entry is None:
        return {"deleted": False}
    keyword_entry = KeywordRegistryService(db).find_entry_by_keyword(entry.keyword_normalized)
    db.delete(entry)
    if keyword_entry is not None:
        db.delete(keyword_entry)
    db.commit()
    return {"deleted": True}


@router.get("/keywords/workbench", response_class=HTMLResponse)
def keyword_management_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>关键词管理台</title>
  <style>
    :root { --bg:#f6efe5; --card:#fffaf3; --ink:#1f2421; --muted:#5b645f; --accent:#7c3aed; --line:#ddd3c4; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f3ea 0%,#eee3d6 100%); color:var(--ink); }
    .shell { max-width:1260px; margin:0 auto; padding:28px 18px 40px; }
    .hero,.panel { background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 28px rgba(33,37,41,.06); }
    .hero { padding:24px; color:#fff; background:linear-gradient(135deg, rgba(124,58,237,.94), rgba(62,28,108,.92)); }
    .hero a { display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:0 14px; border-radius:14px; text-decoration:none; font-weight:600; background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.18); margin-right:10px; margin-top:14px; }
    .grid { display:grid; grid-template-columns:360px 1fr; gap:18px; margin-top:22px; }
    .panel { padding:20px; }
    label { display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }
    input, textarea, select, button { width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; }
    input, textarea, select { padding:12px 14px; background:#fff; }
    textarea { min-height:90px; resize:vertical; }
    button { padding:12px 14px; cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
    button.secondary { background:#efe7fb; color:var(--accent); border:1px solid rgba(124,58,237,.16); }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .actions button { flex:1; }
    .hint,.status,.box { margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; white-space:pre-wrap; font-size:13px; line-height:1.6; }
    .list { display:grid; gap:10px; }
    .card { border:1px solid var(--line); border-radius:16px; padding:12px; background:#fff; }
    .badges { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0; }
    .badge { background:#eee5d8; border-radius:999px; padding:4px 10px; font-size:12px; color:var(--muted); }
    .mini-actions { display:flex; gap:8px; margin-top:10px; }
    .mini-actions button { width:auto; padding:8px 12px; }
    .list-toolbar { display:flex; gap:10px; align-items:center; margin-top:12px; flex-wrap:wrap; }
    .list-toolbar input, .list-toolbar select { flex:1; min-width:180px; }
    .list-toolbar button { width:auto; min-width:120px; }
    .keyword-select-row { display:flex; gap:12px; align-items:flex-start; }
    .keyword-select-row input[type="checkbox"] {
      width:18px;
      height:18px;
      margin-top:4px;
      accent-color: var(--accent);
      flex: 0 0 auto;
    }
    .keyword-main { flex:1; }
    .keyword-title { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .keyword-title strong { font-size:18px; }
    .keyword-summary { color:var(--muted); font-size:13px; line-height:1.5; margin-top:4px; }
    .keyword-note { margin-top:6px; line-height:1.5; }
    .alias-block { margin-top:8px; }
    .alias-label { color:var(--muted); font-size:12px; margin-bottom:6px; }
    .tree-toolbar { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; margin-top:12px; }
    .tree-toolbar button { width:100%; }
    .tree-summary-card { border:1px solid var(--line); border-radius:16px; padding:12px; background:#fff; }
    .tree-summary-paths { margin-top:8px; color:var(--muted); font-size:13px; line-height:1.6; }
    .tree-summary-meta { color:var(--muted); font-size:13px; margin-top:4px; }
    .pagination { display:flex; justify-content:center; align-items:center; gap:10px; margin-top:20px; }
    .pagination button { background:var(--accent); color:#fff; border:none; padding:8px 16px; border-radius:14px; cursor:pointer; font-weight:600; }
    .pagination button:disabled { background:#ccc; cursor:not-allowed; }
    .pagination-info { color:var(--ink); font-size:14px; }
    @media (max-width:940px) { .grid { grid-template-columns:1fr; } }
    @media (max-width:940px) { .tree-toolbar { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>关键词管理台</h1>
      <p>这里集中做白名单 / 黑名单 / 忽略清单 / 标签维护，支持手动新增、添加别名、合并标准词、命中重建、查看排行和相似提示。</p>
      <a href="/workbench">返回统一工作台</a>
      <a href="/extractor/keywords/workbench">返回提取器</a>
      <a href="/plans/workbench">打开计划执行台</a>
      <a href="/keywords/duplicates/workbench" style="background:rgba(255,255,255,.25);">🔍 重复词智能扫描</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <h2>手动新增</h2>
        <label for="canonicalName">标准名称</label>
        <input id="canonicalName" />
        <label for="keywordType">类型</label>
        <select id="keywordType">
          <option value="whitelist">whitelist</option>
          <option value="blacklist">blacklist</option>
          <option value="ignore">ignore</option>
          <option value="tag">tag</option>
        </select>
        <label for="aliases">别名（每行一个）</label>
        <textarea id="aliases"></textarea>
        <label for="keywordNote">备注</label>
        <textarea id="keywordNote"></textarea>
        <div class="actions">
          <button id="createKeywordBtn">新增关键词</button>
          <button class="secondary" id="refreshKeywordsBtn">刷新列表</button>
        </div>
        <h2 style="margin-top:22px;">合并关键词</h2>
        <label for="canonicalEntryId">保留标准词 ID</label>
        <input id="canonicalEntryId" type="number" min="1" />
        <label for="mergeEntryIds">待合并 ID（逗号分隔）</label>
        <input id="mergeEntryIds" />
        <div class="actions">
          <button class="secondary" id="appendSelectedMergeIdsBtn">将勾选项加入待合并 ID</button>
          <button class="secondary" id="clearSelectedMergeIdsBtn">清空勾选</button>
        </div>
        <div class="hint" id="mergeSelectionHint">先在右侧关键词列表按筛选结果勾选，再加入待合并 ID。</div>
        <div class="actions">
          <button id="mergeKeywordsBtn">执行合并</button>
        </div>
        <h2 style="margin-top:22px;">相似提示</h2>
        <label for="similarKeywords">待检查关键词（每行一个）</label>
        <textarea id="similarKeywords"></textarea>
        <div class="actions">
          <button class="secondary" id="checkSimilarBtn">检查相似词</button>
        </div>
        <h2 style="margin-top:22px;">命中重建</h2>
        <label for="hitImportSelect">导入批次</label>
        <select id="hitImportSelect"></select>
        <label for="includeFolders">扫描目录</label>
        <select id="includeFolders">
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
        <label for="includeFiles">扫描文件</label>
        <select id="includeFiles">
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
        <label for="replaceExisting">替换旧的重建命中</label>
        <select id="replaceExisting">
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
        <div class="actions">
          <button class="secondary" id="rebuildHitsBtn">重建关键词命中</button>
        </div>
        <div class="status" id="statusBox">准备就绪。</div>
      </aside>
      <section class="panel">
        <h2>关键词列表</h2>
        <div class="list-toolbar">
          <input id="queryInput" placeholder="按标准名或别名过滤" />
          <select id="keywordTypeFilter">
            <option value="">全部类型</option>
            <option value="whitelist">白名单</option>
            <option value="blacklist">黑名单</option>
            <option value="ignore">忽略名</option>
            <option value="tag">标签</option>
          </select>
          <select id="keywordStatusFilter">
            <option value="">全部状态</option>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </select>
          <button class="secondary" id="selectFilteredKeywordsBtn">全选当前筛选结果</button>
        </div>
        <div class="list" id="keywordList" style="margin-top:14px;"></div>
        <div class="pagination" id="paginationControls">
          <button id="prevPageBtn" disabled>上一页</button>
          <span id="pageInfo" class="pagination-info"></span>
          <button id="nextPageBtn" disabled>下一页</button>
        </div>
        <h2 style="margin-top:22px;">目录树关键词命中排行</h2>
        <div class="tree-toolbar">
          <select id="treeImportFilter"></select>
          <input id="treePathInput" placeholder="指定目录树路径，如 根目录/待整理" />
          <input id="treeLimitInput" type="number" min="1" max="500" value="20" />
          <button class="secondary" id="loadTreeSummaryBtn">刷新命中排行</button>
        </div>
        <div class="box" id="treeSummaryHint">选择导入批次后，可按目录树路径查看每个关键词的命中数量，并按从高到低排序。</div>
        <div class="list" id="treeSummaryList" style="margin-top:14px;"></div>
        <h2 style="margin-top:22px;">最近命中记录</h2>
        <div class="box" id="hitsBox">命中记录会显示在这里。</div>
        <h2 style="margin-top:22px;">最近操作日志</h2>
        <div class="box" id="operationLogBox">操作日志会显示在这里。</div>
        <h2 style="margin-top:22px;">相似匹配提示</h2>
        <div class="box" id="similarBox">相似提示会显示在这里。</div>
      </section>
    </div>
  </div>
  <script>
    const keywordList = document.getElementById('keywordList');
    const hitsBox = document.getElementById('hitsBox');
    const operationLogBox = document.getElementById('operationLogBox');
    const similarBox = document.getElementById('similarBox');
    const statusBox = document.getElementById('statusBox');
    const queryInput = document.getElementById('queryInput');
    const keywordTypeFilter = document.getElementById('keywordTypeFilter');
    const keywordStatusFilter = document.getElementById('keywordStatusFilter');
    const mergeSelectionHint = document.getElementById('mergeSelectionHint');
    const treeImportFilter = document.getElementById('treeImportFilter');
    const hitImportSelect = document.getElementById('hitImportSelect');
    const treePathInput = document.getElementById('treePathInput');
    const treeLimitInput = document.getElementById('treeLimitInput');
    const treeSummaryHint = document.getElementById('treeSummaryHint');
    const treeSummaryList = document.getElementById('treeSummaryList');
    const selectedKeywordEntryIds = new Set();

    // Pagination elements
    const paginationControls = document.getElementById('paginationControls');
    const prevPageBtn = document.getElementById('prevPageBtn');
    const nextPageBtn = document.getElementById('nextPageBtn');
    const pageInfo = document.getElementById('pageInfo');

    let currentPage = 1;
    const pageSize = 20; // Default page size
    let totalKeywords = 0;
    let totalPages = 0;

    function buildKeywordListUrl(skip = 0, limit = pageSize) {
      const params = new URLSearchParams();
      const q = queryInput.value.trim();
      if (q) params.set('query', q);
      if (keywordTypeFilter.value) params.set('keyword_type', keywordTypeFilter.value);
      if (keywordStatusFilter.value) params.set('status', keywordStatusFilter.value);
      params.set('skip', skip);
      params.set('limit', limit);
      const query = params.toString();
      return query ? `/keywords?${query}` : '/keywords';
    }

    function updateMergeSelectionHint() {
      const ids = Array.from(selectedKeywordEntryIds).sort((a, b) => a - b);
      mergeSelectionHint.textContent = ids.length
        ? `当前已勾选 ID: ${ids.join(', ')}`
        : '先在右侧关键词列表按筛选结果勾选，再加入待合并 ID。';
    }

    function renderPaginationControls() {
      pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页 (共 ${totalKeywords} 条)`;
      prevPageBtn.disabled = currentPage <= 1;
      nextPageBtn.disabled = currentPage >= totalPages;
      if (totalPages <= 1) {
        paginationControls.style.display = 'none';
      } else {
        paginationControls.style.display = 'flex';
      }
    }

    prevPageBtn.addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        loadKeywords();
      }
    });

    nextPageBtn.addEventListener('click', () => {
      if (currentPage < totalPages) {
        currentPage++;
        loadKeywords();
      }
    });

    function appendSelectedMergeIds() {
      const canonicalEntryId = Number(document.getElementById('canonicalEntryId').value) || null;
      const currentIds = document.getElementById('mergeEntryIds').value
        .split(',')
        .map(item => Number(item.trim()))
        .filter(Boolean);
      const merged = new Set(currentIds);
      Array.from(selectedKeywordEntryIds).forEach(id => {
        if (id !== canonicalEntryId) {
          merged.add(id);
        }
      });
      document.getElementById('mergeEntryIds').value = Array.from(merged).sort((a, b) => a - b).join(', ');
      statusBox.textContent = merged.size ? '已将勾选项加入待合并 ID。' : '没有可加入的勾选项。';
    }

    function clearSelectedMergeIds() {
      selectedKeywordEntryIds.clear();
      updateMergeSelectionHint();
      loadKeywords();
    }

    async function selectFilteredKeywords() {
      // For selecting all filtered keywords, we need to fetch all, not just a page
      const response = await fetch(buildKeywordListUrl(0, totalKeywords > 0 ? totalKeywords : 100000)); // Fetch a large number if total is not yet known
      const body = await response.json();
      body.entries.forEach(item => selectedKeywordEntryIds.add(item.id));
      updateMergeSelectionHint();
      statusBox.textContent = body.entries.length ? `已全选当前筛选结果，共 ${body.entries.length} 项。` : '当前筛选结果为空。';
      loadKeywords();
    }

    async function loadKeywords() {
      const skip = (currentPage - 1) * pageSize;
      const response = await fetch(buildKeywordListUrl(skip, pageSize));
      const body = await response.json();
      
      totalKeywords = body.total;
      totalPages = Math.ceil(totalKeywords / pageSize);

      keywordList.innerHTML = '';
      if (!body.entries.length) {
        keywordList.innerHTML = '<div class="hint">还没有关键词。</div>';
        renderPaginationControls();
        return;
      }
      for (const item of body.entries) {
        const aliases = item.aliases.map(alias => alias.alias);
        const displayAliases = aliases.filter(alias => alias !== item.canonical_name);
        const card = document.createElement('article');
        card.className = 'card';
        card.innerHTML = `
          <div class="keyword-select-row">
            <input type="checkbox" data-role="select-merge" ${selectedKeywordEntryIds.has(item.id) ? 'checked' : ''} />
            <div class="keyword-main">
              <div class="keyword-title">
                <strong>#${item.id} · ${item.canonical_name}</strong>
              </div>
              <div class="badges">
                <span class="badge">${item.keyword_type}</span>
                <span class="badge">${item.status}</span>
                <span class="badge">别名 ${displayAliases.length}</span>
                <span class="badge">更新 ${item.updated_at ? String(item.updated_at).slice(0, 10) : '未知'}</span>
              </div>
              <div class="keyword-summary">标准词：${item.canonical_name} · 归一化：${item.canonical_name_normalized || '无'}</div>
              <div class="alias-block">
                <div class="alias-label">别名预览</div>
                <div class="badges">${displayAliases.length ? displayAliases.map(alias => `<span class="badge">${alias}</span>`).join('') : '<span class="badge">无额外别名</span>'}</div>
              </div>
              <div class="keyword-note">${item.note || '无备注'}</div>
              <div class="mini-actions">
                <button class="secondary" data-role="disable">禁用</button>
                <button class="secondary" data-role="delete">删除</button>
              </div>
            </div>
          </div>
        `;
        card.querySelector('[data-role="select-merge"]').addEventListener('change', event => {
          if (event.target.checked) {
            selectedKeywordEntryIds.add(item.id);
          } else {
            selectedKeywordEntryIds.delete(item.id);
          }
          updateMergeSelectionHint();
        });
        card.querySelector('[data-role="disable"]').addEventListener('click', async () => {
          await fetch(`/keywords/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'disabled' }) });
          await loadKeywords();
          await loadOperationLogs();
        });
        card.querySelector('[data-role="delete"]').addEventListener('click', async () => {
          selectedKeywordEntryIds.delete(item.id);
          await fetch(`/keywords/${item.id}`, { method: 'DELETE' });
          await loadKeywords();
          await loadHits();
          await loadOperationLogs();
        });
        keywordList.appendChild(card);
      }
      updateMergeSelectionHint();
      renderPaginationControls();
    }

    async function loadImports() {
      const response = await fetch('/imports/data?limit=100');
      const body = await response.json();
      const items = body.items || [];
      treeImportFilter.innerHTML = '<option value="">全部导入批次</option>';
      hitImportSelect.innerHTML = '<option value="">请选择导入批次</option>';
      items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = `#${item.id} · ${item.source_filename}`;
        treeImportFilter.appendChild(option);
        hitImportSelect.appendChild(option.cloneNode(true));
      });
      if (items.length && !treeImportFilter.value) {
        treeImportFilter.value = String(items[0].id);
        hitImportSelect.value = String(items[0].id);
      }
    }

    async function loadTreeSummary() {
      const params = new URLSearchParams();
      if (treeImportFilter.value) params.set('import_id', treeImportFilter.value);
      if (treePathInput.value.trim()) params.set('tree_path', treePathInput.value.trim());
      if (keywordTypeFilter.value) params.set('keyword_type', keywordTypeFilter.value);
      if (keywordStatusFilter.value) params.set('status', keywordStatusFilter.value);
      if (queryInput.value.trim()) params.set('query', queryInput.value.trim());
      params.set('limit', String(Number(treeLimitInput.value) || 20));
      const response = await fetch(`/keywords/tree-hit-summary?${params.toString()}`);
      const body = await response.json();
      treeSummaryList.innerHTML = '';
      if (!body.items.length) {
        treeSummaryHint.textContent = '当前筛选条件下还没有目录树关键词命中记录。';
        return;
      }
      const treeScope = treePathInput.value.trim() || '整个导入批次';
      treeSummaryHint.textContent = `当前范围：${treeScope}，共 ${body.total} 个关键词命中。`;
      body.items.forEach(item => {
        const card = document.createElement('article');
        card.className = 'tree-summary-card';
        card.innerHTML = `
          <div class="keyword-title">
            <strong>${item.canonical_name}</strong>
            <span class="badge">命中 ${item.hit_count}</span>
            <span class="badge">类型 ${item.keyword_type}</span>
            <span class="badge">状态 ${item.status}</span>
          </div>
          <div class="tree-summary-meta">关键词 ID: #${item.keyword_entry_id}</div>
          <div class="tree-summary-paths">${item.sample_paths.length ? item.sample_paths.join('<br />') : '暂无示例路径'}</div>
        `;
        treeSummaryList.appendChild(card);
      });
    }

    async function loadHits() {
      const params = new URLSearchParams();
      params.set('limit', '20');
      if (hitImportSelect.value) {
        params.set('import_id', hitImportSelect.value);
      }
      const response = await fetch(`/keywords/hits?${params.toString()}`);
      const body = await response.json();
      if (!body.length) {
        hitsBox.textContent = hitImportSelect.value ? '这个批次当前还没有关键词命中记录。' : '还没有命中记录。';
        return;
      }
      hitsBox.textContent = body.map(item => `${item.raw_keyword} -> ${item.canonical_name_snapshot || '未归并'} | ${item.source_path}`).join('\\n');
    }

    async function rebuildHits() {
      if (!hitImportSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const response = await fetch('/keywords/hits/rebuild', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          import_id: Number(hitImportSelect.value),
          include_folders: document.getElementById('includeFolders').value === 'true',
          include_files: document.getElementById('includeFiles').value === 'true',
          replace_existing: document.getElementById('replaceExisting').value === 'true'
        })
      });
      const body = await response.json();
      statusBox.textContent = response.ok
        ? '重建完成 - 详情请查看控制台'
        : (body.detail || '重建失败');
      if (response.ok) {
        treeImportFilter.value = hitImportSelect.value;
        await loadHits();
        await loadTreeSummary();
      }
    }

    async function loadOperationLogs() {
      const response = await fetch('/keywords/operation-logs?limit=20');
      const body = await response.json();
      if (!body.length) {
        operationLogBox.textContent = '还没有操作日志。';
        return;
      }
      operationLogBox.textContent = body.map(item => {
        const ids = [
          item.keyword_entry_id ? `主词#${item.keyword_entry_id}` : null,
          item.related_keyword_entry_id ? `相关#${item.related_keyword_entry_id}` : null
        ].filter(Boolean).join(' ');
        return `[${String(item.created_at || '').replace('T', ' ').slice(0, 19)}] ${item.action}${ids ? ' | ' + ids : ''}${item.detail ? ' | ' + item.detail : ''}`;
      }).join('\\n');
    }

    async function createKeyword() {
      const canonical_name = document.getElementById('canonicalName').value.trim();
      if (!canonical_name) {
        statusBox.textContent = '请先输入标准名称。';
        return;
      }
      const payload = {
        canonical_name,
        keyword_type: document.getElementById('keywordType').value,
        aliases: document.getElementById('aliases').value.split('\\n').map(item => item.trim()).filter(Boolean),
        note: document.getElementById('keywordNote').value.trim() || null
      };
      const response = await fetch('/keywords', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const body = await response.json();
      statusBox.textContent = response.ok ? `已创建: ${body.canonical_name}` : (body.detail || '创建失败');
      if (response.ok) {
        await loadKeywords();
        await loadOperationLogs();
      }
    }

    async function mergeKeywords() {
      const canonicalEntryId = Number(document.getElementById('canonicalEntryId').value);
      const mergeEntryIds = document.getElementById('mergeEntryIds').value.split(',').map(item => Number(item.trim())).filter(Boolean);
      const response = await fetch('/keywords/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ canonical_entry_id: canonicalEntryId, merge_entry_ids: mergeEntryIds })
      });
      const body = await response.json();
      statusBox.textContent = response.ok ? `合并完成: ${body.canonical_name}` : (body.detail || '合并失败');
      if (response.ok) {
        await loadKeywords();
        await loadHits();
        await loadOperationLogs();
      }
    }

    async function checkSimilar() {
      const keywords = document.getElementById('similarKeywords').value.split('\\n').map(item => item.trim()).filter(Boolean);
      const response = await fetch('/keywords/similar-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keywords, threshold: 0.75, limit: 50 })
      });
      const body = await response.json();
      similarBox.textContent = body.suggestions && body.suggestions.length
        ? body.suggestions.map(item => `${item.keyword} ~ ${item.matched_canonical_name} (${item.score.toFixed(2)})`).join('\\n')
        : '没有发现需要提示的相似词。';
    }

    document.getElementById('createKeywordBtn').addEventListener('click', createKeyword);
    document.getElementById('refreshKeywordsBtn').addEventListener('click', loadKeywords);
    document.getElementById('selectFilteredKeywordsBtn').addEventListener('click', selectFilteredKeywords);
    document.getElementById('appendSelectedMergeIdsBtn').addEventListener('click', appendSelectedMergeIds);
    document.getElementById('clearSelectedMergeIdsBtn').addEventListener('click', clearSelectedMergeIds);
    document.getElementById('mergeKeywordsBtn').addEventListener('click', mergeKeywords);
    document.getElementById('checkSimilarBtn').addEventListener('click', checkSimilar);
    document.getElementById('rebuildHitsBtn').addEventListener('click', rebuildHits);
    document.getElementById('loadTreeSummaryBtn').addEventListener('click', loadTreeSummary);
    treeImportFilter.addEventListener('change', loadTreeSummary);
    hitImportSelect.addEventListener('change', loadHits);

    // Reset current page when filters change
    keywordTypeFilter.addEventListener('change', async () => {
      currentPage = 1;
      await loadKeywords();
      await loadTreeSummary();
    });
    keywordStatusFilter.addEventListener('change', async () => {
      currentPage = 1;
      await loadKeywords();
      await loadTreeSummary();
    });
    queryInput.addEventListener('input', async () => {
      currentPage = 1;
      await loadKeywords();
      await loadTreeSummary();
    });

    loadImports().then(async () => {
      await loadTreeSummary();
      await loadHits();
    });
    loadKeywords();
    loadOperationLogs();
  </script>
</body>
</html>"""


@router.get("/keywords/hits/workbench")
def keyword_hit_rebuild_workbench() -> RedirectResponse:
    return RedirectResponse(url="/keywords/workbench#hits", status_code=307)


@router.get("/keywords/tree-hit-summary/workbench")
def keyword_tree_hit_summary_workbench() -> RedirectResponse:
    return RedirectResponse(url="/keywords/workbench#tree-summary", status_code=307)


@router.post("/keywords/duplicates/scan", response_model=KeywordDuplicateScanResponse)
def scan_duplicate_keywords(payload: KeywordDuplicateScanRequest, db: Session = Depends(get_db)) -> KeywordDuplicateScanResponse:
    service = KeywordRegistryService(db)
    pairs = service.scan_duplicate_keywords(
        keyword_type=payload.keyword_type,
        status=payload.status,
        threshold=payload.threshold,
    )
    return KeywordDuplicateScanResponse(
        pairs=[
            KeywordDuplicatePairResponse(
                keyword_1=_to_entry_response(a),
                keyword_2=_to_entry_response(b),
                score=score
            )
            for a, b, score in pairs
        ]
    )


@router.get("/keywords/duplicates/workbench", response_class=HTMLResponse)
def keyword_duplicates_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>重复词智能扫描</title>
  <style>
    :root { --bg:#f6efe5; --card:#fffaf3; --ink:#1f2421; --muted:#5b645f; --accent:#7c3aed; --line:#ddd3c4; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f3ea 0%,#eee3d6 100%); color:var(--ink); }
    .shell { max-width:960px; margin:0 auto; padding:28px 18px 40px; }
    .hero,.panel { background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 28px rgba(33,37,41,.06); }
    .hero { padding:24px; color:#fff; background:linear-gradient(135deg, rgba(220,38,38,.94), rgba(153,27,27,.92)); margin-bottom: 22px; }
    .hero a { display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:0 14px; border-radius:14px; text-decoration:none; font-weight:600; background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.18); margin-right:10px; margin-top:14px; }
    .panel { padding:20px; }
    label { display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }
    input, select, button { width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; padding:12px 14px; background:#fff; }
    button { cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
    button.secondary { background:#efe7fb; color:var(--accent); border:1px solid rgba(124,58,237,.16); }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .actions button { flex:1; }
    .status { margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; font-size:13px; }
    
    .list { display:grid; gap:14px; margin-top:14px; }
    .card { border:1px solid var(--line); border-radius:16px; padding:16px; background:#fff; }
    .card-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid var(--line); padding-bottom:8px; }
    .score-badge { background:#ffedd5; color:#c2410c; padding:4px 8px; border-radius:8px; font-weight:bold; font-size:13px; }
    
    .pair-row { display:flex; gap:16px; align-items:center; }
    @media (max-width:600px) { .pair-row { flex-direction:column; align-items:flex-start; } .arrow { transform: rotate(90deg); margin: 8px 0; } }
    
    .keyword-item { flex:1; background:#fafafa; border:1px solid var(--line); border-radius:12px; padding:12px; width:100%; }
    .keyword-title { font-weight:bold; font-size:16px; margin-bottom:4px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .badges { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
    .badge { background:#eee5d8; border-radius:999px; padding:2px 8px; font-size:12px; color:var(--muted); }
    
    .arrow { font-size:24px; color:var(--muted); font-weight:bold; }
    
    .merge-actions { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:16px; }
    .merge-actions button { font-size:13px; }
    .ignore-btn { width:100%; background:transparent; color:var(--muted); border:1px solid var(--line); margin-top:10px; }
    .ignore-btn:hover { background:#f5f5f5; }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>重复词智能扫描</h1>
      <p>自动在内存中两两计算关键词的匹配相似度，找出高重叠率的相似词，并进行一键合并清理。</p>
      <a href="/keywords/workbench">返回关键词管理台</a>
    </section>
    
    <section class="panel">
      <h2>扫描配置</h2>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
        <div>
          <label>扫描类型</label>
          <select id="keywordType">
            <option value="whitelist">白名单 (whitelist)</option>
            <option value="blacklist">黑名单 (blacklist)</option>
            <option value="ignore">忽略名 (ignore)</option>
            <option value="tag">标签 (tag)</option>
            <option value="">全部类型 (慢)</option>
          </select>
        </div>
        <div>
          <label>相似度阈值 (0.1 ~ 1.0)</label>
          <input type="number" id="threshold" value="0.85" step="0.05" min="0.1" max="1.0" />
        </div>
      </div>
      <div class="actions">
        <button id="scanBtn">开始全库摸底扫描</button>
      </div>
      <div class="status" id="statusBox">等待执行...</div>
    </section>
    
    <div class="list" id="resultList"></div>
  </div>
  
  <script>
    const scanBtn = document.getElementById('scanBtn');
    const resultList = document.getElementById('resultList');
    const statusBox = document.getElementById('statusBox');
    
    async function performScan() {
      const type = document.getElementById('keywordType').value;
      const thres = Number(document.getElementById('threshold').value) || 0.85;
      
      scanBtn.disabled = true;
      statusBox.textContent = '正在计算全排列相似度，请稍候...';
      resultList.innerHTML = '';
      
      try {
        const res = await fetch('/keywords/duplicates/scan', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
             keyword_type: type || null,
             threshold: thres
          })
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail || '请求失败');
        
        statusBox.textContent = `扫描完成，发现 ${data.pairs.length} 对潜在重复词汇。`;
        renderResults(data.pairs);
      } catch (err) {
        statusBox.textContent = `出错: ${err.message}`;
      } finally {
        scanBtn.disabled = false;
      }
    }
    
    function renderResults(pairs) {
      if (pairs.length === 0) {
        resultList.innerHTML = '<div class="panel" style="text-align:center; color:#5b645f;">太棒了，没有找到重复度高的相似词！</div>';
        return;
      }
      
      pairs.forEach((pair, idx) => {
        const k1 = pair.keyword_1;
        const k2 = pair.keyword_2;
        
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="card-header">
            <span style="font-size:14px; color:#5b645f;">发现可疑重合对</span>
            <span class="score-badge">相似度 ${(pair.score * 100).toFixed(0)}%</span>
          </div>
          
          <div class="pair-row">
            <div class="keyword-item">
              <div class="keyword-title">
                 <span>#${k1.id}</span> ${k1.canonical_name}
              </div>
              <div class="badges">
                <span class="badge">别名数: ${k1.aliases ? k1.aliases.length : 0}</span>
                <span class="badge">${k1.status}</span>
              </div>
            </div>
            
            <div class="arrow">↔</div>
            
            <div class="keyword-item">
              <div class="keyword-title">
                 <span>#${k2.id}</span> ${k2.canonical_name}
              </div>
              <div class="badges">
                <span class="badge">别名数: ${k2.aliases ? k2.aliases.length : 0}</span>
                <span class="badge">${k2.status}</span>
              </div>
            </div>
          </div>
          
          <div class="merge-actions">
            <button onclick="mergeItems(this, ${k1.id}, ${k2.id})">将 [${k2.canonical_name}] 合并到左侧</button>
            <button class="secondary" onclick="mergeItems(this, ${k2.id}, ${k1.id})">将 [${k1.canonical_name}] 合并到右侧</button>
          </div>
          <button class="ignore-btn" onclick="this.closest('.card').remove()">忽略此条 (暂不处理)</button>
        `;
        resultList.appendChild(card);
      });
    }
    
    async function mergeItems(btn, canonicalId, mergeId) {
      btn.disabled = true;
      btn.textContent = '合并中...';
      
      try {
        const res = await fetch('/keywords/merge', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            canonical_entry_id: canonicalId,
            merge_entry_ids: [mergeId]
          })
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail || '合并失败');
        
        const card = btn.closest('.card');
        card.innerHTML = `<div style="text-align:center; padding: 20px; color: var(--accent); font-weight:bold;">✅ 已成功合并入 #${canonicalId}</div>`;
        setTimeout(() => card.remove(), 2000);
        
      } catch (err) {
        alert("合并报错: " + err.message);
        btn.disabled = false;
        btn.textContent = '重试';
      }
    }
    
    scanBtn.addEventListener('click', performScan);
  </script>
</body>
</html>"""
