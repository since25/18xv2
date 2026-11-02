# Unraid 脚本日报后端

## What was done

- 新增两个 Unraid 输出解析器、幂等回报客户端和演练模式安全退出处理。
- 新增 `script_runs`、`script_run_items` 模型、0017 迁移、认证保护的回报和查询接口。
- 新增汇总时区计算、预期时间状态、90 天名单清理和 5000 条名单截断。
- 新增中文部署说明，包含两个生产脚本的 trap 接入片段。

## Testing

- `scripts/remote-test.sh backend tests/script_runs/test_report_script.py tests/api/test_script_runs_routes.py -q`：通过，7 passed。
- `scripts/remote-test.sh backend tests/script_runs/test_report_script.py tests/api/test_script_runs_routes.py tests/test_migrations.py -q`：通过，13 passed。
- `scripts/remote-test.sh backend`：通过，436 passed，18 warnings。

## Notes

- Changed files / Rollback：新增脚本日报相关文件；回滚可执行 `alembic downgrade 20261101_0016` 并恢复生产脚本备份。

## 补充：前端与联调

### What was done

- 新增「脚本日报」页面（`/script-runs`）：最近 7 天清理数和新命中趋势、两个脚本的今日状态、运行记录、按类别查看名单和搜索路径。
- 联调发现解析器把正常输出算成未识别行，已修正：只统计未知标签和已知标签的格式错误。
- 修正部署说明中的 `.env` 路径、日志写法和迁移方式。

### Testing

- `scripts/remote-test.sh backend`：438 passed，18 warnings。
- `scripts/remote-test.sh frontend src/pages/ScriptRunsPage.test.tsx`：4 passed，构建通过；lint 只有 `EmbyMediaActionsPage`、`ReviewIntakePage` 的既有问题。
- 本地真实后端加虚构数据联调：趋势图、无记录显示、名单展开和页签正常。
- 脚本接入片段在 bash 5.2 上模拟：退出码 0、1、7 都保持不变，`set -e` 行为不变，演练模式不回报。

### Notes

- 真实日志核对和生产上线另行记录。
- Changed files：见提交。Rollback：恢复 Unraid 脚本备份，回退 18x 版本，必要时 `alembic downgrade 20261101_0016`。
