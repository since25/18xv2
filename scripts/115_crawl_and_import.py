"""
从 115 爬取指定目录，生成目录树文本并上传到本地 /imports/tree API。
用法：python scripts/115_crawl_and_import.py [--cid CID] [--api-url URL] [--max-depth N]
默认 CID=3345325155417706503（待整理），最大深度 3。
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import requests

from app.services.client_115.client import Client115Error, Real115Client

# 树格式常量
EM_DASH4 = "\u2014" * 4  # |———— 根节点


def list_all(client: Real115Client, cid: str, limit: int = 100) -> list[dict]:
    """分页获取目录下所有子项。"""
    items: list[dict] = []
    offset = 0
    while True:
        resp = client.list_files(cid=cid, limit=limit, offset=offset)
        batch = resp.get("data") or []
        items.extend(batch)
        if len(items) >= int(resp.get("count", 0)) or not batch:
            break
        offset += len(batch)
        time.sleep(0.3)
    return items


def build_tree_lines(
    client: Real115Client,
    cid: str,
    root_name: str,
    max_depth: int,
) -> list[str]:
    """递归构建目录树行列表。"""
    lines: list[str] = [f"|{EM_DASH4} {root_name}"]

    def walk(parent_cid: str, depth: int) -> None:
        if depth > max_depth:
            return
        prefix = "|" + " |" * depth
        try:
            items = list_all(client, parent_cid)
        except Client115Error as exc:
            print(f"  [警告] 列举 cid={parent_cid} 失败：{exc}", file=sys.stderr)
            return
        for item in items:
            name = item.get("fn") or item.get("file_name") or "未命名"
            is_folder = str(item.get("fc", "1")) == "0"
            lines.append(f"{prefix}- {name}")
            if is_folder:
                child_cid = str(item.get("fid") or item.get("file_id"))
                walk(child_cid, depth + 1)

    walk(cid, 0)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="115 目录树爬取并导入")
    parser.add_argument("--cid", default="3345325155417706503", help="起始目录 CID（默认：待整理）")
    parser.add_argument("--root-name", default=None, help="根节点显示名（默认从 115 自动获取）")
    parser.add_argument("--max-depth", type=int, default=3, help="最大爬取深度（默认 3）")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="本地 API 地址")
    parser.add_argument("--dry-run", action="store_true", help="只生成树文本，不上传")
    args = parser.parse_args()

    client = Real115Client()

    print("[1] 检查 token...")
    try:
        client.ensure_fresh_access_token()
        print("  token 正常")
    except Client115Error as exc:
        print(f"[错误] token 无效：{exc}", file=sys.stderr)
        return 1

    # 获取根节点名称
    root_name = args.root_name
    if not root_name:
        try:
            info = client.get_file(file_id=args.cid)
            root_name = info.get("data", {}).get("file_name") or f"cid_{args.cid}"
        except Exception:
            root_name = f"cid_{args.cid}"

    print(f"[2] 爬取目录：{root_name} (cid={args.cid})，最大深度 {args.max_depth}...")
    lines = build_tree_lines(client, args.cid, root_name, args.max_depth)
    tree_text = "\n".join(lines) + "\n"
    print(f"  共生成 {len(lines)} 行")

    if args.dry_run:
        print("\n--- 树内容预览（前 30 行）---")
        print("\n".join(lines[:30]))
        return 0

    # 上传
    filename = f"{root_name}_crawl.txt"
    print(f"[3] 上传到 {args.api_url}/imports/tree ...")
    try:
        resp = requests.post(
            f"{args.api_url}/imports/tree",
            files={"file": (filename, io.BytesIO(tree_text.encode("utf-8")), "text/plain")},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        import_id = data.get("id") or data.get("import_id")
        node_count = data.get("node_count", "?")
        print(f"  [成功] import_id={import_id}，节点数={node_count}")
        print(f"\n下一步：生成整理计划")
        print(f"  curl -s -X POST {args.api_url}/plans/generate \\")
        print(f"    -H 'Content-Type: application/json' \\")
        print(f"    -d '{{\"import_id\": {import_id}, \"dry_run\": true}}'")
        return 0
    except Exception as exc:
        print(f"[错误] 上传失败：{exc}", file=sys.stderr)
        if hasattr(exc, "response") and exc.response is not None:
            print(exc.response.text[:500], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
