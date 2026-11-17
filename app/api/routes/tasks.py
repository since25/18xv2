from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
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
    DuplicateResolveRequest,
    DuplicateResolveResponse,
    DuplicateResolution,
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


@router.post("/resolve-duplicate-conflicts", response_model=DuplicateResolveResponse)
def resolve_duplicate_conflicts(
    payload: DuplicateResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DuplicateResolveResponse:
    """批量处理重复目标冲突：skip 未保留任务，可选从 115 删除。"""
    from sqlalchemy import select as _select
    from app.models.tree import TreeNode as _TreeNode

    client_115 = getattr(request.app.state, "client_115", None)
    resolved_count = 0
    deleted_from_115_count = 0
    errors: list[str] = []

    for res in payload.resolutions:
        # 1. 将 skip_task_ids 标记为 skipped
        skip_tasks = list(
            db.scalars(_select(OrganizeTask).where(OrganizeTask.id.in_(res.skip_task_ids))).all()
        )
        for t in skip_tasks:
            t.status = "skipped"
        db.flush()
        resolved_count += 1

        # 2. 可选：从 115 删除
        if res.delete_from_115 and client_115 is not None and skip_tasks:
            node_ids = [t.node_id for t in skip_tasks if t.node_id is not None]
            if node_ids:
                nodes = list(
                    db.scalars(_select(_TreeNode).where(_TreeNode.id.in_(node_ids))).all()
                )
                for node in nodes:
                    if not node.remote_cid:
                        errors.append(f"节点 {node.id}（{node.raw_path}）无 remote_cid，跳过删除")
                        continue
                    try:
                        client_115.delete_node(file_id=node.remote_cid, dry_run=False)
                        deleted_from_115_count += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"删除 {node.raw_path}（cid={node.remote_cid}）失败：{exc}")

    db.commit()
    return DuplicateResolveResponse(
        resolved_count=resolved_count,
        deleted_from_115_count=deleted_from_115_count,
        errors=errors,
    )
