# Unraid 脚本日报部署说明

脚本日报接收 `DEL_SOMETHING` 和 `MOVE_SSD_CACHE_TO_DISK2` 的运行结果，保存 90 天名单和长期统计。回报接口沿用 18x 的登录认证，不新增账号。

## 18x 配置和迁移

在 18x 的环境变量中确认：

```dotenv
SCRIPT_REPORT_SCHEDULES=DEL_SOMETHING=12:09,MOVE_SSD_CACHE_TO_DISK2=01:01
```

定时发生变化时，同步修改这个配置；时间按 `Asia/Shanghai` 判断。数据库迁移在 18x 容器启动时由 `docker/entrypoint.sh` 自动执行。回滚时执行 `alembic downgrade 20261101_0016`，只会删除脚本日报的两张表。

## Unraid 文件

把 `scripts/unraid/report_script_run.py` 复制到：

```text
/mnt/cache/docker1/python/scripts/delsomethin/report_script_run.py
```

两个生产脚本都读取 `/boot/config/plugins/user.scripts/scripts/DEL_SOMETHING/.env`，其中已有 `KEYWORDS_API_USERNAME` 和 `KEYWORDS_API_PASSWORD`。回报脚本只读取这两个变量，不把凭证写入日志。

## 生产脚本接入片段

`DEL_SOMETHING` 在 `flock` 判断之后加入，这样被 `flock` 拦下的重复运行不回报。`MOVE_SSD_CACHE_TO_DISK2` 没有 `flock`，在解析完 `DRY_RUN` 之后加入，并把 `REPORT_SCRIPT_NAME` 改成对应脚本名。

```bash
# 脚本日报：输出照常进入 User Scripts 日志，同时写一份临时文件给回报脚本解析
REPORT_SCRIPT_NAME="DEL_SOMETHING"
REPORT_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REPORT_TMP="$(mktemp)"
REPORT_DRY_RUN="${DRY_RUN:-false}"
for report_arg in "$@"; do
    case "$report_arg" in --dry-run|-n) REPORT_DRY_RUN=true ;; esac
done
exec 3>&1 4>&2
exec > >(tee "$REPORT_TMP") 2>&1
REPORT_TEE_PID=$!

report_on_exit() {
    local original_rc=$?
    trap - EXIT
    set +e
    # 恢复输出并等 tee 结束，保证临时文件已写完
    exec 1>&3 2>&4
    wait "$REPORT_TEE_PID"
    case "$REPORT_DRY_RUN" in
        1|true|yes|on) ;;
        *)
            /mnt/cache/docker1/python/scripts/PYTHON_SEHUATANG/venv/bin/python3 \
                /mnt/cache/docker1/python/scripts/delsomethin/report_script_run.py \
                "$REPORT_SCRIPT_NAME" "$REPORT_STARTED_AT" "$original_rc" "$REPORT_TMP" \
                /boot/config/plugins/user.scripts/scripts/DEL_SOMETHING/.env
            ;;
    esac
    rm -f "$REPORT_TMP"
    exit "$original_rc"
}
trap report_on_exit EXIT
```

- 输出通过 `tee` 同时进入原日志和临时文件，原有日志内容不变；trap 里先恢复输出并等待 `tee` 结束，再解析。
- 回报失败只打印一行提示，`exit "$original_rc"` 保证原退出码不变。
- 演练模式不发送回报。

上线顺序：先备份两个 `/boot` 脚本，运行一次 `MOVE_SSD_CACHE_TO_DISK2` 或等它定时运行，确认运行记录和名单，再让 `DEL_SOMETHING` 按定时运行。回滚时恢复备份即可。

## 接口检查

登录后可查看：

```text
GET /api/script-runs/summary?days=7
GET /api/script-runs?limit=50&offset=0
GET /api/script-runs/{id}/items?kind=deleted_file&limit=50&offset=0
```

回报失败不会缓存本地结果；页面会在超过预期时间两小时仍没有记录时显示“今天没有运行记录”。
