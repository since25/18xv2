import os
import csv
import shutil
import datetime
import requests
from urllib.parse import urlsplit, urlunsplit

# === 配置区 ===
csv_targets_file = os.getenv('TARGET_DIRS_CSV', '/mnt/cache/docker1/python/scripts/delsomethin/target_dirs.csv').strip()

# 关键词 API
keywords_api_url = 'http://192.168.70.138:8010/api/keywords'
keywords_api_timeout = 15
keyword_type = 'blacklist'
keyword_status = 'active'
page_limit = 200

# 登录配置从环境变量读取，避免把账号密码明文写进脚本。
keywords_api_username = os.getenv('KEYWORDS_API_USERNAME', '').strip()
keywords_api_password = os.getenv('KEYWORDS_API_PASSWORD', '').strip()

# 是否把 aliases 也加入匹配词
# 先建议 False，降低误删风险
include_aliases = True  # 2026-09 修 Maniacccccc 漏删: canonical=The_Maniacccccc, 目录名只含别名 Maniacccccc

# 安全开关：第一次建议先 True，确认日志无误后再改 False
dry_run = os.getenv('DRY_RUN', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

fuzzy_match = True
suffix_filter = []  # 例如 ['.mp4', '.jpg']，空列表表示全部匹配
enable_backup = False
backup_dir = '/mnt/cache/docker1/python/scripts/delsomethin/backup'
log_file = '/mnt/cache/docker1/python/scripts/delsomethin/delete_log.txt'
max_file_size_mb = 0  # 0 表示不限制大小

# 过滤过短关键词，避免误删
min_keyword_len = 2


# === 函数区 ===
def build_login_url(api_url):
    parsed = urlsplit(api_url)
    path = parsed.path.rstrip('/')

    if path.endswith('/keywords'):
        login_path = path[: -len('/keywords')] + '/auth/login'
    else:
        login_path = '/api/auth/login'

    return urlunsplit((parsed.scheme, parsed.netloc, login_path, '', ''))


def create_authenticated_session():
    if not keywords_api_username or not keywords_api_password:
        raise RuntimeError(
            '未配置 KEYWORDS_API_USERNAME 或 KEYWORDS_API_PASSWORD，无法登录关键词 API。'
            '请先设置环境变量 KEYWORDS_API_USERNAME 和 KEYWORDS_API_PASSWORD。'
        )

    session = requests.Session()
    login_url = build_login_url(keywords_api_url)

    try:
        resp = session.post(
            login_url,
            json={
                'username': keywords_api_username,
                'password': keywords_api_password,
            },
            timeout=keywords_api_timeout,
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f'登录关键词 API 失败: {e}')

    return session


def load_keywords_from_api():
    keywords = set()
    skip = 0
    session = create_authenticated_session()

    while True:
        params = {
            'keyword_type': keyword_type,
            'status': keyword_status,
            'skip': skip,
            'limit': page_limit,
        }

        try:
            resp = session.get(
                keywords_api_url,
                params=params,
                timeout=keywords_api_timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"读取关键词 API 失败: {e}")

        entries = data.get('entries', [])
        total = data.get('total', 0)

        for entry in entries:
            canonical_name = (entry.get('canonical_name') or '').strip()
            if canonical_name and len(canonical_name) >= min_keyword_len:
                keywords.add(canonical_name)

            if include_aliases:
                for alias_item in entry.get('aliases', []):
                    alias_name = (alias_item.get('alias') or '').strip()
                    if alias_name and len(alias_name) >= min_keyword_len:
                        keywords.add(alias_name)

        skip += len(entries)
        if skip >= total or not entries:
            break

    return keywords


def load_target_dirs(csv_path):
    paths = []
    with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
        for row in csv.reader(csvfile):
            for col in row:
                path = col.strip()
                if path.startswith('/') and os.path.isdir(path):
                    paths.append(path)
    return paths


def match_name(name, keywords, fuzzy=False):
    if fuzzy:
        return any(kw in name for kw in keywords)
    return name in keywords


def has_allowed_suffix(file_name, suffix_list):
    return True if not suffix_list else any(file_name.lower().endswith(s.lower()) for s in suffix_list)


def is_under_max_size(file_path, max_mb):
    if max_mb <= 0:
        return True
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    return size_mb <= max_mb


def backup_file(src_path, backup_dir):
    rel_path = os.path.relpath(src_path, start='/')
    dest_path = os.path.join(backup_dir, rel_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(src_path, dest_path)


def delete_matching_items(target_dir, keywords, dry_run=False, fuzzy=False, suffix_list=None):
    deleted = []

    # 删除匹配目录
    for root, dirs, files in os.walk(target_dir, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            if match_name(d, keywords, fuzzy):
                if dry_run:
                    print(f"[DRY-RUN] 将删除目录：{dir_path}")
                    deleted.append(f"[DRY-RUN] DIR: {dir_path}")
                else:
                    try:
                        shutil.rmtree(dir_path)
                        print(f"[DELETED] 已删除目录：{dir_path}")
                        deleted.append(f"DIR: {dir_path}")
                    except Exception as e:
                        print(f"[ERROR] 无法删除目录 {dir_path}：{e}")

    # 删除匹配文件
    for root, _, files in os.walk(target_dir):
        for file in files:
            if not match_name(file, keywords, fuzzy):
                continue
            if not has_allowed_suffix(file, suffix_list):
                continue

            file_path = os.path.join(root, file)
            if not is_under_max_size(file_path, max_file_size_mb):
                print(f"[SKIPPED] 文件过大：{file_path}")
                continue

            if dry_run:
                print(f"[DRY-RUN] 将删除文件：{file_path}")
                deleted.append(f"[DRY-RUN] FILE: {file_path}")
            else:
                try:
                    if enable_backup:
                        backup_file(file_path, backup_dir)
                        print(f"[BACKUP] 已备份：{file_path}")
                    os.remove(file_path)
                    print(f"[DELETED] 已删除文件：{file_path}")
                    deleted.append(f"FILE: {file_path}")
                except Exception as e:
                    print(f"[ERROR] 无法删除文件 {file_path}：{e}")

    return deleted


def remove_empty_folders(root_folder):
    for dirpath, dirnames, filenames in os.walk(root_folder, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
                print(f"[EMPTY] 已删除空文件夹: {dirpath}")
            except Exception as e:
                print(f"[ERROR] 删除失败 {dirpath}: {e}")


def write_log(deleted_files, dry_run=False):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n=== {'DRY-RUN' if dry_run else 'DELETE'} @ {now} ===\n")
        for file in deleted_files:
            f.write(file + '\n')
        f.write(f"共计：{len(deleted_files)} 项\n")


# === 主程序 ===
if __name__ == "__main__":
    try:
        keywords = load_keywords_from_api()
    except Exception as e:
        print(f"[错误] 加载关键词失败：{e}")
        exit(1)

    target_dirs = load_target_dirs(csv_targets_file)

    print(f"[INFO] 加载关键词数量：{len(keywords)}")
    print(f"[INFO] 加载目标路径数量：{len(target_dirs)}")

    if not keywords:
        print("[错误] 未从 API 读取到任何 blacklist 关键词。")
        exit(1)

    if not target_dirs:
        print("[错误] 未找到有效的目标路径，检查 target_dirs.csv 文件。")
        exit(1)

    all_deleted = []

    for target_dir in target_dirs:
        print(f"\n[处理] {target_dir}")
        deleted = delete_matching_items(
            target_dir,
            keywords,
            dry_run=dry_run,
            fuzzy=fuzzy_match,
            suffix_list=suffix_filter
        )
        if not dry_run:
            remove_empty_folders(target_dir)
        all_deleted.extend(deleted)

    write_log(all_deleted, dry_run)
    print(f"\n[完成] {'未实际删除' if dry_run else f'已删除 {len(all_deleted)} 项'}，日志保存于 {log_file}")
