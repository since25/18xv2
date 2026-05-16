from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_115_client, get_db, get_source_article_db
from app.models.tasks import MagnetDownloadTask
from app.schemas.magnet_tasks import (
    ArticleSearchRequest,
    ArticleSearchResponse,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    MagnetTaskBatchResponse,
    MagnetTaskBatchSummaryListResponse,
    MagnetTaskBatchSummaryResponse,
    MagnetTaskCreateRequest,
    MagnetTaskResponse,
    WhitelistBatchPreviewResponse,
    WhitelistBatchRequest,
    WhitelistBatchCandidateResponse,
    WhitelistBatchSubmitResponse,
)
from app.services.client_115.client import Real115Client
from app.services.magnet_download_service import MagnetDownloadService
from app.services.source_article_db import SourceArticleDatabaseService

router = APIRouter(prefix="/magnet-tasks", tags=["magnet-tasks"])


def _build_batch_summaries(rows: list[MagnetDownloadTask]) -> list[MagnetTaskBatchSummaryResponse]:
    grouped: OrderedDict[str, list[MagnetDownloadTask]] = OrderedDict()
    for row in rows:
        batch_key = row.batch_id or f"legacy-{row.id}"
        grouped.setdefault(batch_key, []).append(row)

    summaries: list[MagnetTaskBatchSummaryResponse] = []
    for batch_id, items in grouped.items():
        ordered_items = sorted(items, key=lambda item: item.id)
        summaries.append(
            MagnetTaskBatchSummaryResponse(
                batch_id=batch_id,
                created_at=min(item.created_at for item in ordered_items if item.created_at is not None) or datetime.utcnow(),
                total_count=len(ordered_items),
                submitted_count=sum(1 for item in ordered_items if item.status == "submitted"),
                duplicate_skipped_count=sum(1 for item in ordered_items if item.status == "duplicate_skipped"),
                failed_count=sum(1 for item in ordered_items if item.status == "failed"),
                pending_count=sum(1 for item in ordered_items if item.status == "pending"),
                items=[MagnetTaskResponse.model_validate(item) for item in ordered_items],
            )
        )
    return summaries


