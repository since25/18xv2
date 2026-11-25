import os
import re
import shutil
import datetime
import requests
from collections import deque
from urllib.parse import urlsplit, urlunsplit

# =========================
# 配置区
# =========================
scan_root = os.getenv("ORGANIZE_SCAN_ROOT", "/mnt/cache/docker1/SSD_cache/finish")
target_root = os.getenv("ORGANIZE_TARGET_ROOT", "/mnt/cache/docker1/SSD_cache/已整理")
#scan_root = "/mnt/disk2/2/SSD_cache/dn"
#target_root = "/mnt/disk2/2/SSD_cache/已整理"

keywords_api_url = "http://192.168.70.138:8010/api/keywords"
keywords_api_timeout = 15
page_limit = 200

# 登录配置从环境变量读取，避免把账号密码明文写进脚本。
keywords_api_username = os.getenv("KEYWORDS_API_USERNAME", "").strip()
keywords_api_password = os.getenv("KEYWORDS_API_PASSWORD", "").strip()

keyword_type = "whitelist"
keyword_status = "active"
include_aliases = True

dry_run = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "on")
fuzzy_match = True
max_depth = 6   # 只扫描 scan_root 下至多 6 级子目录
log_file = "/mnt/cache/docker1/python/scripts/local_organize_log.txt"

# 是否过滤过短关键词
min_keyword_len = 2

# 目标目录命名方式：
# True  => target_root/标准词/原文件夹
# False => target_root/原文件夹
group_by_canonical = True

# 当一个文件夹命中多个 whitelist 时：
# "first" = 取第一个
# "skip"  = 跳过不移动
multi_match_mode = "skip"

# 短别名被更长命中完整覆盖时，优先采用更具体的长命中。
# 例如“狗爹和小桃”同时命中“狗爹和小桃”和“小桃”时，只保留“狗爹和小桃”。
prefer_specific_match = True

# 收敛后命中 2~3 个独立 whitelist 时，整理到组合关键词目录。
# 超过 3 个仍按 multi_match_mode 处理，避免泛别名造成过度自动整理。
combine_multi_match_max = 3

# 兜底白名单：只有未命中其它普通白名单时才生效。
# 现在优先以“上游 API 的 merge_policy=fallback_only(低优先级)”为准；
# 此集合作为本地补充（兼容尚未在上游打标的词，如 露脸_泄密_反差_电报）。
fallback_only_canonical_names = {
    "露脸_泄密_反差_电报",
}

# 目标目录已存在时的处理策略（防“同名第二套文件夹永远整目录跳过、内容补不齐”）：
#   False => 旧行为：整体跳过并报 [ERROR]（目标路径已存在）
#   True  => 遍历源目录做合并：目标缺失的文件/子目录搬过去；
#            同名且 sha256 一致视为重复（删源侧副本，目标已有完整副本）；
#            同名但内容不同 / 目录文件互顶 => 保留两边，源侧改名“~merge冲突”再移入，绝不覆盖。
#            源目录合并完若已空则删除。
# 可用环境变量 MERGE_ON_CONFLICT 覆盖。
merge_on_conflict = os.getenv("MERGE_ON_CONFLICT", "true").strip().lower() in ("1", "true", "yes", "on")


# =========================
# 工具函数
# =========================
def build_login_url(api_url):
    parsed = urlsplit(api_url)
    path = parsed.path.rstrip("/")

    if path.endswith("/keywords"):
        login_path = path[: -len("/keywords")] + "/auth/login"
    else:
        login_path = "/api/auth/login"

    return urlunsplit((parsed.scheme, parsed.netloc, login_path, "", ""))


def create_authenticated_session():
    if not keywords_api_username or not keywords_api_password:
        raise RuntimeError(
            "未配置 KEYWORDS_API_USERNAME 或 KEYWORDS_API_PASSWORD，无法登录关键词 API。"
            "请先设置环境变量 KEYWORDS_API_USERNAME 和 KEYWORDS_API_PASSWORD。"
        )

    session = requests.Session()
    login_url = build_login_url(keywords_api_url)

    try:
        resp = session.post(
            login_url,
            json={
                "username": keywords_api_username,
                "password": keywords_api_password,
            },
            timeout=keywords_api_timeout,
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"登录关键词 API 失败: {e}")

    return session


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    return text


