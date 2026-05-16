# CLI 脚本说明

所有脚本在项目根目录下运行，依赖 `.venv`：

```bash
cd /Users/wangyichuan/Desktop/wangcodemac/18x_v2
source .venv/bin/activate
```

## 脚本列表

### start_dev.sh — 本机启动服务
```bash
bash scripts/start_dev.sh
```
脚本会自动加载 `.env`、执行 `alembic upgrade head`，然后以开发模式启动 `uvicorn app.main:app`。

如需关闭热重载：
```bash
UVICORN_RELOAD=0 bash scripts/start_dev.sh
```

### 115_device_auth.py — 设备码 QR 扫码授权
```bash
python scripts/115_device_auth.py
```
在终端显示二维码，用 115 App 扫码后换取 token 并保存到 `data/tokens.json`。

### 115_auth_code.py — 授权码换 token
```bash
python scripts/115_auth_code.py --code <CODE>
```
用从 115 授权页获取的 code 换取 token。适合 QR 扫码不便时的人工兜底。

### sync_strategy_rules.py — 规则同步
```bash
python scripts/sync_strategy_rules.py                        # 同步到 DB
python scripts/sync_strategy_rules.py --dry-run              # 仅预览
python scripts/sync_strategy_rules.py --rules-file path/to/rules.yaml
```
将 `examples/rules.yaml` 的规则同步到 `strategy_rules` 表。部署后运行一次。

### 115_real_smoke.py — API 冒烟测试
```bash
python scripts/115_real_smoke.py                            # 只读冒烟
python scripts/115_real_smoke.py --no-dry-run --parent-cid CID  # 读写验证
```
验证 115 API 链路可达。写操作需配置 `TEST_ALLOWED_PATH_PREFIXES`。

### keyword_extractor.py — 关键词提取
```bash
python scripts/keyword_extractor.py --import-id 1
python scripts/keyword_extractor.py --import-id 1 --top 30
python scripts/keyword_extractor.py --import-id 1 --keywords "词A" "词B"
```
从已导入的目录树批次中提取关键词候选，输出命中统计。
