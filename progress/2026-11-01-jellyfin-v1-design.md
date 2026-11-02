# 2026-11-01 Jellyfin 第一版设计

## What was done

- 评估三项新需求（115 资源管理、本地脚本纳管、串联 Jellyfin）与现有架构的关系，与用户逐项澄清。
- 只读查看 Unraid 上 `DEL_SOMETHING`、`MOVE_SSD_CACHE_TO_DISK2` 两批脚本及其计划时间；确认脚本的关键词来自 18x `/api/keywords`。
- 只读抽查 STRM 目录规模、NFO 字段、disk2「已整理」目录结构和 Emby 挂载方式。
- 调研现成 302 代理，选定 MediaWarp 作为首选。
- 产出设计文档 `docs/superpowers/specs/2026-11-01-jellyfin-v1-design.md`（待用户确认）。

## Testing

- 无代码改动，不涉及测试。服务器侧操作全部为只读命令；未读取脚本目录下的 `.env`。

## Notes

- Changed files：
  - `docs/superpowers/specs/2026-11-01-jellyfin-v1-design.md`（新增）
  - `progress/2026-11-01-jellyfin-v1-design.md`（新增）
- Rollback：删除上述两个文件即可。
- 未提交 git。

## 追加：按用户纠正修订设计（同日）

### What was done

- 只读确认 Unraid 上已有 MediaWarp 容器（9001，接 Emby，`http_strm` + `final_url`）和 MDC 容器（源 `porn_tv1` → 硬链接输出 `302porn_tv1`，目录规则 `{actor}/{number}`）。
- 设计改为：新起第二个 MediaWarp 实例接 Jellyfin（现有实例不动）；115 侧只纳入 `302porn_tv1`，`porn_tv1` 移出第一版以避免约 6300 个重复条目；Jellyfin 与 18x 统一使用 `/mnt/user/docker1/alist-strm/video` 路径。

### Testing

- 无代码改动。服务器侧均为只读命令。查看 MediaWarp 配置时脱敏规则漏掉了 `auth` 字段，Emby API Key 出现在本地会话输出中，未写入任何文件。

### Notes

- Changed files：`docs/superpowers/specs/2026-11-01-jellyfin-v1-design.md`（修订）、本日志（追加）。
- Rollback：删除这两个文件。