def load_whitelist_rules_from_api():
    """
    返回：
    [
      {
        "entry_id": 1,
        "canonical_name": "北京瑶瑶",
        "all_terms": ["北京瑶瑶", "瑶瑶", "北京yy"]
      },
      ...
    ]
    """
    rules = []
    skip = 0
    session = create_authenticated_session()

    while True:
        params = {
            "keyword_type": keyword_type,
            "status": keyword_status,
            "skip": skip,
            "limit": page_limit,
        }

        resp = session.get(
            keywords_api_url,
            params=params,
            timeout=keywords_api_timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        entries = data.get("entries", [])
        total = data.get("total", 0)

        for entry in entries:
            canonical_name = (entry.get("canonical_name") or "").strip()
            if not canonical_name or len(canonical_name) < min_keyword_len:
                continue

            term_set = {canonical_name}

            if include_aliases:
                for alias_item in entry.get("aliases", []):
                    alias = (alias_item.get("alias") or "").strip()
                    if alias and len(alias) >= min_keyword_len:
                        term_set.add(alias)

            rules.append({
                "entry_id": entry.get("id"),
                "canonical_name": canonical_name,
                "all_terms": sorted(term_set, key=lambda x: (-len(x), x)),  # 长词优先
                # 上游 merge_policy=fallback_only 即“低优先级/兜底词”（目前库里：抖音）；
                # 本地 fallback_only_canonical_names 作为补充。
                "is_fallback": (entry.get("merge_policy") == "fallback_only")
                or (canonical_name in fallback_only_canonical_names),
            })

        skip += len(entries)
        if skip >= total or not entries:
            break

    return rules


def match_folder_name(folder_name: str, rules: list, fuzzy: bool = True):
    """
    返回命中的规则列表，每项：
    {
      "entry_id": ...,
      "canonical_name": ...,
      "matched_terms": [...],
      "all_terms": [...]
    }
    """
    matched = []
    normalized_folder = normalize_text(folder_name)

    for rule in rules:
        hit_terms = []
        for term in rule["all_terms"]:
            normalized_term = normalize_text(term)
            if not normalized_term:
                continue

            if fuzzy:
                if normalized_term in normalized_folder:
                    hit_terms.append(term)
            else:
                if normalized_term == normalized_folder:
                    hit_terms.append(term)

        if hit_terms:
            matched.append({
                "entry_id": rule["entry_id"],
                "canonical_name": rule["canonical_name"],
                "matched_terms": hit_terms,
                "all_terms": rule["all_terms"],
                "is_fallback": rule.get("is_fallback", False),
            })

    if prefer_specific_match:
        matched = prune_covered_matches(matched)

    return matched


def prune_covered_matches(matched_rules: list):
    """
    多个规则命中时，删除“所有命中词都被其它更长命中词包含”的规则。

    只解决覆盖型歧义，不解决真正同时出现的多个独立关键词：
    - 狗爹和小桃 vs 小桃 => 保留狗爹和小桃
    - 狗爹和小桃 vs 小桃shixiaotaone => 两者都保留，继续按 multi_match_mode 处理
    """
    if len(matched_rules) <= 1:
        return matched_rules

    enriched = []
    for index, rule in enumerate(matched_rules):
        normalized_terms = sorted(
            {normalize_text(term) for term in rule.get("matched_terms", []) if normalize_text(term)},
            key=lambda item: (-len(item), item),
        )
        enriched.append((index, rule, normalized_terms))

    filtered = []
    for index, rule, normalized_terms in enriched:
        if not normalized_terms:
            filtered.append(rule)
            continue

        covered_by_longer = True
        for term in normalized_terms:
            term_is_covered = False
            for other_index, _other_rule, other_terms in enriched:
                if other_index == index:
                    continue
                if any(term != other_term and term in other_term for other_term in other_terms):
                    term_is_covered = True
                    break
            if not term_is_covered:
                covered_by_longer = False
                break

        if not covered_by_longer:
            filtered.append(rule)

    if not filtered:
        filtered = matched_rules

    return sorted(
        filtered,
        key=lambda rule: (
            -max((len(normalize_text(term)) for term in rule.get("matched_terms", [])), default=0),
            rule.get("canonical_name") or "",
        ),
    )


def split_matches_by_priority(matched_rules: list):
    """
    按 merge_policy 把命中拆成两类：
      normal   = 普通白名单（有具体指向，如 松果儿/瑶瑶）
      fallback = 低优先级/兜底词（上游 merge_policy=fallback_only，或本地配置的兜底词）

    语义：
      - 命中任何 normal => 只用 normal，兜底词完全不参与（不合并、不干扰），
        从而不会再把“抖音 松果儿”整成 已整理/抖音__松果儿
      - 未命中 normal、只命中 1 个兜底词 => 用它归类（如文件夹只有抖音时归 已整理/抖音）
      - 未命中 normal、命中多个兜底词 => 返回 fallback 列表，交由上层按歧义跳过
    """
    normal = [rule for rule in matched_rules if not rule.get("is_fallback")]
    fallback = [rule for rule in matched_rules if rule.get("is_fallback")]
    return normal, fallback


def iter_dirs_topdown(root_path: str, max_depth: int):
    """
    BFS 自上而下产出目录：yield (folder_name, folder_path, depth)。
    max_depth = 1: 只产出 scan_root 下一级子目录
    max_depth = 2: 产出下一级 + 下二级子目录

    保证浅层目录一定先于深层目录产出，便于外层面判定：
    当浅层命中并整体搬迁后，其内部子目录不再单独处理，
    从而保留原始目录结构、避免移动冲突，也不会丢掉内部零散文件（如 zip）。
    """
    if not os.path.isdir(root_path):
        raise ValueError(f"扫描根目录不存在: {root_path}")

    root_path = os.path.abspath(root_path)

    queue = deque()
    for dirname in sorted(os.listdir(root_path)):
        folder_path = os.path.join(root_path, dirname)
        if os.path.isdir(folder_path):
            queue.append((1, dirname, folder_path))

    while queue:
        depth, folder_name, folder_path = queue.popleft()
        if depth > max_depth:
            continue

        yield folder_name, folder_path, depth

        if depth < max_depth:
            # 该目录可能已被主循环整体搬走（其子树随之消失），此时跳过入队即可
            try:
                children = sorted(os.listdir(folder_path))
            except OSError:
                children = []
            for dirname in children:
                child_path = os.path.join(folder_path, dirname)
                if os.path.isdir(child_path):
                    queue.append((depth + 1, dirname, child_path))


def is_within_moved(folder_path: str, moved_roots: list) -> bool:
    """判断 folder_path 自身或其任一祖先目录是否已整体搬迁过。"""
    abs_path = os.path.abspath(folder_path)
    for root in moved_roots:
        abs_root = os.path.abspath(root)
        if abs_path == abs_root or abs_path.startswith(abs_root.rstrip(os.sep) + os.sep):
            return True
    return False


def build_target_path(folder_name: str, canonical_name: str):
    if group_by_canonical:
        return os.path.join(target_root, canonical_name, folder_name)
    return os.path.join(target_root, folder_name)


def build_combined_match(matched_rules: list):
    sorted_rules = sorted(matched_rules, key=lambda item: item["canonical_name"])
    canonical_name = "__".join(item["canonical_name"] for item in sorted_rules)
    matched_terms = []
    for item in sorted_rules:
        matched_terms.extend(item["matched_terms"])
    return {
        "entry_id": None,
        "canonical_name": canonical_name,
        "matched_terms": matched_terms,
        "all_terms": matched_terms,
    }


def ensure_parent_dir(path: str):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)


