"""DEL_SOMETHING 子进程入口：按 Unraid 原 bash 外壳的顺序编排。

1. 运行 delete_files.py（按 18x 黑名单删除）；失败就以同一退出码结束（原外壳 set -e）。
2. 逐条运行整理脚本（按 18x 白名单归类）；扫描目录不存在的跳过，失败就结束。
3. 按配置修正整理目标目录的权限：数字 99:100（Unraid 的 nobody:users；容器里 nobody 是 65534）。

与原外壳的不同：演练时不修正权限（原外壳演练也会 chown）；文件锁由 18x 的互斥代替。
输出的标签行（[SKIP] / [INFO] / [WARN]）与原外壳一致，供阶段 6 的解析器解析。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


TARGET_DIRS_FILE = "target_dirs.csv"
BLACKLIST_FILE = "keywords_blacklist.json"
WHITELIST_FILE = "keywords_whitelist.json"
DELETE_SCRIPT = "delete_files.py"
ORGANIZE_SCRIPT = "local_organize_from_whitelist.py"
OWNER = "99:100"


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _run_python(script: Path, env: dict[str, str]) -> int:
    sys.stdout.flush()
    return subprocess.run([sys.executable, "-u", str(script)], env=env).returncode


def _fix_permissions(root: str) -> bool:
    if not os.path.isdir(root):
        print(f"[WARN] Organized root does not exist, skip permission fix: {root}", flush=True)
        return True
    print(f"[INFO] Fixing permissions for: {root}", flush=True)
    for argv in (
        ["chown", "-R", OWNER, root],
        ["find", root, "-type", "d", "-exec", "chmod", "775", "{}", "+"],
        ["find", root, "-type", "f", "-exec", "chmod", "664", "{}", "+"],
    ):
        if subprocess.run(argv).returncode != 0:
            print(f"[ERROR] 修正权限失败: {root}", flush=True)
            return False
    return True


def run(config: dict) -> int:
    os.umask(0o077)  # 与原外壳一致；新建目录的权限由最后的修正权限统一设置
    dry_run = bool(config["dry_run"])
    run_dir = Path(config["run_dir"])
    scripts_dir = Path(config["scripts_dir"])

    base_env = dict(os.environ)
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env["DRY_RUN"] = _flag(dry_run)
    # 关键词由 18x 导出成文件，不再登录接口
    base_env.pop("KEYWORDS_API_USERNAME", None)
    base_env.pop("KEYWORDS_API_PASSWORD", None)

    delete_env = dict(base_env)
    delete_env["TARGET_DIRS_CSV"] = str(run_dir / TARGET_DIRS_FILE)
    delete_env["KEYWORDS_FILE"] = str(run_dir / BLACKLIST_FILE)
    delete_env["DELETE_LOG_FILE"] = str(run_dir / "delete_log.txt")
    code = _run_python(scripts_dir / DELETE_SCRIPT, delete_env)
    if code != 0:
        return code

    organized_roots: list[str] = []
    for job in config["organize_jobs"]:
        scan_root = job["scan_root"]
        target_root = job["target_root"]
        if not os.path.isdir(scan_root):
            print(f"[SKIP] 扫描根不存在, 跳过: {scan_root}", flush=True)
            continue
        print(f"[INFO] Organizing: {scan_root} -> {target_root}", flush=True)
        organize_env = dict(base_env)
        organize_env["ORGANIZE_SCAN_ROOT"] = scan_root
        organize_env["ORGANIZE_TARGET_ROOT"] = target_root
        organize_env["MERGE_ON_CONFLICT"] = _flag(bool(config["merge_on_conflict"]))
        organize_env["KEYWORDS_FILE"] = str(run_dir / WHITELIST_FILE)
        organize_env["ORGANIZE_LOG_FILE"] = str(run_dir / "organize_log.txt")
        code = _run_python(scripts_dir / ORGANIZE_SCRIPT, organize_env)
        if code != 0:
            return code
        if target_root not in organized_roots:
            organized_roots.append(target_root)

    if not config["fix_permissions"]:
        return 0
    if dry_run:
        print("[INFO] 演练模式，跳过修正权限", flush=True)
        return 0
    ok = True
    for root in organized_roots:
        ok = _fix_permissions(root) and ok
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEL_SOMETHING 编排")
    parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.input).read_text(encoding="utf-8"))
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
