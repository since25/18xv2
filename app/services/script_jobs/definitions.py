"""三个脚本的固定定义：名称、互斥组、超时、参数校验和默认值。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import posixpath
import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session


JOB_NAMES: tuple[str, ...] = ("sehuatang", "MOVE_SSD_CACHE_TO_DISK2", "DEL_SOMETHING")

# 容器里挂载的两个媒体根目录；页面上能选的目录只能在它们下面
ALLOWED_ROOTS: tuple[str, ...] = ("/mnt/cache/docker1/SSD_cache", "/mnt/disk2/qbbtdn")

RUN_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def validate_run_time(value: str) -> str:
    """运行时间必须是两位数的 HH:MM。"""
    if not isinstance(value, str) or not RUN_TIME_RE.match(value):
        raise ValueError("运行时间格式应为 HH:MM，例如 01:28")
    return value


def validate_media_dir(value: str) -> str:
    """目录必须是规范的绝对路径，并且位于容器已挂载的媒体根目录之下。"""
    if not value.startswith("/") or posixpath.normpath(value) != value:
        raise ValueError(f"目录必须是规范的绝对路径：{value}")
    for root in ALLOWED_ROOTS:
        if value == root or value.startswith(root + "/"):
            return value
    raise ValueError(f"目录不在容器已挂载的目录下（只能选 {'、'.join(ALLOWED_ROOTS)} 之下）：{value}")


class SehuatangParams(BaseModel):
    pages: int = Field(ge=1, le=20)
    forum_url: str
    qb_category: str = Field(min_length=1, max_length=64)

    @field_validator("forum_url")
    @classmethod
    def _check_forum_url(cls, value: str) -> str:
        if not value.startswith("https://") or "{page}" not in value:
            raise ValueError("版块地址必须以 https:// 开头，并包含 {page} 页码占位")
        return value

    @field_validator("qb_category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("qB 分类不能为空")
        return value


class MoveParams(BaseModel):
    source_dir: str
    target_dir: str

    @field_validator("source_dir", "target_dir")
    @classmethod
    def _check_dir(cls, value: str) -> str:
        return validate_media_dir(value)


class OrganizeJob(BaseModel):
    scan_root: str
    target_root: str

    @field_validator("scan_root", "target_root")
    @classmethod
    def _check_dir(cls, value: str) -> str:
        return validate_media_dir(value)


class DelParams(BaseModel):
    delete_dirs: list[str] = Field(min_length=1, max_length=20)
    organize_jobs: list[OrganizeJob] = Field(default_factory=list, max_length=30)
    merge_on_conflict: bool
    fix_permissions: bool

    @field_validator("delete_dirs")
    @classmethod
    def _check_dirs(cls, value: list[str]) -> list[str]:
        return [validate_media_dir(item) for item in value]


@dataclass(frozen=True)
class PreparedCommand:
    """子进程的命令行和环境变量。"""

    argv: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class RunContext:
    run_id: int
    job_name: str
    # 启动时的参数快照；运行中改配置不影响本次运行
    params: dict
    dry_run: bool
    run_dir: Path


@dataclass(frozen=True)
class RunOutcome:
    status: str
    counts: dict[str, int]
    items: list[dict]
    error_reason: str | None


@dataclass(frozen=True)
class JobDefinition:
    name: str
    label: str
    # 同组任务互斥：后到的排队
    group: str
    timeout_seconds: int
    # 本阶段能否在 18x 执行（MOVE、DEL 留给后续阶段）
    runnable: bool
    params_model: type[BaseModel]
    default_run_time: str
    default_params: dict
    # 启动前准备命令；结束后把输出整理成结果
    prepare: Callable[[Session, RunContext], PreparedCommand] | None = None
    finalize: Callable[[Session, RunContext, int], RunOutcome] | None = None


def _sehuatang_prepare(db: Session, ctx: RunContext) -> PreparedCommand:
    # 延迟导入，避免 definitions 与 sehuatang_task 循环引用
    from app.services.script_jobs import sehuatang_task

    return sehuatang_task.prepare(db, ctx)


def _sehuatang_finalize(db: Session, ctx: RunContext, exit_code: int) -> RunOutcome:
    from app.services.script_jobs import sehuatang_task

    return sehuatang_task.finalize(db, ctx, exit_code)


DEFINITIONS: dict[str, JobDefinition] = {
    "sehuatang": JobDefinition(
        name="sehuatang",
        label="色花堂抓取",
        group="sehuatang",
        timeout_seconds=3600,
        runnable=True,
        params_model=SehuatangParams,
        default_run_time="01:28",
        default_params={
            "pages": 4,
            "forum_url": "https://sehuatang.org/forum.php?mod=forumdisplay&fid=2&typeid=684&filter=typeid&page={page}",
            "qb_category": "国产BT",
        },
        prepare=_sehuatang_prepare,
        finalize=_sehuatang_finalize,
    ),
    "MOVE_SSD_CACHE_TO_DISK2": JobDefinition(
        name="MOVE_SSD_CACHE_TO_DISK2",
        label="搬运脚本",
        group="media",
        timeout_seconds=21600,
        runnable=False,
        params_model=MoveParams,
        default_run_time="01:01",
        default_params={
            "source_dir": "/mnt/cache/docker1/SSD_cache/已整理",
            "target_dir": "/mnt/disk2/qbbtdn/已整理",
        },
    ),
    "DEL_SOMETHING": JobDefinition(
        name="DEL_SOMETHING",
        label="整理脚本",
        group="media",
        timeout_seconds=10800,
        runnable=False,
        params_model=DelParams,
        default_run_time="12:09",
        default_params={
            "delete_dirs": [
                "/mnt/cache/docker1/SSD_cache",
                "/mnt/disk2/qbbtdn/00000000000000000/scripts",
                "/mnt/disk2/qbbtdn/已整理",
            ],
            "organize_jobs": [
                {"scan_root": "/mnt/cache/docker1/SSD_cache/finish", "target_root": "/mnt/cache/docker1/SSD_cache/已整理"},
                {"scan_root": "/mnt/cache/docker1/SSD_cache/telegram", "target_root": "/mnt/cache/docker1/SSD_cache/已整理"},
                {"scan_root": "/mnt/disk2/qbbtdn/00000000000000000/scripts", "target_root": "/mnt/disk2/qbbtdn/已整理"},
                {"scan_root": "/mnt/cache/docker1/SSD_cache/已整理/抖音", "target_root": "/mnt/cache/docker1/SSD_cache/已整理"},
                {"scan_root": "/mnt/disk2/qbbtdn/已整理/抖音", "target_root": "/mnt/disk2/qbbtdn/已整理"},
                {"scan_root": "/mnt/cache/docker1/SSD_cache/已整理/抖音风", "target_root": "/mnt/cache/docker1/SSD_cache/已整理"},
                {"scan_root": "/mnt/disk2/qbbtdn/已整理/抖音风", "target_root": "/mnt/disk2/qbbtdn/已整理"},
            ],
            "merge_on_conflict": True,
            "fix_permissions": True,
        },
    ),
}


def get_definition(name: str) -> JobDefinition:
    """按脚本名取定义；未知名称抛 KeyError。"""
    return DEFINITIONS[name]