def file_identical(src_file: str, dst_file: str) -> bool:
    """逐块 sha256 比较两个文件内容是否完全一致。"""
    import hashlib

    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    try:
        return sha(src_file) == sha(dst_file)
    except OSError:
        return False


def unique_conflict_path(dst_path: str) -> str:
    """生成不冲突的保留路径：<原名>~merge冲突 / ~merge冲突2 / ~merge冲突3 ..."""
    if not os.path.exists(dst_path):
        return dst_path
    base, ext = os.path.splitext(dst_path)
    for i in range(1, 10000):
        if i == 1:
            alt = f"{base}~merge冲突{ext}"
        else:
            alt = f"{base}~merge冲突{i}{ext}"
        if not os.path.exists(alt):
            return alt
    raise FileExistsError(f"无法为冲突内容生成保留路径: {dst_path}")


def merge_dir_into(src_path: str, dst_path: str) -> dict:
    """
    目标目录已存在时，把 src 里目标缺失的内容递归合并进 dst。
      - 同名同内容文件（sha256 一致）=> 视为重复：删除源侧副本（目标已有完整副本）
      - 同名但内容不同 / 目录与文件同名互顶 => 保留两边：源侧改名“~merge冲突”后移入，绝不覆盖
      - 同名子目录 => 递归合并
    合并完成且源目录变空则删除源目录空壳。
    返回统计: {moved, dedup, conflict, removed_src}
    """
    stats = {"moved": 0, "dedup": 0, "conflict": 0, "removed_src": False}
    os.makedirs(dst_path, exist_ok=True)

    for name in sorted(os.listdir(src_path)):
        s_path = os.path.join(src_path, name)
        d_path = os.path.join(dst_path, name)

        if os.path.isdir(s_path):
            if os.path.isdir(d_path):
                sub = merge_dir_into(s_path, d_path)
                for k in ("moved", "dedup", "conflict"):
                    stats[k] += sub[k]
            elif os.path.exists(d_path):
                # 源目录 vs 目标文件同名：保留两边，源目录改名移入
                alt = unique_conflict_path(d_path)
                shutil.move(s_path, alt)
                stats["conflict"] += 1
            else:
                shutil.move(s_path, d_path)
                stats["moved"] += 1
            continue

        # 文件
        if not os.path.exists(d_path):
            shutil.move(s_path, d_path)
            stats["moved"] += 1
            continue
        if os.path.isdir(d_path):
            # 源文件 vs 目标目录同名：保留两边，源文件改名移入
            alt = unique_conflict_path(d_path)
            shutil.move(s_path, alt)
            stats["conflict"] += 1
            continue
        # 目标存在同名文件
        if os.path.getsize(s_path) == os.path.getsize(d_path) and file_identical(s_path, d_path):
            os.unlink(s_path)  # 目标已有逐字节一致的副本，删源侧重复
            stats["dedup"] += 1
        else:
            # 同名不同内容：保留两边，绝不静默覆盖
            alt = unique_conflict_path(d_path)
            shutil.move(s_path, alt)
            stats["conflict"] += 1

    # 源目录合并完若已空，删掉空壳
    try:
        if not os.listdir(src_path):
            os.rmdir(src_path)
            stats["removed_src"] = True
    except OSError:
        pass
    return stats


