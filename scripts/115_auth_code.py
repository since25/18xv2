"""
授权码换 token 脚本。将从 115 获取的授权码换取 access token 并持久化。
用法：python scripts/115_auth_code.py --code <授权码>
适用场景：P0-1 启动授权失败时的人工兜底。
"""
from __future__ import annotations

import argparse
import sys

from app.services.client_115.client import Client115Error, Real115Client


def main() -> int:
    parser = argparse.ArgumentParser(description="115 授权码换 token")
    parser.add_argument("--code", required=True, help="从 115 授权页面获取的 code 参数")
    parser.add_argument("--redirect-uri", default=None, help="覆盖 .env 中的 APP_REDIRECT_URI（可选）")
    args = parser.parse_args()

    client = Real115Client()
    print(f"[换码] 正在用授权码换取 token...")
    try:
        token = client.exchange_auth_code(args.code, redirect_uri=args.redirect_uri)
        client._persist_tokens(token)
        print(f"[成功] token 已保存到 data/tokens.json")
        print(f"  access_token 前缀：{token.access_token[:20]}...")
        return 0
    except Client115Error as exc:
        print(f"[错误] 换码失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
