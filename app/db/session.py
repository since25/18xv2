from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine_kwargs = {"future": True}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 1800

engine = create_engine(settings.database_url, **engine_kwargs)

if settings.database_url.startswith("sqlite"):
    # SQLite 默认不启用外键约束，模型里声明的 ondelete=CASCADE/SET NULL 全部不生效，
    # 删除导入批次后 keyword_hits / organize_tasks 等表会留下指向不存在记录的幽灵行。
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
