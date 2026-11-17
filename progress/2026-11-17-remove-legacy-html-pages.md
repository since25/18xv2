# 2026-11-17 删除 7 个旧版内嵌网页

## What was done

架构审核中发现后端路由文件里还留着 11 个旧版内嵌网页（React 前端上线前的服务端页面）。逐项核对后，经用户确认删除其中 7 个，保留 4 个。

删除的 7 个网页（共 8 个地址），对应功能在 React 前端都有页面：

| 旧网页 | 地址 | 所在文件 |
|---|---|---|
| 旧首页导航 | `/`、`/workbench` | `app/api/routes/home.py`（整个文件删除） |
| 目录导入 | `/imports` | `imports.py` |
| 节点浏览 | `/nodes` | `nodes.py` |
| 整理计划 | `/plans/workbench`，以及 `/plans` 到它的跳转 | `plans.py` |
| 整理任务 | `/organize-tasks/workbench` | `tasks.py` |
| 磁力任务 | `/magnet-tasks/workbench` | `magnet_tasks.py` |
| 扫码登录 | `/tools/qr-login` | `qr_login.py` |

保留的 4 个网页（用户确认仍在使用，React 前端没有对应页面）：

- 本地文件清理 `/cleanup/local-files/workbench`
- 本地文件夹整理 `/organize/local-folders/workbench`
- 本地目录树导出 `/local-tree-export/workbench`
- 授权码换令牌 `/tools/auth-code`

配套清理：

- `app/main.py` 去掉 `home` 路由的导入和注册。
- 6 个文件去掉不再使用的 `HTMLResponse` / `RedirectResponse` 导入。
- 保留的 3 个本地功能页去掉指向已删首页的「返回统一工作台」链接；授权码页去掉指向已删扫码页的链接。

只删网页和页面间跳转，所有数据接口保持不变。

## Testing

- Spark：`scripts/remote-test.sh backend`，退出码 0，477 passed，用时 80 秒。日志：Spark 上 `~/ci/18x_v2/18x_v2/.remote-test-logs/20261117-200105-backend.log`。
- 本机加载应用核对路由表：8 个已删地址均不存在；4 个保留网页和抽查的 8 个数据接口均在；路由总数 170。
- 未做：前端测试（本轮未改前端）、生产部署、浏览器里实际打开 4 个保留网页。

## Notes

- 已知取舍（用户已确认不需要）：
  - 整理任务的「歧义冲突导出表格 / 导入表格」只有旧网页有入口。接口 `/organize-tasks/ambiguous-conflicts/export` 和 `import-tsv` 仍保留，但现在没有界面调用。
  - 节点接口 `/nodes/data`、`/nodes/data/{node_id}` 仍保留，同样没有界面调用；React 的节点页用的是 `/imports/{id}/entries`。
- 旧首页删除后，4 个保留网页没有导航入口，需要直接输入地址打开。
- 4 个保留网页调用接口时不带 `/api` 前缀，而生产 nginx 只转发 `/api/` 开头的请求，按配置推断它们在生产上不可用，只能在本机直连后端（8000 端口）时使用。未在生产实测。
- 未提交、未部署。

### Changed files

- `app/api/routes/home.py`（删除）
- `app/api/routes/imports.py`
- `app/api/routes/nodes.py`
- `app/api/routes/plans.py`
- `app/api/routes/tasks.py`
- `app/api/routes/magnet_tasks.py`
- `app/api/routes/qr_login.py`
- `app/api/routes/auth_code.py`
- `app/api/routes/local_cleanup.py`
- `app/api/routes/local_organize.py`
- `app/api/routes/local_tree_export.py`
- `app/main.py`

### Rollback

改动尚未提交，恢复上述 12 个文件即可：

```bash
git checkout -- app/main.py app/api/routes/
```
