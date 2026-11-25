"""脚本中心：运行记录扩展、脚本配置、配置修改记录和 sehuatang 帖子表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261125_0018"
down_revision = "20261102_0017"
branch_labels = None
depends_on = None


# 默认配置与 Unraid 现状一致（2026-11-25 核对）；三个脚本初始都仍由 Unraid 运行。
DEFAULT_CONFIGS = [
    {
        "job_name": "sehuatang",
        "executor": "unraid",
        "enabled": False,
        "run_time": "01:28",
        "params": {
            "pages": 4,
            "forum_url": "https://sehuatang.org/forum.php?mod=forumdisplay&fid=2&typeid=684&filter=typeid&page={page}",
            "qb_category": "国产BT",
        },
    },
    {
        "job_name": "MOVE_SSD_CACHE_TO_DISK2",
        "executor": "unraid",
        "enabled": False,
        "run_time": "01:01",
        "params": {
            "source_dir": "/mnt/cache/docker1/SSD_cache/已整理",
            "target_dir": "/mnt/disk2/qbbtdn/已整理",
        },
    },
    {
        "job_name": "DEL_SOMETHING",
        "executor": "unraid",
        "enabled": False,
        "run_time": "12:09",
        "params": {
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
    },
]

NEW_RUN_COLUMNS = ("pid", "error_reason", "log_path", "dry_run", "trigger")


def upgrade() -> None:
    with op.batch_alter_table("script_runs") as batch:
        batch.alter_column("finished_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.alter_column("exit_code", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("trigger", sa.String(16), nullable=False, server_default="report"))
        batch.add_column(sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("log_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("error_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pid", sa.Integer(), nullable=True))

    configs = op.create_table(
        "script_job_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("executor", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("run_time", sa.String(5), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_name", name="uq_script_job_configs_job_name"),
    )
    op.bulk_insert(configs, DEFAULT_CONFIGS)

    op.create_table(
        "script_job_config_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
    )
    op.create_index("ix_script_job_config_changes_job_name", "script_job_config_changes", ["job_name"])

    op.create_table(
        "sehuatang_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tid", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_outcome", sa.String(32), nullable=False),
        sa.Column(
            "last_run_id",
            sa.Integer(),
            sa.ForeignKey("script_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tid", name="uq_sehuatang_posts_tid"),
    )
    op.create_index("ix_sehuatang_posts_last_outcome", "sehuatang_posts", ["last_outcome"])


def downgrade() -> None:
    op.drop_index("ix_sehuatang_posts_last_outcome", table_name="sehuatang_posts")
    op.drop_table("sehuatang_posts")
    op.drop_index("ix_script_job_config_changes_job_name", table_name="script_job_config_changes")
    op.drop_table("script_job_config_changes")
    op.drop_table("script_job_configs")
    # 18x 自己产生的排队/运行中记录可能没有结束时间和退出码，补齐后才能恢复非空约束
    op.execute("UPDATE script_runs SET exit_code = -1 WHERE exit_code IS NULL")
    op.execute("UPDATE script_runs SET finished_at = started_at WHERE finished_at IS NULL")
    with op.batch_alter_table("script_runs") as batch:
        for column in NEW_RUN_COLUMNS:
            batch.drop_column(column)
        batch.alter_column("exit_code", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("finished_at", existing_type=sa.DateTime(timezone=True), nullable=False)
