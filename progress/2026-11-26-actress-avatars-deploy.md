# 2026-11-26 女优头像：部署、试跑并打开每日自动补头像

改动见 `progress/2026-11-26-actress-avatars.md`（提交 `887eb647`）。

## What was done

- 推送 `main`（`887eb647`）到 GitHub。
- 部署前准备：
  - 确认生产机上 `/mnt/user/docker1/mdc_ng/data/mapping_actor.xml` 存在（约 1.2MB）；
  - 备份 organizer 库到 `data/backup_20261126_before_0020.sql`（203M，pg_dump 正常结束）；
  - 备份 `.env` 到 `data/env_backup_20261126_before_avatars.env`，再追加 `ACTRESS_AVATAR_NAME_MAP=/app/mdc/mapping_actor.xml`。`ACTRESS_AVATARS_ENABLED` 没写，保持默认关闭。
- 部署：用户在终端执行拉取代码并重建 `docker-app-1`（本机安全钩子会拦截重建命令）。容器启动时迁移升到 `20261126_0020`。compose 把 MDC 数据目录只读挂到 `/app/mdc`。

## Testing

- 部署后核对：
  - 生产机代码 `887eb64`；`docker-app-1` 在运行，重启 0 次；
  - `alembic current` 是 `20261126_0020 (head)`；
  - `/healthz` 返回 200；接口文档里已有 `/actresses/avatars/refresh`；
  - 容器内能读到 MDC 对照表，共 15286 个名字映射；
  - 每日自动补头像判定为关闭（False）；
  - 1570 位女优的头像状态都是 `pending`；
  - 启动后日志里没有 ERROR 或 Traceback。
- 单人验证（用户批准）：对片数最多的女优（id 451，342 部）用统一任务启动器跑了一次 `actress:avatars`，并带上 `actress_ids=[451]`。任务状态是「完成」，没有报错；她的状态变为 `uploaded`，来源 `4-Kawaii/<日文名>.jpg`。
  - 只读核对：Jellyfin 里规范名对应的人物已有主图。取回的图是 `image/jpeg`，95315 字节，能正常解码为 640×896 的 JPEG，和 Gfriends 原图字节数、尺寸一致。
  - 结论：base64 上传格式在 Jellyfin 10.10.7 上有效，没有传上坏图。
  - 用户在 18x「女优」页确认她的头像正常显示。
- 三人试跑（用户批准）：片数第 2～4 位女优（id 619、156、116）在一个 `actress:avatars` 任务里处理，三人都是 `uploaded`。
  - 来源分别是 `0-Hand-Storage`、`2-Nanairo`、`0-Hand-Storage`；
  - 从 Jellyfin 取回的图都能正常解码为 JPEG，尺寸分别为 1280×1920、400×400、564×720。
- 详情抽屉头部的排版不好看（用户提出），暂不改，先把功能跑通，以后再优化。
- 打开每日自动补头像（用户批准）：
  - 备份 `.env` 到 `data/env_backup_20261126_before_avatars_enabled.env`，再追加 `ACTRESS_AVATARS_ENABLED=true`；
  - 用户在终端执行 `up -d --force-recreate app`。用户要求放宽拦截部署命令的本机安全钩子，按规定不代改，已告知用户自行修改的位置；
  - 重启后核对：容器在运行，重启 0 次；`/healthz` 返回 200；每日补头像判定为 True；每次上限 300，每天 3 点运行；头像状态为 4 位 `uploaded`、1566 位 `pending`；日志里没有 ERROR。
  - 待核对：2026-11-27 03:00 首次自动运行的任务摘要（各状态人数、对照表有没有正常使用）。

## Notes

- Changed files：本日志（新增）。生产 `.env` 追加了两行（`ACTRESS_AVATAR_NAME_MAP`、`ACTRESS_AVATARS_ENABLED=true`），重建了两次容器，给 4 位女优上传了 Jellyfin 人物主图。
- 下一步：2026-11-27 早上核对 03:00 首次自动运行的任务摘要；详情抽屉排版以后再优化。
- Rollback（停用自动补头像：把 `ACTRESS_AVATARS_ENABLED` 改回 false 并重建容器即可）：
  1. 在新代码上执行 `docker exec docker-app-1 alembic downgrade 20261126_0019`；
  2. `.env` 换回备份；
  3. 生产机代码切回 `b0f5bfc`，重建容器。
