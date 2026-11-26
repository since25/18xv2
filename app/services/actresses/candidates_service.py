"""待删清单：所有当前应删的片子，持续随状态变化、每日任务增删。

清单里的片子默认勾选；不勾选的留在清单里下次再看；「保留」的移出清单并记入保留名单，
以后重新评估都不会再提出它，撤销保留后重新评估放回来。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actresses import ActressDeleteCandidate, ActressKeptFilm
from app.services.actresses.archive_service import require_strm_roots
from app.services.actresses.films import load_films, read_nfo_title
from app.services.actresses.rules import RuleContext


@dataclass
class CandidateView:
    """清单页上的一行。"""

    film_dir: str
    number: str
    title: str | None
    selected: bool
    # mark（改状态时加入）/ daily（每日任务加入）
    added_by: str
    added_at: datetime
    # 因为谁：演员里黑名单的人
    black_names: list[str]
    # 同片其他演员：（名字, 档案状态），没有档案的算 none
    other_actors: list[tuple[str, str]]
    remote_state: str
    remote_note: str | None


def _normalize_dirs(film_dirs: list[str]) -> list[str]:
    """去掉末尾斜杠等写法差异并去重，与 load_films 对番号目录的处理一致。"""
    return list(dict.fromkeys(os.path.normpath(film_dir) for film_dir in film_dirs if film_dir))


class CandidateService:
    """待删清单的重算与勾选、保留操作，每个写操作自己 commit。"""

    def reconcile(self, db: Session, *, strm_roots: list[str], added_by: str) -> tuple[int, int]:
        """按删片规则重算清单，返回（新加入部数, 移出部数）。

        新应删的片子加入并默认勾选；已在清单里的保持原来的勾选状态和加入方式；不再应删的移出。
        根目录没配置时抛 ActressError，不改任何数据。
        """
        require_strm_roots(strm_roots, "重算待删清单")
        context = RuleContext.load(db)
        films = load_films(db, strm_roots=strm_roots)
        deletable = {film.film_dir for film in films if context.verdict(film).deletable}
        rows = {row.film_dir: row for row in db.scalars(select(ActressDeleteCandidate))}

        removed = 0
        for film_dir, row in rows.items():
            if film_dir not in deletable:
                db.delete(row)
                removed += 1
        added = 0
        for film_dir in sorted(deletable.difference(rows)):
            db.add(ActressDeleteCandidate(film_dir=film_dir, selected=True, added_by=added_by))
            added += 1
        db.commit()
        return added, removed

    def list(self, db: Session, *, strm_roots: list[str]) -> list[CandidateView]:
        """清单全部片子，按加入时间倒序、再按番号。

        已不在扫描结果里的片子（等下次重算移出）只显示番号目录，没有演员和标题。
        """
        rows = db.scalars(select(ActressDeleteCandidate)).all()
        films = {
            film.film_dir: film
            for film in load_films(db, strm_roots=strm_roots, film_dirs={row.film_dir for row in rows})
        }
        context = RuleContext.load(db)

        views: list[CandidateView] = []
        for row in rows:
            film = films.get(row.film_dir)
            black_names: list[str] = []
            other_actors: list[tuple[str, str]] = []
            actor_names = film.actor_names if film else ()
            for raw_name in actor_names:
                status = context.actor_status(raw_name)
                if status == "blacklist":
                    black_names.append(raw_name)
                else:
                    other_actors.append((raw_name, status))
            views.append(
                CandidateView(
                    film_dir=row.film_dir,
                    number=os.path.basename(row.film_dir),
                    title=read_nfo_title(film) if film else None,
                    selected=row.selected,
                    added_by=row.added_by,
                    added_at=row.added_at,
                    black_names=black_names,
                    other_actors=other_actors,
                    remote_state=row.remote_state,
                    remote_note=row.remote_note,
                )
            )
        # 两次稳定排序：先按番号，再按加入时间倒序
        views.sort(key=lambda view: view.number)
        views.sort(key=lambda view: view.added_at, reverse=True)
        return views

    def set_selected(self, db: Session, film_dirs: list[str], selected: bool) -> int:
        """改清单里这些片子的勾选状态，返回清单里命中的部数。"""
        dirs = _normalize_dirs(film_dirs)
        rows = db.scalars(select(ActressDeleteCandidate).where(ActressDeleteCandidate.film_dir.in_(dirs))).all()
        for row in rows:
            row.selected = selected
        db.commit()
        return len(rows)

    def keep(self, db: Session, film_dirs: list[str]) -> int:
        """把这些片子记入保留名单并移出清单，返回新记入保留名单的部数。"""
        dirs = _normalize_dirs(film_dirs)
        already = set(db.scalars(select(ActressKeptFilm.film_dir).where(ActressKeptFilm.film_dir.in_(dirs))))
        new_dirs = [film_dir for film_dir in dirs if film_dir not in already]
        db.add_all(ActressKeptFilm(film_dir=film_dir) for film_dir in new_dirs)
        for row in db.scalars(select(ActressDeleteCandidate).where(ActressDeleteCandidate.film_dir.in_(dirs))).all():
            db.delete(row)
        db.commit()
        return len(new_dirs)

    def unkeep(self, db: Session, film_dirs: list[str], *, strm_roots: list[str]) -> int:
        """撤销保留，再重算清单让仍应删的片子回来，返回撤销的部数。"""
        # 先检查：否则保留记录已删掉、重算才报错
        require_strm_roots(strm_roots, "重算待删清单")
        dirs = _normalize_dirs(film_dirs)
        rows = db.scalars(select(ActressKeptFilm).where(ActressKeptFilm.film_dir.in_(dirs))).all()
        for row in rows:
            db.delete(row)
        db.commit()
        self.reconcile(db, strm_roots=strm_roots, added_by="mark")
        return len(rows)
