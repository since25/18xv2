"""
115 API 真实冒烟测试脚本。验证 list_files / get_file / create_folder / delete_node 链路。
默认 --dry-run=true，仅验证读取链路；传入 --no-dry-run 才执行写操作（需配置白名单目录）。
用法：python scripts/115_real_smoke.py [--no-dry-run] [--parent-cid CID]
"""
from __future__ import annotations

import argparse
import sys

from app.services.client_115.client import Client115Error, Real115Client


def main() -> int:
    parser = argparse.ArgumentParser(description="115 API 冒烟测试")
    parser.add_argument("--no-dry-run", action="store_true", help="执行写操作（create_folder + delete_node）")
    parser.add_argument("--parent-cid", default="0", help="写操作的父目录 CID（默认根目录 0）")
    args = parser.parse_args()
    dry_run = not args.no_dry_run

    client = Real115Client()

    # 确认 token 有效
    print("[1] 检查 token 有效性...")
    try:
        client.ensure_fresh_access_token()
        print("  token 已刷新或仍在有效期")
    except Client115Error as exc:
        print(f"[错误] token 无效：{exc}", file=sys.stderr)
        return 1

    # 读取根目录
    print("[2] 读取根目录 (cid=0)...")
    try:
        resp = client.list_files(cid="0", limit=10)
        items = resp.get("data", [])
        print(f"  根目录共 {resp.get('count', '?')} 项，本次获取前 {len(items)} 项：")
        for item in items[:5]:
            print(f"    [{item.get('fid')}] {item.get('fn')} ({'文件夹' if item.get('fc') == '0' else '文件'})")
    except Client115Error as exc:
        print(f"[错误] list_files 失败：{exc}", file=sys.stderr)
        return 1

    if dry_run:
        print("[冒烟完成] dry-run 模式，跳过写操作。")
        return 0

    # 写操作：创建测试目录再删除
    test_dir_name = "__smoke_test_delete_me__"
    print(f"[3] 在 cid={args.parent_cid} 下创建测试目录 {test_dir_name!r}...")
    try:
        result = client.create_folder(args.parent_cid, test_dir_name)
        created_id = result.payload["file_id"]
        print(f"  创建成功，fid={created_id}")
    except Client115Error as exc:
        print(f"[错误] create_folder 失败：{exc}", file=sys.stderr)
        return 1

    print(f"[4] 删除测试目录 fid={created_id}...")
    try:
        client.delete_node(created_id, dry_run=False)
        print("  删除成功")
    except Client115Error as exc:
        print(f"[警告] delete_node 失败（需手动清理 fid={created_id}）：{exc}", file=sys.stderr)
        return 1

    print("[冒烟完成] 读写链路验证通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
