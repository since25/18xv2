"""女优档案、待删清单与删除批次的接口。

这里只做参数校验、调用服务、错误转换和组织返回，不含新的业务规则。
固定路径（/by-media、/candidates、/delete-batches 等）必须声明在 `/{actress_id}` 之前，
否则会被当成女优 id 解析而返回 422。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import os
from typing import Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.core.config import Settings, get_settings
from app.models.actresses import (
    Actress,
    ActressAlias,
    ActressDeleteBatch,
    ActressDeleteBatchFilm,
    ActressDeleteCandidate,
    ActressKeptFilm,
    ActressMark,
)
from app.models.jellyfin import JellyfinMediaItem
from app.schemas.actresses import (
    ActressAliasRequest,
    ActressCandidateListResponse,
    ActressCandidateSelectRequest,
    ActressCountResponse,
    ActressDeleteBatchDetail,
    ActressDeleteBatchListResponse,
    ActressDeleteBatchStartResponse,
    ActressDetail,
    ActressFilmDirsRequest,
    ActressJobResponse,
    ActressKeptListResponse,
    ActressListResponse,
    ActressMergeRequest,
    ActressStatus,
    ActressStatusRequest,
    ActressStatusResponse,
    MediaActorsResponse,
)
from app.services.actresses.archive_service import (
    ACTRESS_STATUSES,
    ActressError,
    ArchiveService,
    require_strm_roots,
)
from app.services.actresses.candidates_service import CandidateService
from app.services.actresses.delete_batch_service import CandidateListChanged, DeleteBatchService
from app.services.actresses.delete_guard import PathMapper, parse_path_map
from app.services.actresses.films import load_films, read_nfo_title
from app.services.actresses.job_runner import (
    JOB_DELETE,
    JOB_REFRESH,
    actress_delete_ready,
    actress_enabled,
    delete_work,
    refresh_work,
)
from app.services.actresses.names import normalize_actress_name
from app.services.actresses.rules import RuleContext
from app.services.background_job_service import BackgroundJobService
from app.services.jellyfin.client import JellyfinClient
from app.services.jellyfin.job_runner import jellyfin_sync_enabled
from app.services.job_runner import JobAlreadyRunning, create_job, submit_job


router = APIRouter(prefix="/actresses", tags=["actresses"])

T = TypeVar("T")

# 一次「检查 115」最多处理的部数，网页按这个数分批调用
_CHECK_REMOTE_LIMIT = 50
# 可以续跑的批次状态；running 指上次执行被打断、任务已不在跑的批次
_RESUMABLE_STATUSES = ("failed", "interrupted", "running")
_DELETE_RUNNING = "女优删除任务正在运行，请等它结束"


# ---------- 公共小函数 ----------


def _strm_roots(settings: Settings) -> list[str]:
    return list(getattr(settings, "media_library_strm_roots", []) or [])


def _require_enabled(settings: Settings) -> None:
    """女优功能关闭时拒绝会改档案、改清单或起任务的请求。"""
    if not actress_enabled(settings):
        raise HTTPException(status_code=409, detail="女优功能未开启（需要打开 ACTRESS_ENABLED 和 Jellyfin 扫描）")


def _require_delete_ready(settings: Settings) -> None:
    if not actress_delete_ready(settings):
        raise HTTPException(
            status_code=409,
            detail="女优删除未就绪：需要开启女优功能，并配置 porn_tv1、302porn_tv1 两个可写根目录",
        )


def _start_job(db: Session, job_type: str, busy_detail: str) -> str:
    try:
        return create_job(db, job_type)
    except JobAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=busy_detail) from exc


def _get_actress(db: Session, actress_id: int) -> Actress:
    actress = db.get(Actress, actress_id)
    if actress is None:
        raise HTTPException(status_code=404, detail="女优不存在")
    return actress


def _change_and_reconcile(
    db: Session, strm_roots: list[str], action: str, change: Callable[[], T]
) -> tuple[T, int, int]:
    """改档案后按新档案重算待删清单，返回（改动结果, 新加入部数, 移出部数）；业务错误转 400。

    先确认根目录已配置：否则档案改了、清单却重算失败。
    """
    try:
        require_strm_roots(strm_roots, action)
        result = change()
        added, removed = CandidateService().reconcile(db, strm_roots=strm_roots, added_by="mark")
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result, added, removed


def _candidate_counts(db: Session, strm_roots: list[str]) -> Counter[int]:
    """每位女优在当前待删清单里作为黑名单演员出现的部数，一次读完整个清单。

    「黑名单演员」的判断与清单页的「因为谁」相同（RuleContext.actor_status），只是不读 NFO 标题。
    """
    film_dirs = set(db.scalars(select(ActressDeleteCandidate.film_dir)))
    context = RuleContext.load(db)
    counts: Counter[int] = Counter()
    for film in load_films(db, strm_roots=strm_roots, film_dirs=film_dirs):
        # 同一部片里两个名字对应同一位女优时只算一次
        counts.update(
            {
                context.name_index[normalize_actress_name(name)]
                for name in film.actor_names
                if context.actor_status(name) == "blacklist"
            }
        )
    return counts


def _summaries(db: Session, actresses: list[Actress], candidate_counts: Counter[int]) -> list[dict]:
    """女优列表行；别名一次查出。"""
    aliases: dict[int, list[str]] = {}
    ids = [actress.id for actress in actresses]
    if ids:
        rows = db.execute(
            select(ActressAlias.actress_id, ActressAlias.alias)
            .where(ActressAlias.actress_id.in_(ids))
            .order_by(ActressAlias.id)
        )
        for actress_id, alias in rows:
            aliases.setdefault(actress_id, []).append(alias)
    return [
        {
            "id": actress.id,
            "canonical_name": actress.canonical_name,
            "aliases": aliases.get(actress.id, []),
            "status": actress.status,
            "film_count": actress.film_count,
            "candidate_count": candidate_counts.get(actress.id, 0),
        }
        for actress in actresses
    ]


def _detail(db: Session, actress: Actress, strm_roots: list[str]) -> dict:
    """女优详情：列表行字段 + 标记记录（新的在前）+ 她的片子（同片演员状态、是否受保护、是否在清单里）。"""
    context = RuleContext.load(db)
    candidate_dirs = set(db.scalars(select(ActressDeleteCandidate.film_dir)))
    films = []
    for film in load_films(db, strm_roots=strm_roots):
        owner_ids = {context.name_index.get(normalize_actress_name(name)) for name in film.actor_names}
        if actress.id not in owner_ids:
            continue
        films.append(
            {
                "film_dir": film.film_dir,
                "number": film.number,
                "title": read_nfo_title(film),
                "actors": [{"name": name, "status": context.actor_status(name)} for name in film.actor_names],
                "protected": bool(context.verdict(film).protected_by),
                "in_candidates": film.film_dir in candidate_dirs,
            }
        )
    marks = db.scalars(
        select(ActressMark)
        .where(ActressMark.actress_id == actress.id)
        .order_by(ActressMark.created_at.desc(), ActressMark.id.desc())
    ).all()
    summary = _summaries(db, [actress], _candidate_counts(db, strm_roots))[0]
    return {
        **summary,
        "marks": [
            {
                "from_status": mark.from_status,
                "to_status": mark.to_status,
                "source": mark.source,
                "media_item_id": mark.media_item_id,
                "note": mark.note,
                "created_at": mark.created_at,
            }
            for mark in marks
        ],
        "films": films,
    }


def _batch_summary(batch: ActressDeleteBatch) -> dict:
    return {
        "id": batch.id,
        "job_id": batch.job_id,
        "status": batch.status,
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "finished_at": batch.finished_at,
        "deleted_films": batch.deleted_films,
        "failed_films": batch.failed_films,
        "skipped_films": batch.skipped_films,
        "jellyfin_refresh": batch.jellyfin_refresh,
        "note": batch.note,
    }


def _get_batch(db: Session, batch_id: int) -> ActressDeleteBatch:
    batch = db.get(ActressDeleteBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="删除批次不存在")
    return batch


def _submit_delete(db: Session, batch: ActressDeleteBatch, job_id: str, request: Request) -> dict:
    """把任务编号写回批次后再交给后台执行（避免和后台会话同时写这一行）。"""
    batch.job_id = job_id
    db.commit()
    submit_job(job_id, delete_work(batch.id, request.app.state.client_115))
    return {"batch_id": batch.id, "job_id": job_id}


# ---------- 固定路径（必须在 /{actress_id} 之前） ----------


@router.get("", response_model=ActressListResponse)
def list_actresses(
    status_filter: ActressStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    sort: Literal["film_count", "name"] = Query(default="film_count"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    conditions = []
    if status_filter is not None:
        conditions.append(Actress.status == status_filter)
    # 按女优名的归一化规则搜规范名和别名
    keyword = normalize_actress_name(q or "")
    if keyword:
        alias_owners = select(ActressAlias.actress_id).where(
            ActressAlias.alias_normalized.icontains(keyword, autoescape=True)
        )
        conditions.append(
            or_(Actress.canonical_name_normalized.icontains(keyword, autoescape=True), Actress.id.in_(alias_owners))
        )
    total = int(db.scalar(select(func.count()).select_from(Actress).where(*conditions)) or 0)
    if sort == "film_count":
        order = (Actress.film_count.desc(), Actress.canonical_name, Actress.id)
    else:
        order = (Actress.canonical_name, Actress.id)
    rows = db.scalars(
        select(Actress).where(*conditions).order_by(*order).offset((page - 1) * page_size).limit(page_size)
    ).all()
    counts = dict.fromkeys(ACTRESS_STATUSES, 0)
    counts.update(dict(db.execute(select(Actress.status, func.count()).group_by(Actress.status)).all()))
    strm_roots = _strm_roots(get_settings())
    return {"items": _summaries(db, list(rows), _candidate_counts(db, strm_roots)), "total": total, "counts": counts}


@router.get("/by-media", response_model=MediaActorsResponse)
def actors_by_media(
    jellyfin_item_id: str | None = Query(default=None),
    path: str | None = Query(default=None, description="STRM 文件路径或番号目录"),
    db: Session = Depends(get_db),
) -> dict:
    """按片查演员（给播放器）：按 NFO 顺序返回演员和状态，档案里没有的当场建档（未标）。"""
    settings = get_settings()
    _require_enabled(settings)
    if bool(jellyfin_item_id) == bool(path):
        raise HTTPException(status_code=400, detail="jellyfin_item_id 和 path 必须传且只能传一个")

    valid_item = (JellyfinMediaItem.source == "strm_115", JellyfinMediaItem.active.is_(True))
    if jellyfin_item_id:
        item = db.execute(
            select(JellyfinMediaItem.id, JellyfinMediaItem.path)
            .where(*valid_item, JellyfinMediaItem.jellyfin_item_id == jellyfin_item_id)
            .limit(1)
        ).first()
        film_dir = os.path.dirname(item.path) if item else None
    else:
        normalized = os.path.normpath(path)
        item = db.execute(
            select(JellyfinMediaItem.id, JellyfinMediaItem.path).where(
                *valid_item, JellyfinMediaItem.path == normalized
            )
        ).first()
        # 传的是 STRM 路径就取它所在的番号目录，否则按番号目录本身查
        film_dir = os.path.dirname(item.path) if item else normalized
    films = load_films(db, strm_roots=_strm_roots(settings), film_dirs={film_dir}) if film_dir else []
    if not films:
        raise HTTPException(status_code=404, detail="找不到这部片")
    film = films[0]
    # 播放器改状态时回传：按条目查的用这个条目，按番号目录查的用这部片第一个条目
    media_item_id = item.id if item else film.media_item_ids[0]

    try:
        actresses = ArchiveService().ensure_actresses(db, list(film.actor_names))
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    in_candidates = (
        db.scalar(select(ActressDeleteCandidate.id).where(ActressDeleteCandidate.film_dir == film.film_dir))
        is not None
    )
    return {
        "film_dir": film.film_dir,
        "number": film.number,
        "media_item_id": media_item_id,
        "in_candidates": in_candidates,
        "actors": [
            {"actress_id": actress.id, "name": name, "status": actress.status}
            for name, actress in zip(film.actor_names, actresses)
        ],
    }


@router.post("/status", response_model=ActressStatusResponse)
def set_actress_status(payload: ActressStatusRequest, db: Session = Depends(get_db)) -> dict:
    """批量改状态，再重算待删清单，返回状态有变化的人数和清单增减部数。"""
    settings = get_settings()
    _require_enabled(settings)
    if payload.media_item_id is not None and db.get(JellyfinMediaItem, payload.media_item_id) is None:
        raise HTTPException(status_code=400, detail=f"片子条目不存在：{payload.media_item_id}")
    changed, added, removed = _change_and_reconcile(
        db,
        _strm_roots(settings),
        "改女优状态",
        lambda: ArchiveService().set_status(
            db,
            payload.actress_ids,
            payload.status,
            source=payload.source,
            media_item_id=payload.media_item_id,
        ),
    )
    return {"changed": changed, "candidates_added": added, "candidates_removed": removed}


@router.post("/refresh", response_model=ActressJobResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_refresh(db: Session = Depends(get_db)) -> dict:
    """手动刷新女优档案和待删清单（与每日任务的女优步骤相同）。"""
    settings = get_settings()
    _require_enabled(settings)
    try:
        require_strm_roots(_strm_roots(settings), "刷新女优档案")
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = _start_job(db, JOB_REFRESH, "女优刷新任务正在运行，请等它结束")
    submit_job(job_id, refresh_work)
    return {"job_id": job_id}


@router.get("/candidates", response_model=ActressCandidateListResponse)
def list_candidates(db: Session = Depends(get_db)) -> dict:
    views = CandidateService().list(db, strm_roots=_strm_roots(get_settings()))
    items = [
        {
            "film_dir": view.film_dir,
            "number": view.number,
            "title": view.title,
            "selected": view.selected,
            "added_by": view.added_by,
            "added_at": view.added_at,
            "black_names": view.black_names,
            "other_actors": [{"name": name, "status": actor_status} for name, actor_status in view.other_actors],
            "remote_state": view.remote_state,
            "remote_note": view.remote_note,
        }
        for view in views
    ]
    return {"items": items, "total": len(items), "selected": sum(1 for view in views if view.selected)}


@router.post("/candidates/select", response_model=ActressCountResponse)
def select_candidates(payload: ActressCandidateSelectRequest, db: Session = Depends(get_db)) -> dict:
    _require_enabled(get_settings())
    return {"count": CandidateService().set_selected(db, payload.film_dirs, payload.selected)}


@router.post("/candidates/keep", response_model=ActressCountResponse)
def keep_candidates(payload: ActressFilmDirsRequest, db: Session = Depends(get_db)) -> dict:
    _require_enabled(get_settings())
    return {"count": CandidateService().keep(db, payload.film_dirs)}


@router.post("/candidates/check-remote", response_model=ActressCountResponse)
def check_candidates_remote(payload: ActressFilmDirsRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """只读检查这些片子在 115 上还能不能找到，一次最多 50 部；不删任何文件。"""
    settings = get_settings()
    _require_enabled(settings)
    if len(payload.film_dirs) > _CHECK_REMOTE_LIMIT:
        raise HTTPException(status_code=400, detail=f"一次最多检查 {_CHECK_REMOTE_LIMIT} 部，请分批")
    try:
        mapper = PathMapper(parse_path_map(settings.actress_path_map))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"ACTRESS_PATH_MAP 配置有误：{exc}") from exc
    try:
        count = CandidateService().check_remote(
            db,
            payload.film_dirs,
            request.app.state.client_115,
            strm_roots=_strm_roots(settings),
            mapper=mapper,
        )
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": count}


@router.get("/kept", response_model=ActressKeptListResponse)
def list_kept(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(ActressKeptFilm).order_by(ActressKeptFilm.created_at.desc(), ActressKeptFilm.id.desc())
    ).all()
    return {
        "items": [
            {"film_dir": row.film_dir, "number": os.path.basename(row.film_dir), "created_at": row.created_at}
            for row in rows
        ]
    }


@router.post("/kept/remove", response_model=ActressCountResponse)
def remove_kept(payload: ActressFilmDirsRequest, db: Session = Depends(get_db)) -> dict:
    """撤销保留，仍应删的片子重新回到清单。"""
    settings = get_settings()
    _require_enabled(settings)
    try:
        count = CandidateService().unkeep(db, payload.film_dirs, strm_roots=_strm_roots(settings))
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": count}


@router.get("/delete-batches", response_model=ActressDeleteBatchListResponse)
def list_delete_batches(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(ActressDeleteBatch).order_by(ActressDeleteBatch.id.desc())).all()
    return {"items": [_batch_summary(batch) for batch in rows]}


@router.post(
    "/delete-batches", response_model=ActressDeleteBatchStartResponse, status_code=status.HTTP_202_ACCEPTED
)
def create_delete_batch(
    payload: ActressFilmDirsRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """把网页上勾选并确认的片子建成删除批次并交给后台执行。

    只删请求里的这些片子；其中有已不在待删清单里的（页面过期）返回 409，让用户刷新后再确认。
    """
    settings = get_settings()
    # 先看删除任务是否在跑：在跑时直接拒绝，不建一个没人执行的批次
    if BackgroundJobService.list_active(db, JOB_DELETE):
        raise HTTPException(status_code=409, detail=_DELETE_RUNNING)
    _require_delete_ready(settings)
    try:
        batch = DeleteBatchService().create_batch(db, strm_roots=_strm_roots(settings), film_dirs=payload.film_dirs)
    except CandidateListChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job_id = create_job(db, JOB_DELETE)
    except JobAlreadyRunning as exc:
        # 极小的竞态：建批次期间另一个删除任务启动了；待执行批次不能续跑，删掉免得留下孤儿
        db.delete(batch)
        db.commit()
        raise HTTPException(status_code=409, detail=_DELETE_RUNNING) from exc
    return _submit_delete(db, batch, job_id, request)


@router.get("/delete-batches/{batch_id}", response_model=ActressDeleteBatchDetail)
def get_delete_batch(batch_id: int, db: Session = Depends(get_db)) -> dict:
    """批次详情：每部片的状态、跳过原因、错误和文件行。"""
    batch = db.scalar(
        select(ActressDeleteBatch)
        .where(ActressDeleteBatch.id == batch_id)
        .options(selectinload(ActressDeleteBatch.films).selectinload(ActressDeleteBatchFilm.files))
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="删除批次不存在")
    films = [
        {
            "id": film.id,
            "film_dir": film.film_dir,
            "number": film.number,
            "status": film.status,
            "reason": film.reason,
            "error": film.error,
            "finished_at": film.finished_at,
            "files": [
                {
                    "id": file.id,
                    "group": file.group,
                    "target": file.target,
                    "remote_file_id": file.remote_file_id,
                    "status": file.status,
                    "error": file.error,
                    "executed_at": file.executed_at,
                }
                for file in film.files
            ],
        }
        for film in batch.films
    ]
    return {**_batch_summary(batch), "films": films}


@router.post(
    "/delete-batches/{batch_id}/resume",
    response_model=ActressDeleteBatchStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_delete_batch(batch_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    """续跑失败、中断或执行被打断的批次：只处理待执行和失败的片子。"""
    _require_delete_ready(get_settings())
    batch = _get_batch(db, batch_id)
    if batch.status not in _RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"批次状态是 {batch.status}，只有 failed、interrupted、running 的批次可以续跑",
        )
    job_id = _start_job(db, JOB_DELETE, _DELETE_RUNNING)
    return _submit_delete(db, batch, job_id, request)


# ---------- 单个女优 ----------


@router.get("/{actress_id}", response_model=ActressDetail)
def get_actress(actress_id: int, db: Session = Depends(get_db)) -> dict:
    actress = _get_actress(db, actress_id)
    return _detail(db, actress, _strm_roots(get_settings()))


@router.get("/{actress_id}/image")
def get_actress_image(actress_id: int, db: Session = Depends(get_db)) -> Response:
    """按规范名转发 Jellyfin 人物主图；Jellyfin 未配置或取不到都返回 404，网页显示占位。"""
    settings = get_settings()
    actress = _get_actress(db, actress_id)
    if not jellyfin_sync_enabled(settings):
        raise HTTPException(status_code=404, detail="Jellyfin 未配置，没有头像")
    with JellyfinClient(
        settings.jellyfin_base_url,
        settings.jellyfin_api_key,
        settings.jellyfin_timeout_seconds,
        settings.jellyfin_page_size,
    ) as client:
        image = client.get_person_image(actress.canonical_name)
    if image is None:
        raise HTTPException(status_code=404, detail="Jellyfin 里取不到她的头像")
    content, content_type = image
    return Response(content=content, media_type=content_type)


@router.post("/{actress_id}/aliases", response_model=ActressDetail)
def add_actress_alias(actress_id: int, payload: ActressAliasRequest, db: Session = Depends(get_db)) -> dict:
    """加别名后重算清单（别名会改变演员归属）。"""
    settings = get_settings()
    _require_enabled(settings)
    actress = _get_actress(db, actress_id)
    strm_roots = _strm_roots(settings)
    _change_and_reconcile(db, strm_roots, "改别名", lambda: ArchiveService().add_alias(db, actress.id, payload.alias))
    return _detail(db, actress, strm_roots)


@router.delete("/{actress_id}/aliases/{alias_id}", response_model=ActressDetail)
def remove_actress_alias(actress_id: int, alias_id: int, db: Session = Depends(get_db)) -> dict:
    """删别名后重算清单。"""
    settings = get_settings()
    _require_enabled(settings)
    actress = _get_actress(db, actress_id)
    strm_roots = _strm_roots(settings)
    _change_and_reconcile(
        db, strm_roots, "改别名", lambda: ArchiveService().remove_alias(db, actress.id, alias_id)
    )
    return _detail(db, actress, strm_roots)


@router.post("/{actress_id}/merge", response_model=ActressDetail)
def merge_actress(actress_id: int, payload: ActressMergeRequest, db: Session = Depends(get_db)) -> dict:
    """把这位女优合并进 into_id，返回合并后的女优详情，并重算清单。"""
    settings = get_settings()
    _require_enabled(settings)
    _get_actress(db, actress_id)
    strm_roots = _strm_roots(settings)
    target, _added, _removed = _change_and_reconcile(
        db, strm_roots, "合并女优", lambda: ArchiveService().merge(db, actress_id, payload.into_id)
    )
    return _detail(db, target, strm_roots)
