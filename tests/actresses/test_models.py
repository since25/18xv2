from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.actresses import (
    Actress,
    ActressAlias,
    ActressDeleteBatch,
    ActressDeleteBatchFile,
    ActressDeleteBatchFilm,
    ActressDeleteCandidate,
    JellyfinMediaActor,
)
from app.models.jellyfin import JellyfinMediaItem


def _enable_foreign_keys(db_session):
    """测试库默认不开 SQLite 外键，要验证数据库级联必须先打开。"""
    db_session.commit()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")


def _count(db_session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model))


def test_actress_alias_normalized_is_unique(db_session):
    actress = Actress(canonical_name="甲", canonical_name_normalized="甲")
    db_session.add(actress)
    db_session.flush()
    db_session.add_all(
        [
            ActressAlias(actress_id=actress.id, alias="乙", alias_normalized="乙"),
            ActressAlias(actress_id=actress.id, alias="乙 ", alias_normalized="乙"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_media_item_cascades_actor_rows(db_session):
    _enable_foreign_keys(db_session)
    item = JellyfinMediaItem(source="porn_tv1", path="/媒体/甲/ABC-001/ABC-001.strm")
    db_session.add(item)
    db_session.flush()
    db_session.add_all(
        [
            JellyfinMediaActor(media_item_id=item.id, position=0, raw_name="甲", name_normalized="甲"),
            JellyfinMediaActor(media_item_id=item.id, position=1, raw_name="乙", name_normalized="乙"),
        ]
    )
    db_session.commit()
    assert _count(db_session, JellyfinMediaActor) == 2

    db_session.delete(item)
    db_session.commit()

    assert _count(db_session, JellyfinMediaActor) == 0


def test_candidate_film_dir_is_unique(db_session):
    db_session.add_all(
        [
            ActressDeleteCandidate(film_dir="/媒体/甲/ABC-001", added_by="mark"),
            ActressDeleteCandidate(film_dir="/媒体/甲/ABC-001", added_by="daily"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_batch_films_and_files_cascade(db_session):
    _enable_foreign_keys(db_session)
    batch = ActressDeleteBatch(status="pending")
    film = ActressDeleteBatchFilm(film_dir="/媒体/甲/ABC-001", number="ABC-001", status="pending")
    film.files = [
        ActressDeleteBatchFile(group="remote_115", target="/云盘/ABC-001.mp4", status="pending"),
        ActressDeleteBatchFile(group="organized_dir", target="/媒体/甲/ABC-001", status="pending"),
    ]
    batch.films = [film]
    db_session.add(batch)
    db_session.commit()
    assert _count(db_session, ActressDeleteBatchFilm) == 1
    assert _count(db_session, ActressDeleteBatchFile) == 2
    # 默认值：计数为 0；重新从库里读出时文件按 id 排序
    db_session.expire_all()
    assert (batch.deleted_films, batch.failed_films, batch.skipped_films) == (0, 0, 0)
    assert [f.group for f in batch.films[0].files] == ["remote_115", "organized_dir"]

    db_session.delete(batch)
    db_session.commit()

    assert _count(db_session, ActressDeleteBatch) == 0
    assert _count(db_session, ActressDeleteBatchFilm) == 0
    assert _count(db_session, ActressDeleteBatchFile) == 0