@router.get("", response_model=list[MagnetTaskResponse])
def list_magnet_tasks(
    status: str | None = None,
    keyword_entry_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[MagnetTaskResponse]:
    stmt = select(MagnetDownloadTask).order_by(MagnetDownloadTask.id.desc())
    if status:
        stmt = stmt.where(MagnetDownloadTask.status == status)
    if keyword_entry_id is not None:
        stmt = stmt.where(MagnetDownloadTask.keyword_entry_id == keyword_entry_id)
    return [MagnetTaskResponse.model_validate(row) for row in db.scalars(stmt).all()]


@router.get("/batches", response_model=MagnetTaskBatchSummaryListResponse)
def list_magnet_task_batches(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> MagnetTaskBatchSummaryListResponse:
    rows = db.scalars(select(MagnetDownloadTask).order_by(MagnetDownloadTask.id.desc())).all()
    summaries = _build_batch_summaries(list(rows))
    limited = summaries[: max(1, min(limit, 100))]
    return MagnetTaskBatchSummaryListResponse(total=len(summaries), batches=limited)


@router.delete("/history")
def clear_magnet_task_history(db: Session = Depends(get_db)) -> dict[str, int]:
    rows = db.scalars(select(MagnetDownloadTask)).all()
    deleted_count = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return {"deleted_count": deleted_count}


@router.post("/search", response_model=ArticleSearchResponse)
def search_article_candidates(
    payload: ArticleSearchRequest,
    db: Session = Depends(get_db),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> ArticleSearchResponse:
    try:
        candidates = MagnetDownloadService(db, article_db=article_db).build_candidates(
            query=payload.query,
            keyword_entry_id=payload.keyword_entry_id,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ArticleSearchResponse(
        query=payload.query,
        keyword_entry_id=payload.keyword_entry_id,
        total_candidates=len(candidates),
        candidates=candidates,
    )


@router.post("/duplicate-check", response_model=DuplicateCheckResponse)
def duplicate_check(
    payload: DuplicateCheckRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> DuplicateCheckResponse:
    if payload.tree_import_id is None:
        raise HTTPException(status_code=400, detail="请先选择目录树批次后再执行重复检查。当前仅支持本地目录树匹配。")
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    return DuplicateCheckResponse(items=service.check_duplicates(payload.items, tree_import_id=payload.tree_import_id))


@router.post("/submit", response_model=MagnetTaskBatchResponse)
def submit_magnet_tasks(
    payload: MagnetTaskCreateRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> MagnetTaskBatchResponse:
    if payload.tree_import_id is None:
        raise HTTPException(status_code=400, detail="请先选择目录树批次后再提交磁力任务。当前仅允许基于本地目录树完成重复检查。")
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    tasks = service.create_and_submit_tasks(
        items=payload.items,
        target_cid=payload.target_cid,
        force_submit=payload.force_submit,
        tree_import_id=payload.tree_import_id,
    )
    return MagnetTaskBatchResponse(
        created_count=len(tasks),
        submitted_count=sum(1 for task in tasks if task.status == "submitted"),
        duplicate_skipped_count=sum(1 for task in tasks if task.status == "duplicate_skipped"),
        tasks=[MagnetTaskResponse.model_validate(task) for task in tasks],
    )


@router.post("/whitelist-batch/preview", response_model=WhitelistBatchPreviewResponse)
def preview_whitelist_batch(
    payload: WhitelistBatchRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> WhitelistBatchPreviewResponse:
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    try:
        preview_run = service.preview_whitelist_batch(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            total_limit=payload.total_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WhitelistBatchPreviewResponse(
        scanned_keyword_count=preview_run.scanned_keyword_count,
        total_candidates=preview_run.total_candidates,
        selected_candidates=len(preview_run.preview_items),
        candidates=[
            WhitelistBatchCandidateResponse(
                source_tid=item.item.source_tid,
                source_title=item.item.source_title,
                source_magnet=item.item.source_magnet,
                source_detail_url=item.item.source_detail_url,
                source_section=item.item.source_section,
                matched_keyword=item.item.matched_keyword,
                matched_alias=item.item.matched_alias,
                match_score=item.item.match_score,
                keyword_entry_id=item.item.keyword_entry_id,
                duplicate_status=item.duplicate_status,
                duplicate_reason=item.duplicate_reason,
                matched_import_id=item.matched_import_id,
                matched_import_label=item.matched_import_label,
                target_path=item.target_path,
            )
            for item in preview_run.preview_items
        ],
    )


@router.post("/whitelist-batch/submit", response_model=WhitelistBatchSubmitResponse)
def submit_whitelist_batch(
    payload: WhitelistBatchRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
    article_db: SourceArticleDatabaseService = Depends(get_source_article_db),
) -> WhitelistBatchSubmitResponse:
    service = MagnetDownloadService(db, article_db=article_db, client_115=client_115)
    try:
        preview_run, tasks = service.submit_whitelist_batch(
            tree_import_id=payload.tree_import_id,
            keyword_entry_ids=payload.keyword_entry_ids,
            per_keyword_limit=payload.per_keyword_limit,
            total_limit=payload.total_limit,
            submit_limit=payload.submit_limit,
            force_submit=payload.force_submit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WhitelistBatchSubmitResponse(
        scanned_keyword_count=preview_run.scanned_keyword_count,
        total_candidates=preview_run.total_candidates,
        selected_candidates=min(len(preview_run.preview_items), payload.submit_limit),
        created_count=len(tasks),
        submitted_count=sum(1 for task in tasks if task.status == "submitted"),
        duplicate_skipped_count=sum(1 for task in tasks if task.status == "duplicate_skipped"),
        failed_count=sum(1 for task in tasks if task.status == "failed"),
        tasks=[MagnetTaskResponse.model_validate(task) for task in tasks],
    )


@router.get("/workbench", response_class=HTMLResponse)
def magnet_tasks_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>磁力下载任务台</title>
  <style>
    :root { --bg:#f4efe7; --card:#fffaf4; --ink:#1e2320; --muted:#66706a; --accent:#125f54; --line:#ded4c6; --soft:#dcefeb; --warn:#8c5a00; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f2ea,#ebe0d2); color:var(--ink); }
    .shell { max-width:1280px; margin:0 auto; padding:28px 18px 40px; }
    .hero,.panel { background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 30px rgba(33,37,41,.06); }
    .hero { padding:24px; color:#fff; background:linear-gradient(135deg, rgba(18,95,84,.95), rgba(15,92,138,.92)); }
    .grid { display:grid; grid-template-columns:360px 1fr; gap:18px; margin-top:22px; }
    .panel { padding:20px; }
    label { display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }
    input, button, textarea { width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; }
    input, textarea { padding:12px 14px; background:#fff; }
    button { padding:12px 14px; cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
    button.secondary { background:var(--soft); color:var(--accent); border:1px solid rgba(18,95,84,.2); }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .actions button { flex:1; }
    .box { margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; white-space:pre-wrap; font-size:13px; line-height:1.6; }
    .list { display:grid; gap:12px; margin-top:14px; }
    .card { border:1px solid var(--line); border-radius:16px; padding:12px; background:#fff; }
    .row { display:flex; gap:12px; align-items:flex-start; }
    .row input[type="checkbox"] { width:18px; height:18px; margin-top:4px; accent-color:var(--accent); flex:0 0 auto; }
    .grow { flex:1; }
    .meta { color:var(--muted); font-size:13px; margin-top:6px; }
    .badges { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
    .badge { background:#eee5d8; border-radius:999px; padding:4px 10px; font-size:12px; color:var(--muted); }
    .warn { color:var(--warn); }
    @media (max-width:940px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>磁力下载任务台</h1>
      <p>根据关键词到外部 article 数据库搜索资源，先做 115 去重预检，再勾选提交磁力离线下载。</p>
    </section>
    <div class="grid">
      <aside class="panel">
        <label for="keywordEntryId">关键词 ID（可选）</label>
        <input id="keywordEntryId" type="number" min="1" placeholder="例如：123" />
        <label for="queryInput">搜索词</label>
        <input id="queryInput" placeholder="演员名、番号或别名" />
        <label for="targetCidInput">115 保存目录 CID（可选）</label>
        <input id="targetCidInput" placeholder="留空则使用默认保存目录" />
        <label><input id="forceSubmitCheckbox" type="checkbox" style="width:auto;" />发现重复也强制提交</label>
        <div class="actions">
          <button id="searchBtn">搜索预览</button>
          <button class="secondary" id="dedupeBtn">检查重复</button>
        </div>
        <div class="actions">
          <button class="secondary" id="submitBtn">提交勾选项到115</button>
        </div>
        <div class="box" id="statusBox">先输入搜索词，再搜索预览。</div>
      </aside>
      <section class="panel">
        <div class="actions">
          <button class="secondary" id="selectAllBtn">全选</button>
          <button class="secondary" id="clearBtn">清空</button>
        </div>
        <div class="list" id="candidateList"></div>
      </section>
    </div>
  </div>
  <script>
    const state = { candidates: [], duplicateMap: new Map() };
    const $ = (id) => document.getElementById(id);

    function selectedItems() {
      return state.candidates.filter((_, index) => {
        const box = document.querySelector(`input[data-index="${index}"]`);
        return box && box.checked;
      });
    }

    function render() {
      const list = $("candidateList");
      list.innerHTML = "";
      if (!state.candidates.length) {
        list.innerHTML = '<div class="box">还没有搜索结果。</div>';
        return;
      }
      state.candidates.forEach((item, index) => {
        const dup = state.duplicateMap.get(item.source_tid);
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
          <div class="row">
            <input type="checkbox" data-index="${index}" />
            <div class="grow">
              <div><strong>${item.source_title}</strong></div>
              <div class="badges">
                <span class="badge">tid ${item.source_tid}</span>
                <span class="badge">score ${item.match_score}</span>
                ${item.matched_keyword ? `<span class="badge">关键词 ${item.matched_keyword}</span>` : ""}
                ${item.matched_alias ? `<span class="badge">别名 ${item.matched_alias}</span>` : ""}
              </div>
              <div class="meta">${item.source_detail_url || "无详情链接"}</div>
              <div class="meta">磁力：${item.source_magnet.slice(0, 100)}...</div>
              <div class="meta ${dup && dup.duplicate_status !== 'clear' ? 'warn' : ''}">
                去重：${dup ? `${dup.duplicate_status}${dup.duplicate_reason ? " - " + dup.duplicate_reason : ""}` : "未检查"}
              </div>
            </div>
          </div>`;
        list.appendChild(card);
      });
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || JSON.stringify(body));
      return body;
    }

    $("searchBtn").addEventListener("click", async () => {
      $("statusBox").textContent = "正在搜索 article 数据库...";
      try {
        const body = await postJson("/magnet-tasks/search", {
          keyword_entry_id: $("keywordEntryId").value ? Number($("keywordEntryId").value) : null,
          query: $("queryInput").value,
          limit: 30,
        });
        state.candidates = body.candidates;
        state.duplicateMap = new Map();
        render();
        $("statusBox").textContent = `搜索完成，共 ${body.total_candidates} 条候选。`;
      } catch (error) {
        $("statusBox").textContent = String(error);
      }
    });

    $("dedupeBtn").addEventListener("click", async () => {
      const items = selectedItems();
      if (!items.length) {
        $("statusBox").textContent = "先勾选要做去重检查的候选项。";
        return;
      }
      $("statusBox").textContent = "正在检查 115 是否已有重复资源...";
      try {
        const body = await postJson("/magnet-tasks/duplicate-check", { items });
        state.duplicateMap = new Map(body.items.map((item) => [item.source_tid, item]));
        render();
        const duplicateCount = body.items.filter((item) => item.duplicate_status !== "clear").length;
        $("statusBox").textContent = `去重检查完成，发现 ${duplicateCount} 条疑似重复。`;
      } catch (error) {
        $("statusBox").textContent = String(error);
      }
    });

    $("submitBtn").addEventListener("click", async () => {
      const items = selectedItems();
      if (!items.length) {
        $("statusBox").textContent = "先勾选要提交的候选项。";
        return;
      }
      $("statusBox").textContent = "正在提交磁力到 115...";
      try {
        const body = await postJson("/magnet-tasks/submit", {
          items,
          target_cid: $("targetCidInput").value || null,
          force_submit: $("forceSubmitCheckbox").checked,
        });
        $("statusBox").textContent = `已创建 ${body.created_count} 条任务，成功提交 ${body.submitted_count} 条，跳过重复 ${body.duplicate_skipped_count} 条。`;
      } catch (error) {
        $("statusBox").textContent = String(error);
      }
    });

    $("selectAllBtn").addEventListener("click", () => {
      document.querySelectorAll('input[data-index]').forEach((box) => box.checked = true);
    });
    $("clearBtn").addEventListener("click", () => {
      document.querySelectorAll('input[data-index]').forEach((box) => box.checked = false);
    });
    render();
  </script>
</body>
</html>"""