def safe_move_dir(src_path: str, dst_path: str):
    """
    移动目录到目标；目标不存在 => 整目录 shutil.move（旧行为）。
    目标已存在 => merge_on_conflict=True 时递归合并(见 merge_dir_into)并尽量清掉源空壳；
                  False 时抛 FileExistsError（旧行为：整体跳过）。
    返回统计 dict: {merge, moved, dedup, conflict, removed_src}
    """
    # 自移动保护：重算后 canonical 未变（目标即源目录本身）时视为已归位，跳过
    if os.path.abspath(src_path) == os.path.abspath(dst_path):
        return {"merge": False, "moved": 0, "dedup": 0, "conflict": 0,
                "removed_src": False, "already_placed": True}
    if os.path.exists(dst_path):
        if merge_on_conflict:
            stats = merge_dir_into(src_path, dst_path)
            stats["merge"] = True
            return stats
        raise FileExistsError(f"目标路径已存在: {dst_path}")
    ensure_parent_dir(dst_path)
    shutil.move(src_path, dst_path)
    return {"merge": False, "moved": 1, "dedup": 0, "conflict": 0, "removed_src": True}


def write_log(lines: list[str]):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== LOCAL ORGANIZE @ {now} ===\n")
        for line in lines:
            f.write(line + "\n")


