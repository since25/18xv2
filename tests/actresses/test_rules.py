from __future__ import annotations

from app.models.actresses import Actress, ActressAlias, ActressKeptFilm
from app.models.keywords import KeywordAlias, KeywordEntry
from app.services.actresses.films import Film
from app.services.actresses.names import build_protected_terms, normalize_actress_name
from app.services.actresses.rules import RuleContext, Verdict, skip_reason

_ROOT = "/媒体/strm"


def _film(number: str, actors: tuple[str, ...], *, actor_dir: str = "甲") -> Film:
    """直接构造一部片（规则只看演员和番号目录，不读库里的扫描条目）。"""
    return Film(
        film_dir=f"{_ROOT}/{actor_dir}/{number}",
        number=number,
        actor_dir=f"{_ROOT}/{actor_dir}",
        strm_paths=(f"{_ROOT}/{actor_dir}/{number}/{number}.strm",),
        media_item_ids=(1,),
        jellyfin_item_ids=(),
        actor_names=actors,
    )


def _add_actress(db_session, name: str, *, status: str = "none", aliases: tuple[str, ...] = ()) -> Actress:
    actress = Actress(canonical_name=name, canonical_name_normalized=normalize_actress_name(name), status=status)
    actress.aliases = [ActressAlias(alias=alias, alias_normalized=normalize_actress_name(alias)) for alias in aliases]
    db_session.add(actress)
    db_session.commit()
    return actress


def _add_keyword(
    db_session, name: str, keyword_type: str, *, status: str = "active", aliases: tuple[str, ...] = ()
) -> KeywordEntry:
    entry = KeywordEntry(
        canonical_name=name,
        canonical_name_normalized=normalize_actress_name(name),
        keyword_type=keyword_type,
        status=status,
    )
    entry.aliases = [KeywordAlias(alias=alias, alias_normalized=normalize_actress_name(alias)) for alias in aliases]
    db_session.add(entry)
    db_session.commit()
    return entry


def test_black_only_film_is_deletable(db_session):
    _add_actress(db_session, "甲", status="blacklist", aliases=("甲甲",))

    context = RuleContext.load(db_session)

    assert context.verdict(_film("ABC-001", ("甲",))) == Verdict(
        deletable=True, black_names=("甲",), protected_by=(), kept=False
    )
    # 别名、空格写法也能对上档案
    assert context.verdict(_film("ABC-002", ("甲 甲",))).black_names == ("甲 甲",)


def test_film_with_whitelisted_costar_is_protected(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    _add_actress(db_session, "乙", status="whitelist")

    verdict = RuleContext.load(db_session).verdict(_film("ABC-001", ("甲", "乙")))

    assert verdict.deletable is False
    assert verdict.black_names == ("甲",)
    assert verdict.protected_by == ("乙",)
    assert skip_reason(verdict) == "已受白名单保护：乙"


def test_keyword_whitelist_costar_protects(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    # 乙没有档案，只在启用中的普通关键词白名单里
    _add_keyword(db_session, "乙", "whitelist")
    # 停用的白名单和其他类型的关键词不算保护
    _add_keyword(db_session, "丙", "whitelist", status="disabled")
    _add_keyword(db_session, "丁", "blacklist")
    context = RuleContext.load(db_session)

    protected = context.verdict(_film("ABC-001", ("甲", "乙")))
    assert protected.deletable is False
    assert protected.protected_by == ("乙",)

    assert context.verdict(_film("ABC-002", ("甲", "丙", "丁"))).deletable is True


def test_emby_whitelist_alias_protects(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    _add_keyword(db_session, "丙", "emby_whitelist", aliases=("乙　Ａ",))

    assert build_protected_terms(db_session) == {"丙", "乙A"}

    verdict = RuleContext.load(db_session).verdict(_film("ABC-001", ("甲", "乙 A")))

    assert verdict.deletable is False
    assert verdict.protected_by == ("乙 A",)


def test_keyword_whitelist_protects_archive_alias_in_nfo(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    # 乙在档案里未标、有别名「乙乙」；关键词白名单只写了规范名「乙」
    _add_actress(db_session, "乙", aliases=("乙乙",))
    _add_keyword(db_session, "乙", "whitelist")

    verdict = RuleContext.load(db_session).verdict(_film("ABC-001", ("甲", "乙 乙")))

    assert verdict.deletable is False
    # 显示 NFO 原名
    assert verdict.protected_by == ("乙 乙",)


def test_keyword_whitelist_on_archive_alias_protects_canonical_in_nfo(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    # 反过来：关键词白名单只写了别名「乙乙」，NFO 写的是规范名「乙」
    _add_actress(db_session, "乙", aliases=("乙乙",))
    _add_keyword(db_session, "乙乙", "emby_whitelist")
    context = RuleContext.load(db_session)

    verdict = context.verdict(_film("ABC-001", ("甲", "乙")))

    assert verdict.deletable is False
    assert verdict.protected_by == ("乙",)
    # 不相干的未标演员不受影响
    assert context.verdict(_film("ABC-002", ("甲", "丙"))).deletable is True


def test_unmarked_costar_does_not_protect(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    _add_actress(db_session, "乙")

    # 乙有档案但未标，丙连档案都没有：都不算保护
    verdict = RuleContext.load(db_session).verdict(_film("ABC-001", ("乙", "甲", "丙")))

    assert verdict == Verdict(deletable=True, black_names=("甲",), protected_by=(), kept=False)


def test_kept_film_is_not_deletable(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    film = _film("ABC-001", ("甲",))
    db_session.add(ActressKeptFilm(film_dir=film.film_dir))
    db_session.commit()
    context = RuleContext.load(db_session)

    verdict = context.verdict(film)

    assert verdict == Verdict(deletable=False, black_names=("甲",), protected_by=(), kept=True)
    assert skip_reason(verdict) == "已标为保留"
    # 保留只针对这一个番号目录
    assert context.verdict(_film("ABC-002", ("甲",))).deletable is True


def test_film_without_actors_is_never_deletable(db_session):
    _add_actress(db_session, "甲", status="blacklist")
    _add_actress(db_session, "乙")
    context = RuleContext.load(db_session)

    # NFO 缺失或解析失败的片子没有演员
    no_actors = context.verdict(_film("ABC-001", ()))
    assert no_actors == Verdict(deletable=False, black_names=(), protected_by=(), kept=False)
    assert skip_reason(no_actors) == "没有黑名单演员"

    assert skip_reason(context.verdict(_film("ABC-002", ("乙",)))) == "没有黑名单演员"
