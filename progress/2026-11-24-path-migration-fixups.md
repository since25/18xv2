# 2026-11-24 路径迁移补漏

## What was done

- 迁移提交 89361df6 之后体检，补改两处遗漏：
  - 本机 IINA 已安装的「复核入库」脚本（仓库外）：`~/Library/Application Support/com.colliderli.iina/scripts/iina_review_intake.lua` 和 `.../plugins/.data/io.iina.user-script/18x-review-intake.js`，把调用的程序和 Python 路径从 `~/Desktop/wangcodemac/18x_v2` 改为 `~/Developer/wangcodemac/18x_v2`。只换路径，没有同步仓库里的新版脚本内容。
  - `docs/DEVELOPMENT_GUIDE.md`、`PROGRESS.md` 里 6 处旧路径。
- 历史计划/设计文档、`.claude/settings.local.json` 里的旧路径保留不动（只是历史记录或权限白名单，不影响运行）。

## Testing

- 两份 IINA 脚本和两份文档复查已无 `Desktop/wangcodemac`。
- 新路径下 `scripts/review_intake_shortcut.py` 存在，用新 `.venv` 运行 `--help` 正常；登录 cookie 与日志放在用户主目录，不受迁移影响。
- 未在 IINA 里实际按快捷键提交（会真实写入待审池）。

## Notes

- Changed files：`docs/DEVELOPMENT_GUIDE.md`、`PROGRESS.md`、本文件；仓库外两份 IINA 脚本。
- Rollback：仓库内文件用 git 还原；IINA 脚本改前备份在本次会话临时目录 `iina-backup/`（临时目录可能被清理），也可把路径手动改回 Desktop。
- 旧目录 `~/Desktop/wangcodemac` 仍完整保留，是否删除待用户决定。
