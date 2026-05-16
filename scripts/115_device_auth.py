"""
115 设备码授权脚本。通过 QR 扫码完成 Open API 授权，换取 access token 并持久化到 data/tokens.json。
适用场景：启动时 token 失效，或首次部署尚未授权。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.client_115.client import Client115Error, Real115Client
from app.services.client_115.token_store import save_tokens


def main() -> int:
    settings = get_settings()
    if not settings.app_id:
        print("[错误] APP_ID 未配置，请检查 .env", file=sys.stderr)
        return 1

    client = Real115Client()

    print("[1/3] 正在获取设备码...")
    try:
        payload, code_verifier = client.create_device_code()
    except Client115Error as exc:
        print(f"[错误] 获取设备码失败：{exc}", file=sys.stderr)
        return 1

    print(f"\n请使用 115 App 扫描以下二维码或访问链接：")
    print(f"  QR 数据：{payload.qrcode}\n")

    # 保存二维码图片到 data/qr.png，同时尝试 ASCII 显示
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=2)
        qr.add_data(payload.qrcode)
        qr.make(fit=True)

        # 优先保存图片（不依赖终端宽度）
        try:
            from PIL import Image  # type: ignore
            img = qr.make_image(fill_color="black", back_color="white")
            qr_path = Path("data/qr.png")
            qr_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(qr_path)
            print(f"  二维码图片已保存：{qr_path.resolve()}")
            import subprocess, platform
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(qr_path)])
        except Exception:  # noqa: BLE001
            pass

        # 仍尝试 ASCII（终端够宽时可用）
        try:
            qr.print_ascii(invert=True)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass

    print("[2/3] 等待扫码确认（最长 3 分钟）...")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            status_resp = client.poll_device_status(
                uid=payload.uid,
                time_value=payload.time,
                sign=payload.sign,
            )
        except Client115Error as exc:
            print(f"  [警告] 轮询出错：{exc}")
            continue

        status = int((status_resp.get("data") or {}).get("status", 0))
        if status == 0:
            print("  等待扫码...")
        elif status == 1:
            print("  已扫码，请在手机上点击确认...")
        elif status == 2:
            print("  扫码成功！正在换取 token...")
            break
        else:
            print(f"[错误] 二维码已失效（status={status}）", file=sys.stderr)
            return 1
    else:
        print("[错误] 等待超时，请重新运行脚本。", file=sys.stderr)
        return 1

    print("[3/3] 正在换取 access token...")
    try:
        token = client.exchange_device_code(uid=payload.uid, code_verifier=code_verifier)
        client._persist_tokens(token)
        print(f"[成功] token 已保存到 data/tokens.json")
        print(f"  access_token 前缀：{token.access_token[:20]}...")
        return 0
    except Client115Error as exc:
        print(f"[错误] 换取 token 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
