from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_115_client, get_db
from app.models.organization import BatchPlanOperationLog, ExecutionJob, OrganizationPlan
from app.schemas.plans import (
    BatchDeletePlanRequest,
    BatchExecutePlanRequest,
    BatchPlanOperationLogResponse,
    BatchPlanOperationResponse,
    ExecutePlanRequest,
    JobResponse,
    KeywordMovePlanGenerateRequest,
    OrganizeTaskPlanGenerateRequest,
    PlanBatchResponse,
    PlanResponse,
    PlanGenerateRequest,
    PlanSummaryPageResponse,
    PlanSummaryResponse,
)
from app.services.client_115.client import Real115Client
from app.services.executor.executor import PlanExecutor
from app.services.planner.plan_service import PlanService
from app.services.strategy_rule_service import StrategyRuleService

router = APIRouter(prefix="/plans", tags=["plans"])


def _dump_json_list(values: list[int] | list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _load_json_int_list(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[int] = []
    for item in parsed:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _load_json_str_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _to_batch_log_response(log: BatchPlanOperationLog) -> BatchPlanOperationLogResponse:
    return BatchPlanOperationLogResponse(
        id=log.id,
        action=log.action,
        requested_count=log.requested_count,
        processed_count=log.processed_count,
        requested_plan_ids=_load_json_int_list(log.requested_plan_ids),
        processed_plan_ids=_load_json_int_list(log.processed_plan_ids),
        skipped_plan_ids=_load_json_int_list(log.skipped_plan_ids),
        errors=_load_json_str_list(log.error_details),
        requested_by=log.requested_by,
        operator_note=log.operator_note,
        created_at=log.created_at,
    )


def _list_plan_summaries(
    db: Session,
    *,
    min_item_count: int | None = None,
    max_item_count: int | None = None,
    latest_job_status: str | None = None,
    include_completed: bool = True,
) -> list[PlanSummaryResponse]:
    plans = list(
        db.scalars(
            select(OrganizationPlan)
            .order_by(OrganizationPlan.id.desc())
            .options(selectinload(OrganizationPlan.items), selectinload(OrganizationPlan.jobs))
        ).all()
    )
    summaries: list[PlanSummaryResponse] = []
    for plan in plans:
        latest_job = max(plan.jobs, key=lambda item: item.id) if plan.jobs else None
        summaries.append(
            PlanSummaryResponse(
                id=plan.id,
                strategy_version=plan.strategy_version,
                scope_desc=plan.scope_desc,
                status=plan.status,
                dry_run=plan.dry_run,
                created_at=plan.created_at,
                item_count=len(plan.items),
                latest_job_id=latest_job.id if latest_job else None,
                latest_job_status=latest_job.status if latest_job else None,
                latest_job_dry_run=latest_job.dry_run if latest_job else None,
            )
        )
    filtered: list[PlanSummaryResponse] = []
    for summary in summaries:
        if min_item_count is not None and summary.item_count < min_item_count:
            continue
        if max_item_count is not None and summary.item_count > max_item_count:
            continue
        if latest_job_status:
            normalized_filter = latest_job_status.strip().lower()
            normalized_actual = (summary.latest_job_status or "none").strip().lower()
            if normalized_filter != normalized_actual:
                continue
        elif not include_completed and (summary.latest_job_status or "").strip().lower() == "completed":
            continue
        filtered.append(summary)
    return filtered


@router.get("")
def plans_index() -> RedirectResponse:
    return RedirectResponse(url="/plans/workbench", status_code=307)


@router.get("/data", response_model=PlanSummaryPageResponse)
def list_plans(
    min_item_count: int | None = None,
    max_item_count: int | None = None,
    latest_job_status: str | None = None,
    include_completed: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> PlanSummaryPageResponse:
    summaries = _list_plan_summaries(
        db,
        min_item_count=min_item_count,
        max_item_count=max_item_count,
        latest_job_status=latest_job_status,
        include_completed=include_completed,
    )
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    return PlanSummaryPageResponse(total=len(summaries), items=summaries[safe_offset : safe_offset + safe_limit])


@router.post("/batch-execute", response_model=BatchPlanOperationResponse)
def batch_execute_plans(
    payload: BatchExecutePlanRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
) -> BatchPlanOperationResponse:
    executor = PlanExecutor(db, client=client_115)
    jobs: list[JobResponse] = []
    errors: list[str] = []
    processed_count = 0
    processed_plan_ids: list[int] = []
    seen_plan_ids: list[int] = []
    for plan_id in payload.plan_ids:
        if plan_id in seen_plan_ids:
            continue
        seen_plan_ids.append(plan_id)
        try:
            job = executor.execute_plan(
                plan_id=plan_id,
                dry_run=payload.dry_run,
                confirm_real_run=payload.confirm_real_run,
                requested_by=payload.requested_by,
                operator_note=payload.operator_note,
            )
            hydrated = db.scalar(
                select(ExecutionJob)
                .where(ExecutionJob.id == job.id)
                .options(selectinload(ExecutionJob.logs), selectinload(ExecutionJob.rollback_records))
            )
            if hydrated is not None:
                jobs.append(JobResponse.model_validate(hydrated))
            processed_count += 1
            processed_plan_ids.append(plan_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"plan_id={plan_id}: {exc}")
    db.add(
        BatchPlanOperationLog(
            action="batch_execute",
            requested_count=len(payload.plan_ids),
            processed_count=processed_count,
            requested_plan_ids=_dump_json_list(payload.plan_ids),
            processed_plan_ids=_dump_json_list(processed_plan_ids),
            skipped_plan_ids=_dump_json_list([]),
            error_details=_dump_json_list(errors),
            requested_by=payload.requested_by,
            operator_note=payload.operator_note,
        )
    )
    db.commit()
    return BatchPlanOperationResponse(
        requested_count=len(payload.plan_ids),
        processed_count=processed_count,
        jobs=jobs,
        errors=errors,
    )


@router.post("/batch-delete", response_model=BatchPlanOperationResponse)
def batch_delete_plans(payload: BatchDeletePlanRequest, db: Session = Depends(get_db)) -> BatchPlanOperationResponse:
    deleted_plan_ids: list[int] = []
    skipped_plan_ids: list[int] = []
    for plan_id in payload.plan_ids:
        plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan_id))
        if plan is None:
            skipped_plan_ids.append(plan_id)
            continue
        db.delete(plan)
        deleted_plan_ids.append(plan_id)
    db.add(
        BatchPlanOperationLog(
            action="batch_delete",
            requested_count=len(payload.plan_ids),
            processed_count=len(deleted_plan_ids),
            requested_plan_ids=_dump_json_list(payload.plan_ids),
            processed_plan_ids=_dump_json_list(deleted_plan_ids),
            skipped_plan_ids=_dump_json_list(skipped_plan_ids),
            error_details=_dump_json_list([]),
        )
    )
    db.commit()
    return BatchPlanOperationResponse(
        requested_count=len(payload.plan_ids),
        processed_count=len(deleted_plan_ids),
        deleted_plan_ids=deleted_plan_ids,
        skipped_plan_ids=skipped_plan_ids,
    )


@router.get("/batch-logs", response_model=list[BatchPlanOperationLogResponse])
def list_batch_operation_logs(limit: int = 10, db: Session = Depends(get_db)) -> list[BatchPlanOperationLogResponse]:
    safe_limit = max(1, min(limit, 50))
    logs = list(
        db.scalars(select(BatchPlanOperationLog).order_by(BatchPlanOperationLog.id.desc()).limit(safe_limit)).all()
    )
    return [_to_batch_log_response(log) for log in logs]


@router.post("/generate", response_model=PlanResponse)
def generate_plan(payload: PlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plan = service.generate_plan(
            import_id=payload.import_id,
            strategy_version=payload.strategy_version,
            dry_run=payload.dry_run,
            node_ids=payload.node_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
    return PlanResponse.model_validate(plan)


@router.post("/keyword-generate", response_model=PlanResponse)
def generate_keyword_move_plan(payload: KeywordMovePlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plan = service.generate_keyword_move_plan(
            import_id=payload.import_id,
            keyword=payload.keyword,
            target_path=payload.target_path,
            dry_run=payload.dry_run,
            keyword_entry_id=payload.keyword_entry_id,
            case_sensitive=payload.case_sensitive,
            node_ids=payload.node_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
    return PlanResponse.model_validate(plan)


@router.post("/generate-from-tasks", response_model=PlanBatchResponse)
def generate_plan_from_organize_tasks(payload: OrganizeTaskPlanGenerateRequest, db: Session = Depends(get_db)) -> PlanResponse:
    service = PlanService(db, StrategyRuleService(db).build_classifier())
    try:
        plans = service.generate_plan_from_tasks(
            import_id=payload.import_id,
            dry_run=payload.dry_run,
            keyword_entry_id=payload.keyword_entry_id,
            task_ids=payload.task_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hydrated_plans = [
        db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan.id).options(selectinload(OrganizationPlan.items)))
        for plan in plans
    ]
    return PlanBatchResponse(total=len(hydrated_plans), plans=[PlanResponse.model_validate(plan) for plan in hydrated_plans if plan is not None])


@router.get("/workbench", response_class=HTMLResponse)
def plans_workbench() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>计划执行台</title>
  <style>
    :root {
      --bg: #f5efe6;
      --card: #fffaf2;
      --ink: #1f2421;
      --muted: #5b645e;
      --accent: #0f5c8a;
      --accent-soft: #dcebf4;
      --line: #ddd3c4;
      --danger: #9a3412;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", sans-serif;
      background: linear-gradient(135deg, #f8f2e8 0%, #eee4d7 100%);
      color: var(--ink);
    }
    .shell { max-width: 1320px; margin: 0 auto; padding: 28px 18px 40px; }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 26px;
      box-shadow: 0 12px 28px rgba(33,37,41,.06);
    }
    .hero {
      padding: 26px;
      background: linear-gradient(135deg, rgba(15,92,138,.95), rgba(35,48,58,.9));
      color: #f8f4ee;
    }
    .hero h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 42px); }
    .hero p { margin: 0; max-width: 820px; line-height: 1.6; color: rgba(248,244,238,.88); }
    .hero-links {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }
    .hero-links a {
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
    .grid {
      display: grid;
      grid-template-columns: 380px 1fr;
      gap: 18px;
      margin-top: 22px;
    }
    .panel { padding: 20px; }
    h2 { margin: 0 0 14px; font-size: 18px; }
    button, select, input {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      font: inherit;
    }
    select, input { padding: 12px 14px; background: #fff; }
    button {
      padding: 12px 14px;
      border: none;
      background: var(--accent);
      color: white;
      font-weight: 600;
      cursor: pointer;
    }
    button.secondary {
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(15,92,138,.18);
    }
    button.danger {
      background: var(--danger);
    }
    .actions { display: flex; gap: 10px; margin-top: 14px; }
    .actions button { flex: 1; }
    .actions.compact button { flex: 1; min-width: 0; }
    .filters {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .pager {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 14px;
      flex-wrap: wrap;
    }
    .pager button {
      width: auto;
      min-width: 120px;
    }
    .pager span {
      color: var(--muted);
      font-size: 13px;
    }
    .status, .detail {
      margin-top: 14px;
      padding: 12px;
      border-radius: 16px;
      background: #f3ece2;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
    }
    .list {
      display: grid;
      gap: 14px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(245,238,227,.98));
    }
    .plan-row {
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }
    .plan-row input[type="checkbox"] {
      width: 18px;
      height: 18px;
      margin-top: 4px;
      accent-color: var(--accent);
      flex: 0 0 auto;
    }
    .plan-main { flex: 1; }
    .card h3 {
      margin: 0 0 10px;
      font-size: 18px;
      word-break: break-word;
    }
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
    .paths, .logs {
      display: grid;
      gap: 10px;
      font-size: 13px;
      line-height: 1.5;
      color: var(--muted);
    }
    .log-item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px;
      background: #fff;
    }
    .error-list {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .error-item {
      border: 1px solid rgba(154,52,18,.18);
      border-radius: 14px;
      padding: 10px;
      background: #fff6f3;
      color: var(--danger);
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .history-item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: #fff;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
    }
    @media (max-width: 960px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>计划执行台</h1>
      <p>这里集中查看整理计划、最近一次执行状态和日志摘要。计划默认先 dry-run，确认后再做真实执行。</p>
      <div class="hero-links">
        <a href="/workbench">返回统一工作台</a>
        <a href="/keywords/workbench">返回关键词管理台</a>
        <a href="/organize-tasks/workbench">打开整理任务台</a>
      </div>
    </section>
    <div class="grid">
      <aside class="panel">
        <h2>执行快照控制</h2>
        <select id="planSelect"></select>
        <input id="requestedByInput" placeholder="执行人，可选" />
        <input id="operatorNoteInput" placeholder="备注，可选" />
        <label style="display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--muted);font-size:13px;"><input id="confirmRealRunCheckbox" type="checkbox" style="width:auto;" />确认我知道这会执行真实操作</label>
        <div class="actions">
          <button id="refreshBtn" class="secondary">刷新计划</button>
          <button id="loadBtn">查看详情</button>
        </div>
        <div class="actions">
          <button id="dryRunBtn" class="secondary">执行 Dry Run</button>
          <button id="realRunBtn" class="danger">真实执行</button>
        </div>
        <div class="filters">
          <input id="minItemCountInput" type="number" min="0" placeholder="最少项数，如 1" />
          <input id="maxItemCountInput" type="number" min="0" placeholder="最多项数，如 20" />
          <select id="latestJobStatusFilter">
            <option value="">全部最近任务状态</option>
            <option value="completed">completed</option>
            <option value="running">running</option>
            <option value="pending">pending</option>
            <option value="failed">failed</option>
            <option value="none">无最近任务</option>
          </select>
          <input id="pageSizeInput" type="number" min="1" max="200" value="30" />
          <label style="display:flex;gap:8px;align-items:center;color:var(--muted);font-size:13px;"><input id="showCompletedCheckbox" type="checkbox" style="width:auto;" />显示最近任务为 completed 的计划</label>
        </div>
        <div class="actions compact">
          <button id="selectAllBtn" class="secondary">全选当前列表</button>
          <button id="clearSelectedBtn" class="secondary">清空勾选</button>
        </div>
        <div class="actions">
          <button id="batchDryRunBtn" class="secondary">批量 Dry Run</button>
          <button id="batchRealRunBtn" class="danger">批量真实执行</button>
        </div>
        <div class="actions">
          <button id="batchDeleteBtn" class="secondary">删除勾选计划</button>
        </div>
        <div class="status" id="statusBox">先选择一个计划，然后查看详情或执行。</div>
        <div class="detail" id="summaryBox">计划摘要会显示在这里。</div>
      </aside>
      <section class="panel">
        <h2>执行快照列表</h2>
        <div class="pager">
          <button id="prevPageBtn" class="secondary">上一页</button>
          <button id="nextPageBtn" class="secondary">下一页</button>
          <span id="pageInfo">第 1 / 1 页</span>
        </div>
        <div class="list" id="planList"></div>
        <h2 style="margin-top:22px;">执行日志</h2>
        <div class="logs" id="jobLogs">
          <div class="detail">选中计划后，会显示最近一次执行的日志摘要。</div>
        </div>
        <h2 style="margin-top:22px;">批量错误</h2>
        <div class="error-list" id="errorList">
          <div class="detail">批量执行或批量删除时的失败原因会显示在这里。</div>
        </div>
        <h2 style="margin-top:22px;">最近批量操作</h2>
        <div class="error-list" id="batchLogList">
          <div class="detail">最近的批量执行和批量删除记录会显示在这里。</div>
        </div>
      </section>
    </div>
  </div>
  <script>
    const planSelect = document.getElementById('planSelect');
    const statusBox = document.getElementById('statusBox');
    const summaryBox = document.getElementById('summaryBox');
    const planList = document.getElementById('planList');
    const jobLogs = document.getElementById('jobLogs');
    const errorList = document.getElementById('errorList');
    const batchLogList = document.getElementById('batchLogList');
    const minItemCountInput = document.getElementById('minItemCountInput');
    const maxItemCountInput = document.getElementById('maxItemCountInput');
    const latestJobStatusFilter = document.getElementById('latestJobStatusFilter');
    const pageSizeInput = document.getElementById('pageSizeInput');
    const showCompletedCheckbox = document.getElementById('showCompletedCheckbox');
    const pageInfo = document.getElementById('pageInfo');
    const requestedByInput = document.getElementById('requestedByInput');
    const operatorNoteInput = document.getElementById('operatorNoteInput');
    const state = { plans: [], currentPlan: null, currentJob: null, selectedPlanIds: new Set(), total: 0, page: 1 };

    function selectedPlanId() {
      return planSelect.value ? Number(planSelect.value) : null;
    }

    function renderPlans() {
      planList.innerHTML = '';
      if (!state.plans.length) {
        planList.innerHTML = '<div class="detail">还没有生成任何计划。</div>';
        pageInfo.textContent = '第 1 / 1 页';
        return;
      }
      for (const plan of state.plans) {
        const article = document.createElement('article');
        article.className = 'card';
        article.innerHTML = `
          <div class="plan-row">
            <input type="checkbox" data-role="select-plan" ${state.selectedPlanIds.has(plan.id) ? 'checked' : ''} />
            <div class="plan-main">
              <h3>#${plan.id} · ${plan.strategy_version}</h3>
              <div class="badges">
                <span class="badge">项数 ${plan.item_count}</span>
                <span class="badge">状态 ${plan.status}</span>
                <span class="badge">快照 dry_run ${plan.dry_run}</span>
                <span class="badge">最近任务 ${plan.latest_job_status || '无'}</span>
              </div>
              <div class="paths">${plan.scope_desc}</div>
            </div>
          </div>
        `;
        article.querySelector('[data-role="select-plan"]').addEventListener('change', event => {
          if (event.target.checked) {
            state.selectedPlanIds.add(plan.id);
          } else {
            state.selectedPlanIds.delete(plan.id);
          }
        });
        planList.appendChild(article);
      }
      const totalPages = Math.max(1, Math.ceil(state.total / currentPageSize()));
      pageInfo.textContent = `第 ${state.page} / ${totalPages} 页，共 ${state.total} 条`;
    }

    function renderJobLogs(job) {
      jobLogs.innerHTML = '';
      if (!job) {
        jobLogs.innerHTML = '<div class="detail">还没有执行日志。</div>';
        return;
      }
      const successCount = job.logs.filter(item => item.success).length;
      const failureCount = job.logs.length - successCount;
      const summary = document.createElement('div');
      summary.className = 'detail';
      summary.textContent = `job_id=${job.id}\\nplan_id=${job.plan_id}\\nstatus=${job.status}\\ndry_run=${job.dry_run}\\nrequested_by=${job.requested_by || '-'}\\nrollback_status=${job.rollback_status}\\nsuccess=${successCount}\\nfailure=${failureCount}`;
      jobLogs.appendChild(summary);
      if (job.rollback_records && job.rollback_records.length) {
        const rollback = document.createElement('div');
        rollback.className = 'detail';
        rollback.textContent = `rollback_records=${job.rollback_records.length}\\nlatest=${job.rollback_records.slice(0, 3).map(item => `${item.undo_action}:${item.status}`).join(', ')}`;
        jobLogs.appendChild(rollback);
      }
      for (const log of job.logs.slice(0, 30)) {
        const article = document.createElement('article');
        article.className = 'log-item';
        article.textContent = `${log.success ? 'OK' : 'ERR'} | ${log.api_status}\\n${log.before_path}\\n=> ${log.after_path}${log.error_message ? '\\n' + log.error_message : ''}`;
        jobLogs.appendChild(article);
      }
    }

    function renderErrors(errors, emptyMessage = '当前没有批量错误。') {
      errorList.innerHTML = '';
      if (!errors || !errors.length) {
        errorList.innerHTML = `<div class="detail">${emptyMessage}</div>`;
        return;
      }
      for (const item of errors) {
        const article = document.createElement('article');
        article.className = 'error-item';
        article.textContent = item;
        errorList.appendChild(article);
      }
    }

    function renderBatchLogs(logs) {
      batchLogList.innerHTML = '';
      if (!logs || !logs.length) {
        batchLogList.innerHTML = '<div class="detail">还没有批量操作记录。</div>';
        return;
      }
      for (const log of logs) {
        const article = document.createElement('article');
        article.className = 'history-item';
        article.textContent = [
          `#${log.id} | ${log.action} | ${log.created_at}`,
          `requested=${log.requested_count} processed=${log.processed_count}`,
          `requested_ids=${(log.requested_plan_ids || []).join(', ') || '无'}`,
          `processed_ids=${(log.processed_plan_ids || []).join(', ') || '无'}`,
          `skipped_ids=${(log.skipped_plan_ids || []).join(', ') || '无'}`,
          `requested_by=${log.requested_by || '-'}`,
          `operator_note=${log.operator_note || '-'}`,
          `errors=${(log.errors || []).length ? log.errors.join(' | ') : '无'}`
        ].join('\\n');
        batchLogList.appendChild(article);
      }
    }

    async function loadBatchLogs() {
      const response = await fetch('/plans/batch-logs?limit=10');
      const body = await response.json();
      if (!response.ok) {
        batchLogList.innerHTML = `<div class="detail">${body.detail || '读取批量操作记录失败。'}</div>`;
        return;
      }
      renderBatchLogs(body || []);
    }

    function currentPageSize() {
      return Math.max(1, Math.min(200, Number(pageSizeInput.value) || 30));
    }

    function buildPlanListParams() {
      const params = new URLSearchParams();
      if (minItemCountInput.value.trim()) {
        params.set('min_item_count', minItemCountInput.value.trim());
      }
      if (maxItemCountInput.value.trim()) {
        params.set('max_item_count', maxItemCountInput.value.trim());
      }
      if (latestJobStatusFilter.value) {
        params.set('latest_job_status', latestJobStatusFilter.value);
      }
      params.set('include_completed', showCompletedCheckbox.checked ? 'true' : 'false');
      params.set('limit', String(currentPageSize()));
      params.set('offset', String((state.page - 1) * currentPageSize()));
      return params;
    }

    async function loadPlans(preferredId = null) {
      const response = await fetch(`/plans/data?${buildPlanListParams().toString()}`);
      const body = await response.json();
      state.plans = body.items || [];
      state.total = body.total || 0;
      planSelect.innerHTML = '';
      for (const plan of state.plans) {
        const option = document.createElement('option');
        option.value = plan.id;
        option.textContent = `#${plan.id} · ${plan.strategy_version} · ${plan.item_count}项`;
        planSelect.appendChild(option);
      }
      if (preferredId && state.plans.some(item => item.id === preferredId)) {
        planSelect.value = String(preferredId);
      }
      renderPlans();
    }

    async function loadPlanDetail() {
      const planId = selectedPlanId();
      if (!planId) {
        statusBox.textContent = '请先选择一个计划。';
        return;
      }
      statusBox.textContent = '正在读取计划详情...';
      const response = await fetch(`/plans/${planId}`);
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '读取计划失败';
        return;
      }
      state.currentPlan = body;
      const itemPreview = body.items.slice(0, 5).map(item => `${item.source_path} => ${item.suggested_target_path}`).join('\\n');
      summaryBox.textContent = `plan_id=${body.id}\\nstrategy=${body.strategy_version}\\nitems=${body.items.length}\\nstatus=${body.status}\\n\\n前5条:\\n${itemPreview || '无'}\\n\\n真实执行前需要勾选确认。`;
      const selectedPlan = state.plans.find(item => item.id === planId);
      if (selectedPlan && selectedPlan.latest_job_id) {
        await loadJob(selectedPlan.latest_job_id, false);
      } else {
        renderJobLogs(null);
      }
      statusBox.textContent = '计划详情已载入。';
    }

    async function loadJob(jobId, updateStatus = true) {
      const response = await fetch(`/jobs/${jobId}`);
      const body = await response.json();
      if (!response.ok) {
        if (updateStatus) {
          statusBox.textContent = body.detail || '读取任务失败';
        }
        return;
      }
      state.currentJob = body;
      renderJobLogs(body);
      if (updateStatus) {
        statusBox.textContent = `已载入 job #${jobId}`;
      }
    }

    async function executePlan(dryRun) {
      const planId = selectedPlanId();
      if (!planId) {
        statusBox.textContent = '请先选择一个计划。';
        return;
      }
      statusBox.textContent = dryRun ? '正在执行 dry-run...' : '正在执行真实任务...';
      const response = await fetch(`/plans/${planId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dry_run: dryRun,
          confirm_real_run: dryRun ? false : document.getElementById('confirmRealRunCheckbox').checked,
          requested_by: requestedByInput.value,
          operator_note: operatorNoteInput.value
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '执行失败';
        return;
      }
      await loadPlans(planId);
      summaryBox.textContent = `plan_id=${body.plan_id}\\njob_id=${body.id}\\nstatus=${body.status}\\ndry_run=${body.dry_run}\\nrequested_by=${body.requested_by || '-'}\\nrollback_status=${body.rollback_status}\\nlogs=${body.logs.length}`;
      renderJobLogs(body);
      statusBox.textContent = dryRun ? 'dry-run 完成。' : '真实执行完成。';
    }

    function selectedPlanIds() {
      return Array.from(state.selectedPlanIds).sort((a, b) => a - b);
    }

    function syncSelectedPlansFromVisible() {
      state.plans.forEach(plan => state.selectedPlanIds.add(plan.id));
      renderPlans();
      statusBox.textContent = `已勾选 ${state.selectedPlanIds.size} 个计划。`;
    }

    function clearSelectedPlans() {
      state.selectedPlanIds.clear();
      renderPlans();
      statusBox.textContent = '已清空勾选计划。';
    }

    async function batchExecutePlans(dryRun) {
      const ids = selectedPlanIds();
      if (!ids.length) {
        statusBox.textContent = '请先勾选要执行的计划。';
        return;
      }
      statusBox.textContent = dryRun ? '正在批量执行 dry-run...' : '正在批量执行真实任务...';
      const response = await fetch('/plans/batch-execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_ids: ids,
          dry_run: dryRun,
          confirm_real_run: dryRun ? false : document.getElementById('confirmRealRunCheckbox').checked,
          requested_by: requestedByInput.value,
          operator_note: operatorNoteInput.value
        })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '批量执行失败';
        renderErrors(body.errors || [body.detail || '批量执行失败'], '批量执行失败原因会显示在这里。');
        return;
      }
      await loadPlans();
      const successJobs = body.jobs || [];
      summaryBox.textContent = `批量执行完成\nrequested=${body.requested_count}\nprocessed=${body.processed_count}\nerrors=${body.errors.length}\njob_ids=${successJobs.map(item => item.id).join(', ') || '无'}`;
      if (successJobs.length) {
        renderJobLogs(successJobs[successJobs.length - 1]);
      }
      statusBox.textContent = body.errors.length
        ? `批量执行完成，但有 ${body.errors.length} 个错误。`
        : (dryRun ? '批量 dry-run 完成。' : '批量真实执行完成。');
      renderErrors(body.errors || [], '当前没有批量执行错误。');
      await loadBatchLogs();
    }

    async function batchDeletePlans() {
      const ids = selectedPlanIds();
      if (!ids.length) {
        statusBox.textContent = '请先勾选要删除的计划。';
        return;
      }
      const response = await fetch('/plans/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_ids: ids })
      });
      const body = await response.json();
      if (!response.ok) {
        statusBox.textContent = body.detail || '删除计划失败';
        renderErrors(body.errors || [body.detail || '删除计划失败'], '批量删除失败原因会显示在这里。');
        return;
      }
      body.deleted_plan_ids.forEach(id => state.selectedPlanIds.delete(id));
      await loadPlans();
      statusBox.textContent = `已删除 ${body.deleted_plan_ids.length} 个计划。`;
      summaryBox.textContent = `deleted=${body.deleted_plan_ids.join(', ') || '无'}\nskipped=${body.skipped_plan_ids.join(', ') || '无'}`;
      const deleteErrors = [];
      if (body.skipped_plan_ids && body.skipped_plan_ids.length) {
        deleteErrors.push(`这些计划未找到，已跳过：${body.skipped_plan_ids.join(', ')}`);
      }
      renderErrors(deleteErrors, '当前没有批量删除错误。');
      await loadBatchLogs();
      if (selectedPlanId()) {
        await loadPlanDetail();
      } else {
        renderJobLogs(null);
      }
    }

    async function reloadFromFirstPage() {
      state.page = 1;
      await loadPlans(selectedPlanId());
    }

    async function goPrevPage() {
      if (state.page <= 1) return;
      state.page -= 1;
      await loadPlans();
    }

    async function goNextPage() {
      const totalPages = Math.max(1, Math.ceil(state.total / currentPageSize()));
      if (state.page >= totalPages) return;
      state.page += 1;
      await loadPlans();
    }

    document.getElementById('refreshBtn').addEventListener('click', () => reloadFromFirstPage());
    document.getElementById('loadBtn').addEventListener('click', loadPlanDetail);
    document.getElementById('dryRunBtn').addEventListener('click', () => executePlan(true));
    document.getElementById('realRunBtn').addEventListener('click', () => executePlan(false));
    document.getElementById('selectAllBtn').addEventListener('click', syncSelectedPlansFromVisible);
    document.getElementById('clearSelectedBtn').addEventListener('click', clearSelectedPlans);
    document.getElementById('batchDryRunBtn').addEventListener('click', () => batchExecutePlans(true));
    document.getElementById('batchRealRunBtn').addEventListener('click', () => batchExecutePlans(false));
    document.getElementById('batchDeleteBtn').addEventListener('click', batchDeletePlans);
    document.getElementById('prevPageBtn').addEventListener('click', goPrevPage);
    document.getElementById('nextPageBtn').addEventListener('click', goNextPage);
    minItemCountInput.addEventListener('change', reloadFromFirstPage);
    maxItemCountInput.addEventListener('change', reloadFromFirstPage);
    latestJobStatusFilter.addEventListener('change', reloadFromFirstPage);
    pageSizeInput.addEventListener('change', reloadFromFirstPage);
    showCompletedCheckbox.addEventListener('change', reloadFromFirstPage);
    planSelect.addEventListener('change', loadPlanDetail);
    renderErrors([], '批量执行或批量删除时的失败原因会显示在这里。');
    loadBatchLogs();
    loadPlans();
  </script>
</body>
</html>"""


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: int, db: Session = Depends(get_db)) -> PlanResponse:
    plan = db.scalar(select(OrganizationPlan).where(OrganizationPlan.id == plan_id).options(selectinload(OrganizationPlan.items)))
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse.model_validate(plan)


@router.post("/{plan_id}/execute", response_model=JobResponse)
def execute_plan(
    plan_id: int,
    payload: ExecutePlanRequest,
    db: Session = Depends(get_db),
    client_115: Real115Client = Depends(get_115_client),
) -> JobResponse:
    executor = PlanExecutor(db, client=client_115)
    try:
        job = executor.execute_plan(
            plan_id=plan_id,
            dry_run=payload.dry_run,
            confirm_real_run=payload.confirm_real_run,
            requested_by=payload.requested_by,
            operator_note=payload.operator_note,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    job = db.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.id == job.id)
        .options(selectinload(ExecutionJob.logs), selectinload(ExecutionJob.rollback_records))
    )
    return JobResponse.model_validate(job)
