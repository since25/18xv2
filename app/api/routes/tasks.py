from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.tasks import OrganizeTask
from app.schemas.tasks import (
    AmbiguousConflictItem,
    AmbiguousConflictListResponse,
    AmbiguousConflictResolutionImportResponse,
    AmbiguousKeywordOption as SchemaKeywordOption,
    AmbiguousResolveRequest,
    AmbiguousResolveResponse,
    DuplicateTargetConflictGroup,
    DuplicateTargetConflictListResponse,
    NodeDetailItem,
    NodeDetailRequest,
    NodeDetailResponse,
    OrganizeTaskBatchResponse,
    OrganizeTaskCreateRequest,
    OrganizeTaskGenerateFromImportRequest,
    OrganizeTaskGenerateFromKeywordRequest,
    OrganizeTaskResponse,
    OrganizeTaskUpdateRequest,
)
from app.services.tasks.organize_task_service import OrganizeTaskService

router = APIRouter(prefix="/organize-tasks", tags=["organize-tasks"])


@router.get("", response_model=list[OrganizeTaskResponse])
def list_organize_tasks(
    import_id: int | None = None,
    keyword_entry_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[OrganizeTaskResponse]:
    query = select(OrganizeTask).order_by(OrganizeTask.id.desc())
    if import_id is not None:
        query = query.where(OrganizeTask.import_id == import_id)
    if keyword_entry_id is not None:
        query = query.where(OrganizeTask.keyword_entry_id == keyword_entry_id)
    if status is not None:
        query = query.where(OrganizeTask.status == status)
    rows = list(db.scalars(query).all())
    return [OrganizeTaskResponse.model_validate(item) for item in rows]


@router.post("", response_model=OrganizeTaskResponse)
def create_organize_task(payload: OrganizeTaskCreateRequest, db: Session = Depends(get_db)) -> OrganizeTaskResponse:
    task = OrganizeTask(
        import_id=payload.import_id,
        node_id=payload.node_id,
        keyword_entry_id=payload.keyword_entry_id,
        source_path=payload.source_path,
        target_path=payload.target_path,
        matched_canonical_name=payload.matched_canonical_name,
        status="pending",
        operation_log="Placeholder task created. Real 115 execution is not enabled yet.",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return OrganizeTaskResponse.model_validate(task)


@router.post("/generate-from-keyword", response_model=OrganizeTaskBatchResponse)
def generate_organize_tasks_from_keyword(
    payload: OrganizeTaskGenerateFromKeywordRequest,
    db: Session = Depends(get_db),
) -> OrganizeTaskBatchResponse:
    try:
        result = OrganizeTaskService(db).generate_tasks_from_keyword_hits(
            import_id=payload.import_id,
            keyword_entry_id=payload.keyword_entry_id,
            target_root=payload.target_root,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrganizeTaskBatchResponse(
        import_id=result.import_id,
        keyword_entry_id=result.keyword_entry_id,
        deleted_count=result.deleted_count,
        created_count=result.created_count,
        skipped_ambiguous_count=result.skipped_ambiguous_count,
        tasks=[OrganizeTaskResponse.model_validate(item) for item in result.tasks],
    )


@router.post("/generate-from-import", response_model=OrganizeTaskBatchResponse)
def generate_organize_tasks_from_import(
    payload: OrganizeTaskGenerateFromImportRequest,
    db: Session = Depends(get_db),
) -> OrganizeTaskBatchResponse:
    try:
        result = OrganizeTaskService(db).generate_tasks_from_import_hits(
            import_id=payload.import_id,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrganizeTaskBatchResponse(
        import_id=result.import_id,
        keyword_entry_id=result.keyword_entry_id,
        deleted_count=result.deleted_count,
        created_count=result.created_count,
        skipped_ambiguous_count=result.skipped_ambiguous_count,
        tasks=[OrganizeTaskResponse.model_validate(item) for item in result.tasks],
    )


@router.get("/duplicate-conflicts", response_model=DuplicateTargetConflictListResponse)
def list_duplicate_target_conflicts(
    import_id: int,
    db: Session = Depends(get_db),
) -> DuplicateTargetConflictListResponse:
    """返回同一批次中目标路径重复（会产生 duplicate_target 冲突）的任务分组。"""
    from collections import defaultdict
    rows = list(
        db.scalars(
            select(OrganizeTask)
            .where(OrganizeTask.import_id == import_id)
            .where(OrganizeTask.status == "pending")
            .order_by(OrganizeTask.id.asc())
        ).all()
    )
    groups: dict[str, list[OrganizeTask]] = defaultdict(list)
    for row in rows:
        groups[row.target_path].append(row)
    conflict_groups = [
        DuplicateTargetConflictGroup(
            target_path=target_path,
            tasks=[OrganizeTaskResponse.model_validate(t) for t in tasks],
        )
        for target_path, tasks in sorted(groups.items())
        if len(tasks) > 1
    ]
    return DuplicateTargetConflictListResponse(
        import_id=import_id,
        conflict_count=len(conflict_groups),
        groups=conflict_groups,
    )


@router.patch("/{task_id}", response_model=OrganizeTaskResponse)
def update_organize_task(
    task_id: int,
    payload: OrganizeTaskUpdateRequest,
    db: Session = Depends(get_db),
) -> OrganizeTaskResponse:
    """更新任务的目标路径或状态，用于手动解决 duplicate_target 冲突。"""
    task = db.scalar(select(OrganizeTask).where(OrganizeTask.id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail=f"OrganizeTask {task_id} not found")
    if payload.target_path is not None:
        task.target_path = payload.target_path.strip()
    if payload.status is not None:
        allowed = {"pending", "completed", "failed", "skipped"}
        if payload.status not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of: {sorted(allowed)}")
        task.status = payload.status
    db.commit()
    db.refresh(task)
    return OrganizeTaskResponse.model_validate(task)


@router.get("/ambiguous-conflicts", response_model=AmbiguousConflictListResponse)
def list_ambiguous_conflicts_json(
    import_id: int,
    db: Session = Depends(get_db),
) -> AmbiguousConflictListResponse:
    """返回 JSON 格式的歧义冲突列表（含关键词 ID，用于 UI 内联选择）。"""
    conflicts = OrganizeTaskService(db).list_ambiguous_conflicts(import_id=import_id)
    items = [
        AmbiguousConflictItem(
            source_path=c.source_path,
            keyword_options=[SchemaKeywordOption(id=opt.id, name=opt.name) for opt in c.keyword_options],
        )
        for c in conflicts
    ]
    return AmbiguousConflictListResponse(import_id=import_id, conflict_count=len(items), items=items)


@router.post("/ambiguous-conflicts/resolve", response_model=AmbiguousResolveResponse)
def resolve_ambiguous_conflicts_json(
    payload: AmbiguousResolveRequest,
    db: Session = Depends(get_db),
) -> AmbiguousResolveResponse:
    """接收 UI 选择的裁决，生成对应任务。"""
    resolutions = [{"source_path": r.source_path, "keyword_entry_id": r.keyword_entry_id} for r in payload.resolutions]
    tasks, replaced, skipped, errors = OrganizeTaskService(db).apply_ambiguous_resolutions_from_json(
        import_id=payload.import_id,
        resolutions=resolutions,
        replace_existing=payload.replace_existing,
    )
    return AmbiguousResolveResponse(
        import_id=payload.import_id,
        created_count=len(tasks),
        replaced_count=replaced,
        skipped_count=skipped,
        errors=errors,
    )


@router.get("/ambiguous-conflicts/export")
def export_ambiguous_conflicts(
    import_id: int,
    db: Session = Depends(get_db),
) -> Response:
    conflicts = OrganizeTaskService(db).list_ambiguous_conflicts(import_id=import_id)
    lines = ["source_path\tkeyword_count\tkeywords\tselected_keyword\tselected_keyword_id"]
    for item in conflicts:
        lines.append(f"{item.source_path}\t{item.keyword_count}\t{' | '.join(item.keywords)}\t\t")
    content = "\n".join(lines) + "\n"
    return Response(
        content=content,
        media_type="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="organize_task_ambiguous_conflicts_import_{import_id}.tsv"'
        },
    )


@router.post("/ambiguous-conflicts/import-tsv", response_model=AmbiguousConflictResolutionImportResponse)
async def import_ambiguous_conflicts_tsv(
    import_id: int,
    file: UploadFile = File(...),
    replace_existing: bool = True,
    db: Session = Depends(get_db),
) -> AmbiguousConflictResolutionImportResponse:
    try:
        raw = await file.read()
        tsv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="TSV must be UTF-8 encoded") from exc

    tasks, replaced_count, skipped_count, errors = OrganizeTaskService(db).apply_ambiguous_resolutions_from_tsv(
        import_id=import_id,
        tsv_text=tsv_text,
        replace_existing=replace_existing,
    )
    return AmbiguousConflictResolutionImportResponse(
        import_id=import_id,
        created_count=len(tasks),
        replaced_count=replaced_count,
        skipped_count=skipped_count,
        errors=errors,
        tasks=[OrganizeTaskResponse.model_validate(item) for item in tasks],
    )


@router.post("/node-details", response_model=NodeDetailResponse)
def get_task_node_details(
    payload: NodeDetailRequest,
    db: Session = Depends(get_db),
) -> NodeDetailResponse:
    """批量查询各任务关联节点的本地信息（raw_name / raw_path / remote_cid）。"""
    raw = OrganizeTaskService(db).get_node_details(task_ids=payload.task_ids)
    details = {tid: NodeDetailItem(**item) for tid, item in raw.items()}
    return NodeDetailResponse(details=details)


@router.get("/workbench", response_class=HTMLResponse)
def organize_tasks_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>关键词整理任务台</title>
  <style>
    :root { --bg:#f5efe6; --card:#fffaf2; --ink:#1f2421; --muted:#5b645f; --accent:#115e59; --soft:#d7ece8; --line:#ddd3c4; --warn:#9a6700; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f3ea 0%,#efe4d6 100%); color:var(--ink); }
    .shell { max-width:1280px; margin:0 auto; padding:28px 18px 40px; }
    .hero,.panel { background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 28px rgba(33,37,41,.06); }
    .hero { padding:24px; color:#fff; background:linear-gradient(135deg, rgba(17,94,89,.95), rgba(15,92,138,.92)); }
    .hero a { display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:0 14px; border-radius:14px; text-decoration:none; font-weight:600; background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.18); margin-right:10px; margin-top:14px; }
    .grid { display:grid; grid-template-columns:360px 1fr; gap:18px; margin-top:22px; }
    .panel { padding:20px; }
    label { display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }
    input, select, button { width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; }
    input, select { padding:12px 14px; background:#fff; }
    input[type="file"] { padding:10px 12px; }
    input[type="checkbox"] { width:auto; }
    button { padding:12px 14px; cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
    button.secondary { background:var(--soft); color:var(--accent); border:1px solid rgba(17,94,89,.18); }
    .actions { display:flex; gap:10px; margin-top:14px; }
    .actions button { flex:1; }
    .status,.box { margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; white-space:pre-wrap; font-size:13px; line-height:1.6; }
    .toggle-line { display:flex; gap:8px; align-items:center; margin-top:12px; color:var(--muted); font-size:13px; }
    .inline-link { display:none; margin-top:12px; }
    .inline-link a { display:inline-flex; align-items:center; justify-content:center; min-height:40px; padding:0 14px; border-radius:12px; text-decoration:none; font-weight:600; background:var(--soft); color:var(--accent); border:1px solid rgba(17,94,89,.18); }
    .list { display:grid; gap:12px; margin-top:14px; }
    .card { border:1px solid var(--line); border-radius:16px; padding:12px; background:#fff; }
    .task-row { display:flex; gap:12px; align-items:flex-start; }
    .task-row input[type="checkbox"] { width:18px; height:18px; margin-top:4px; accent-color:var(--accent); flex:0 0 auto; }
    .task-main { flex:1; }
    .badges { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
    .badge { background:#eee5d8; border-radius:999px; padding:4px 10px; font-size:12px; color:var(--muted); }
    .muted { color:var(--muted); font-size:13px; }
    .group { border:1px solid var(--line); border-radius:18px; padding:14px; background:linear-gradient(180deg,rgba(255,255,255,.98),rgba(245,238,227,.98)); }
    .group h3 { margin:0 0 10px; }
    .warning { color:var(--warn); }
    @media (max-width:940px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>关键词整理任务台</h1>
      <p>这里是整理主入口。系统会针对指定批次的目录树，只使用 active whitelist 关键词自动生成可整理任务，目标目录固定收口到 /根目录/已整理/安全化后的 canonical_name。</p>
      <a href="/keywords/workbench">返回关键词管理台</a>
      <a href="/plans/workbench">打开计划执行台</a>
      <a href="/workbench">返回统一工作台</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <h2>重建任务</h2>
        <label for="importSelect">导入批次</label>
        <select id="importSelect"></select>
        <div class="box">默认规则：
1. 只处理 active whitelist
2. 别名参与命中，但目录统一收口到 canonical_name
3. 目标目录固定为 /根目录/已整理/&lt;安全关键词目录名&gt;
4. 同一路径命中多个白名单关键词时会先跳过，避免误整理</div>
        <div class="actions">
          <button id="generateTasksBtn">重建本批次整理任务</button>
          <button class="secondary" id="refreshTasksBtn">刷新任务列表</button>
        </div>
        <div class="actions">
          <button class="secondary" id="exportConflictsBtn">导出冲突明细</button>
        </div>
        <label for="conflictResolutionFile" style="margin-top:14px;">导入冲突裁决 TSV</label>
        <input id="conflictResolutionFile" type="file" accept=".tsv,text/tab-separated-values,text/plain" />
        <label class="toggle-line"><input id="replaceConflictTasksCheckbox" type="checkbox" checked />导入时替换同路径已有任务</label>
        <div class="actions">
          <button class="secondary" id="importConflictsBtn">上传裁决并生成任务</button>
        </div>
        <h2 style="margin-top:22px;">手动生成任务</h2>
        <label for="manualKeywordEntryId">关键词 ID</label>
        <input id="manualKeywordEntryId" type="number" min="1" placeholder="例如：123" />
        <label for="manualTargetRoot">目标根目录</label>
        <input id="manualTargetRoot" value="/根目录/已整理/小千" placeholder="例如：/根目录/已整理/小千" />
        <div class="box">适用于冲突目录的人工裁决场景。输入关键词管理台里的关键词 ID，只为这个关键词单独生成任务，不再受多关键词冲突跳过限制。</div>
        <div class="actions">
          <button class="secondary" id="generateTasksFromKeywordBtn">按关键词手动生成任务</button>
        </div>
        <h2 style="margin-top:22px;">生成计划</h2>
        <div class="actions">
          <button class="secondary" id="selectFilteredBtn">全选当前任务</button>
          <button class="secondary" id="clearSelectedBtn">清空勾选</button>
        </div>
        <label for="statusFilter">任务状态筛选</label>
        <select id="statusFilter">
          <option value="">全部状态</option>
          <option value="pending">pending</option>
          <option value="completed">completed</option>
          <option value="failed">failed</option>
        </select>
        <div class="actions">
          <button class="secondary" id="generatePlanBtn">从勾选任务生成计划</button>
        </div>
        <h2 style="margin-top:22px;">重复目标冲突</h2>
        <div class="box">同一批次中目标路径相同的 pending 任务会在计划生成时触发 duplicate_target 冲突，可在此将其中一个改路径或跳过。</div>
        <div class="actions">
          <button class="secondary" id="loadDupConflictsBtn">查看重复目标冲突</button>
        </div>
        <div class="status" id="statusBox">先选择导入批次，再重建本批次的 whitelist 整理任务。</div>
        <div class="inline-link" id="planLinkBox"><a id="planLink" href="/plans/workbench">打开计划执行台（计划 #）</a></div>
      </aside>
      <section class="panel">
        <h2>重复目标冲突审核</h2>
        <div class="box" id="dupConflictMeta">点击左侧「查看重复目标冲突」后，冲突分组会显示在这里。</div>
        <div class="list" id="dupConflictList"></div>
        <h2 style="margin-top:22px;">按关键词分组的整理任务</h2>
        <div class="box" id="metaBox">任务列表会显示在这里。</div>
        <div class="list" id="taskList"></div>
      </section>
    </div>
  </div>
  <script>
    const importSelect = document.getElementById('importSelect');
    const statusBox = document.getElementById('statusBox');
    const metaBox = document.getElementById('metaBox');
    const taskList = document.getElementById('taskList');
    const planLinkBox = document.getElementById('planLinkBox');
    const planLink = document.getElementById('planLink');
    const statusFilter = document.getElementById('statusFilter');
    const selectedTaskIds = new Set();

    function currentFilter() {
      const importId = importSelect.value ? Number(importSelect.value) : null;
      const status = statusFilter.value || null;
      return { importId, status };
    }

    async function loadImports() {
      const response = await fetch('/imports/data?limit=100');
      const body = await response.json();
      const items = body.items || [];
      importSelect.innerHTML = '';
      items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = `#${item.id} · ${item.source_filename}`;
        importSelect.appendChild(option);
      });
    }

    async function loadTasks() {
      const { importId, status } = currentFilter();
      const params = new URLSearchParams();
      if (importId) params.set('import_id', String(importId));
      if (status) params.set('status', status);
      const response = await fetch(`/organize-tasks?${params.toString()}`);
      const filtered = await response.json();
      taskList.innerHTML = '';
      const importLabel = importSelect.options[importSelect.selectedIndex]?.textContent || '未选择导入批次';
      const statusLabel = status || '全部状态';
      if (!filtered.length) {
        metaBox.textContent = `当前筛选：${importLabel} / ${statusLabel}\n已勾选任务：${selectedTaskIds.size}\n当前批次还没有整理任务。`;
        return;
      }
      const groups = new Map();
      const statusCounts = new Map();
      for (const item of filtered) {
        const key = item.matched_canonical_name || '未命名关键词';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
        statusCounts.set(item.status, (statusCounts.get(item.status) || 0) + 1);
      }
      const statusSummary = [...statusCounts.entries()].map(([name, count]) => `${name}:${count}`).join(' / ');
      metaBox.textContent = `当前筛选：${importLabel} / ${statusLabel}\n当前显示 ${filtered.length} 条整理任务，按 ${groups.size} 个关键词分组。\n状态分布：${statusSummary}\n已勾选任务：${selectedTaskIds.size}`;
      [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh-CN')).forEach(([groupName, items]) => {
        const section = document.createElement('section');
        section.className = 'group';
        const sampleRoot = items[0]?.target_path.split('/').slice(0, 3).join('/') || '-';
        section.innerHTML = `
          <h3>${groupName}</h3>
          <div class="badges">
            <span class="badge">任务 ${items.length}</span>
            <span class="badge">目标目录 ${sampleRoot}</span>
          </div>
        `;
        const groupList = document.createElement('div');
        groupList.className = 'list';
        items.forEach(item => {
          const card = document.createElement('article');
          card.className = 'card';
          card.innerHTML = `
            <div class="task-row">
              <input type="checkbox" data-role="select-task" ${selectedTaskIds.has(item.id) ? 'checked' : ''} />
              <div class="task-main">
                <div><strong>${item.matched_canonical_name || '未命名关键词'}</strong></div>
                <div class="badges">
                  <span class="badge">任务 #${item.id}</span>
                  <span class="badge">${item.status}</span>
                </div>
                <div>${item.source_path}</div>
                <div style="margin-top:8px;color:#5b645f;">=> ${item.target_path}</div>
              </div>
            </div>
          `;
          card.querySelector('[data-role="select-task"]').addEventListener('change', event => {
            if (event.target.checked) {
              selectedTaskIds.add(item.id);
            } else {
              selectedTaskIds.delete(item.id);
            }
            metaBox.textContent = `当前筛选：${importLabel} / ${statusLabel}\n当前显示 ${filtered.length} 条整理任务，按 ${groups.size} 个关键词分组。\n状态分布：${statusSummary}\n已勾选任务：${selectedTaskIds.size}`;
          });
          groupList.appendChild(card);
        });
        section.appendChild(groupList);
        taskList.appendChild(section);
      });
    }

    async function selectFilteredTasks() {
      const { importId } = currentFilter();
      const params = new URLSearchParams();
      if (importId) params.set('import_id', String(importId));
      const response = await fetch(`/organize-tasks?${params.toString()}`);
      const filtered = await response.json();
      filtered.forEach(item => selectedTaskIds.add(item.id));
      statusBox.textContent = filtered.length ? `已勾选当前筛选结果，共 ${filtered.length} 条任务。` : '当前筛选结果为空。';
      await loadTasks();
    }

    async function clearSelectedTasks() {
      selectedTaskIds.clear();
      statusBox.textContent = '已清空勾选任务。';
      await loadTasks();
    }

    async function generateTasks() {
      planLinkBox.style.display = 'none';
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const response = await fetch('/organize-tasks/generate-from-import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          import_id: Number(importSelect.value),
          replace_existing: true
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '生成整理任务失败';
        return;
      }
      selectedTaskIds.clear();
      statusBox.textContent = `任务重建完成\\nimport_id: ${body.import_id}\\n删除旧任务: ${body.deleted_count}\\n新建任务: ${body.created_count}\\n跳过多关键词冲突: ${body.skipped_ambiguous_count}`;
      if (response.ok) {
        await loadTasks();
      }
    }

    function exportConflicts() {
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const importId = Number(importSelect.value);
      window.location.href = `/organize-tasks/ambiguous-conflicts/export?import_id=${importId}`;
      statusBox.textContent = `正在导出冲突明细\\nimport_id: ${importId}`;
    }

    async function importConflictResolutions() {
      planLinkBox.style.display = 'none';
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const fileInput = document.getElementById('conflictResolutionFile');
      const replaceExisting = document.getElementById('replaceConflictTasksCheckbox').checked;
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        statusBox.textContent = '请先选择要上传的 TSV 文件。';
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      statusBox.textContent = `正在导入冲突裁决\\nimport_id: ${Number(importSelect.value)}\\nfile: ${file.name}`;
      const response = await fetch(`/organize-tasks/ambiguous-conflicts/import-tsv?import_id=${Number(importSelect.value)}&replace_existing=${replaceExisting}`, {
        method: 'POST',
        body: formData
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '导入冲突裁决失败';
        return;
      }
      selectedTaskIds.clear();
      const errorSummary = body.errors && body.errors.length ? `\\n错误 ${body.errors.length} 条:\\n- ${body.errors.slice(0, 5).join('\\n- ')}` : '';
      statusBox.textContent = `冲突裁决导入完成\\nimport_id: ${body.import_id}\\n新建任务: ${body.created_count}\\n替换旧任务: ${body.replaced_count}\\n跳过记录: ${body.skipped_count}${errorSummary}`;
      fileInput.value = '';
      await loadTasks();
    }

    async function generateTasksFromKeyword() {
      planLinkBox.style.display = 'none';
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const keywordEntryId = Number(document.getElementById('manualKeywordEntryId').value);
      const targetRoot = document.getElementById('manualTargetRoot').value.trim();
      if (!keywordEntryId) {
        statusBox.textContent = '请先输入关键词 ID。';
        return;
      }
      if (!targetRoot) {
        statusBox.textContent = '请先输入目标根目录。';
        return;
      }
      const response = await fetch('/organize-tasks/generate-from-keyword', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          import_id: Number(importSelect.value),
          keyword_entry_id: keywordEntryId,
          target_root: targetRoot,
          replace_existing: true
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '按关键词生成任务失败';
        return;
      }
      selectedTaskIds.clear();
      statusBox.textContent = `按关键词生成任务完成\\nimport_id: ${body.import_id}\\nkeyword_entry_id: ${body.keyword_entry_id}\\n删除旧任务: ${body.deleted_count}\\n新建任务: ${body.created_count}\\n目标根目录: ${targetRoot}`;
      await loadTasks();
    }

    async function generatePlan() {
      planLinkBox.style.display = 'none';
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      if (!selectedTaskIds.size) {
        statusBox.textContent = '请先勾选要生成计划的任务。';
        return;
      }
      const response = await fetch('/plans/generate-from-tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          import_id: Number(importSelect.value),
          task_ids: Array.from(selectedTaskIds).sort((a, b) => a - b),
          dry_run: true
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '生成计划失败';
        return;
      }
      const firstPlan = body.plans[0];
      statusBox.textContent = `执行快照已生成\\nplans: ${body.total}\\nfirst_plan_id: ${firstPlan.id}\\nfirst_strategy: ${firstPlan.strategy_version}\\nfirst_items: ${firstPlan.items.length}`;
      planLink.href = `/plans/workbench`;
      planLink.textContent = `打开计划执行台（首个计划 #${firstPlan.id}，共 ${body.total} 个）`;
      planLinkBox.style.display = 'block';
    }

    const dupConflictMeta = document.getElementById('dupConflictMeta');
    const dupConflictList = document.getElementById('dupConflictList');

    async function loadDupConflicts() {
      if (!importSelect.value) {
        statusBox.textContent = '请先选择导入批次。';
        return;
      }
      const importId = Number(importSelect.value);
      dupConflictMeta.textContent = '正在加载重复目标冲突...';
      dupConflictList.innerHTML = '';
      const response = await fetch(`/organize-tasks/duplicate-conflicts?import_id=${importId}`);
      const body = await response.json();
      if (!response.ok) {
        dupConflictMeta.textContent = body.detail || '加载冲突失败';
        return;
      }
      if (!body.conflict_count) {
        dupConflictMeta.textContent = `当前批次 #${importId} 没有重复目标冲突。`;
        return;
      }
      dupConflictMeta.textContent = `批次 #${importId} 共 ${body.conflict_count} 组重复目标冲突，以下任务的 target_path 相同：`;
      for (const group of body.groups) {
        const section = document.createElement('section');
        section.className = 'group';
        section.innerHTML = `<h3 style="word-break:break-all;">${group.target_path}</h3><div class="badges"><span class="badge">冲突任务 ${group.tasks.length} 条</span></div>`;
        const list = document.createElement('div');
        list.className = 'list';
        for (const task of group.tasks) {
          const card = document.createElement('article');
          card.className = 'card';
          card.innerHTML = `
            <div><strong>#${task.id}</strong> · ${task.matched_canonical_name || '-'} · <span class="badge">${task.status}</span></div>
            <div class="muted" style="margin-top:6px;">来源: ${task.source_path}</div>
            <div style="margin-top:8px;">
              <label style="font-size:12px;color:var(--muted);">新目标路径（留空不改）</label>
              <input class="dup-new-target" type="text" placeholder="${task.target_path}" value="" style="margin-top:4px;" />
            </div>
            <div class="actions" style="margin-top:8px;">
              <button class="secondary btn-save-target" data-task-id="${task.id}">保存新路径</button>
              <button class="danger btn-skip-task" data-task-id="${task.id}">跳过此任务</button>
            </div>
          `;
          card.querySelector('.btn-save-target').addEventListener('click', async () => {
            const newTarget = card.querySelector('.dup-new-target').value.trim();
            if (!newTarget) { statusBox.textContent = '请填写新目标路径后再保存。'; return; }
            const r = await fetch(`/organize-tasks/${task.id}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ target_path: newTarget })
            });
            const b = await r.json();
            if (!r.ok) { statusBox.textContent = b.detail || '保存失败'; return; }
            statusBox.textContent = `任务 #${task.id} 目标路径已更新为：${b.target_path}`;
            await loadDupConflicts();
          });
          card.querySelector('.btn-skip-task').addEventListener('click', async () => {
            const r = await fetch(`/organize-tasks/${task.id}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: 'skipped' })
            });
            const b = await r.json();
            if (!r.ok) { statusBox.textContent = b.detail || '操作失败'; return; }
            statusBox.textContent = `任务 #${task.id} 已标记为 skipped。`;
            await loadDupConflicts();
            await loadTasks();
          });
          list.appendChild(card);
        }
        section.appendChild(list);
        dupConflictList.appendChild(section);
      }
    }

    document.getElementById('loadDupConflictsBtn').addEventListener('click', loadDupConflicts);
    document.getElementById('generateTasksBtn').addEventListener('click', generateTasks);
    document.getElementById('refreshTasksBtn').addEventListener('click', loadTasks);
    document.getElementById('exportConflictsBtn').addEventListener('click', exportConflicts);
    document.getElementById('importConflictsBtn').addEventListener('click', importConflictResolutions);
    document.getElementById('generateTasksFromKeywordBtn').addEventListener('click', generateTasksFromKeyword);
    document.getElementById('selectFilteredBtn').addEventListener('click', selectFilteredTasks);
    document.getElementById('clearSelectedBtn').addEventListener('click', clearSelectedTasks);
    document.getElementById('generatePlanBtn').addEventListener('click', generatePlan);
    importSelect.addEventListener('change', loadTasks);
    statusFilter.addEventListener('change', loadTasks);
    loadImports().then(loadTasks);
  </script>
</body>
</html>"""