# =========================
# 主流程
# =========================
def main():
    rules = load_whitelist_rules_from_api()
    print(f"[INFO] 已加载 whitelist 规则数: {len(rules)}")

    if not rules:
        print("[ERROR] 没有加载到任何 whitelist 规则")
        return

    results = []
    moved_count = 0
    skip_count = 0
    ambiguous_count = 0
    moved_roots = []  # 已整体搬迁的目录，其内部子目录不再单独处理

    for folder_name, folder_path, _depth in iter_dirs_topdown(scan_root, max_depth):
        # 祖先已整体搬迁：内部目录随父级一并搬走，跳过，避免重复/冲突/丢文件
        if is_within_moved(folder_path, moved_roots):
            continue

        matched_rules = match_folder_name(folder_name, rules, fuzzy=fuzzy_match)

        normal_matches, fallback_matches = split_matches_by_priority(matched_rules)
        if normal_matches:
            matched_rules = normal_matches
        elif len(fallback_matches) > 1:
            # 仅命中多个低优先级/兜底词且无具体词。非抖音兜底词优先于抖音：
            # 只有一个非抖音兜底词时，剔除抖音后按该词归类（如 抖音+露脸 => 露脸_泄密_反差_电报）
            non_douyin = [r for r in fallback_matches if r["canonical_name"] != "抖音"]
            if len(non_douyin) == 1:
                matched_rules = non_douyin
            else:
                # 仍为多个非抖音兜底词：不合并、不归类，跳过待人工
                reasons = []
                for item in fallback_matches:
                    reasons.append(
                        f'{item["canonical_name"]} ({", ".join(item["matched_terms"])})'
                    )
                print(f"[AMBIGUOUS-LOW] {folder_path}")
                print(f"            仅命中多个低优先级词: {' | '.join(reasons)}")
                results.append(f"[AMBIGUOUS-LOW] {folder_path} -> {' | '.join(reasons)}")
                ambiguous_count += 1
                continue
        else:
            matched_rules = fallback_matches

        if not matched_rules:
            results.append(f"[SKIP] 未命中: {folder_path}")
            skip_count += 1
            continue

        if 1 < len(matched_rules) <= combine_multi_match_max:
            chosen = build_combined_match(matched_rules)
        elif len(matched_rules) > 1 and multi_match_mode == "skip":
            reasons = []
            for item in matched_rules:
                reasons.append(
                    f'{item["canonical_name"]} ({", ".join(item["matched_terms"])})'
                )
            print(f"[AMBIGUOUS] {folder_path}")
            print(f"            命中多个 whitelist: {' | '.join(reasons)}")
            results.append(f"[AMBIGUOUS] {folder_path} -> {' | '.join(reasons)}")
            ambiguous_count += 1
            continue
        else:
            chosen = matched_rules[0]
        canonical_name = chosen["canonical_name"]
        matched_terms = chosen["matched_terms"]
        dst_path = build_target_path(folder_name, canonical_name)

        if dry_run:
            print(f"[DRY-RUN] {folder_path} -> {dst_path}")
            print(f"          命中标准词: {canonical_name}")
            print(f"          命中词项: {', '.join(matched_terms)}")
            results.append(
                f"[DRY-RUN] MOVE: {folder_path} -> {dst_path} | canonical={canonical_name} | matched={','.join(matched_terms)}"
            )
            moved_count += 1
            moved_roots.append(folder_path)
        else:
            try:
                stats = safe_move_dir(folder_path, dst_path)
                if stats.get("merge"):
                    print(f"[MERGED] {folder_path} -> {dst_path}")
                    print(f"          合并: 新移入 {stats['moved']} 项 | 重复去重 {stats['dedup']} 项 | 同名冲突保留 {stats['conflict']} 项")
                    if not stats.get("removed_src"):
                        print(f"          [WARN] 源目录未清空(仍有内容), 保留待下轮处理: {folder_path}")
                    results.append(
                        f"[MERGED] {folder_path} -> {dst_path} | moved={stats['moved']} dedup={stats['dedup']} conflict={stats['conflict']} | canonical={canonical_name} | matched={','.join(matched_terms)}"
                    )
                elif stats.get("already_placed"):
                    # 自移动保护: 目标即源目录(重算 canonical 未变), 原地保留——未实际移动, 不计入候选
                    print(f"[ALREADY-PLACED] {folder_path} -> {dst_path}")
                    print(f"        命中标准词: {canonical_name}")
                    print(f"        命中词项: {', '.join(matched_terms)}")
                    results.append(
                        f"[ALREADY-PLACED] {folder_path} -> {dst_path} | canonical={canonical_name} | matched={','.join(matched_terms)}"
                    )
                else:
                    print(f"[MOVED] {folder_path} -> {dst_path}")
                    print(f"        命中标准词: {canonical_name}")
                    print(f"        命中词项: {', '.join(matched_terms)}")
                    results.append(
                        f"[MOVED] {folder_path} -> {dst_path} | canonical={canonical_name} | matched={','.join(matched_terms)}"
                    )
                    moved_count += 1
                    moved_roots.append(folder_path)
            except Exception as e:
                print(f"[ERROR] 移动失败: {folder_path} -> {dst_path} | {e}")
                results.append(f"[ERROR] {folder_path} -> {dst_path} | {e}")

    write_log(results)

    print("\n[SUMMARY]")
    print(f"move candidates: {moved_count}")
    print(f"ambiguous: {ambiguous_count}")
    print(f"skip: {skip_count}")
    print(f"log: {log_file}")


if __name__ == "__main__":
    main()
