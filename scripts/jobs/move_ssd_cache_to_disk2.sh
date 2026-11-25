#!/bin/bash
# ============================================================
# 移动 SSD 缓存"已整理"目录的文件到 disk2"已整理"目录
#   源目录: 环境变量 MOVE_SOURCE_DIR(默认配置 /mnt/cache/docker1/SSD_cache/已整理)
#   目标目录: 环境变量 MOVE_TARGET_DIR(默认配置 /mnt/disk2/qbbtdn/已整理)
#   两个目录由 18x 脚本中心按页面参数传入
# 移动完成后将权限设置为 99:100(即 Unraid 的 nobody:users;容器里 nobody 是 65534,必须写数字)
# 来源: Unraid User Scripts 的 MOVE_SSD_CACHE_TO_DISK2,移入 18x 时只改了目录来源、去掉日报回报、权限改为数字
# 规则:
#   - 目标不存在         -> 直接移动
#   - 同名目录           -> 递归合并内容,源目录空后删除
#   - 同名文件且大小一致 -> 真重复,删除源文件(目标已有相同文件)
#   - 同名文件但大小不同 -> 内容不同,以"_新版本"后缀移入目标保留两版
#   - 目录/文件类型冲突  -> 跳过并提示
# 用法: 直接运行即执行;传 --dry-run 或 -n 仅演练不实际移动
# ============================================================

set -u

SRC="${MOVE_SOURCE_DIR:?未设置源目录 MOVE_SOURCE_DIR}"
DST="${MOVE_TARGET_DIR:?未设置目标目录 MOVE_TARGET_DIR}"

# --- 演练模式 ---
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ] || [ "${1:-}" = "-n" ]; then
  DRY_RUN=1
  echo "[演练模式] 不会实际移动/删除文件"
fi

# --- 检查源目录 ---
if [ ! -d "$SRC" ]; then
  echo "错误: 源目录不存在: $SRC"
  exit 1
fi

# --- 确保目标目录存在 ---
if [ ! -d "$DST" ]; then
  echo "目标目录不存在,创建: $DST"
  if [ $DRY_RUN -eq 0 ]; then
    mkdir -p "$DST" || { echo "错误: 无法创建目标目录"; exit 1; }
  fi
fi

MOVED=0
DELETED=0
SKIPPED=0
FAILED=0

# 递归移动/合并: 将 src_dir 下的条目移入 dst_dir
merge_move() {
  local src_dir="$1" dst_dir="$2" item name dest
  local s1 s2 ext base newname newdest i
  shopt -s nullglob
  for item in "$src_dir"/*; do
    [ -e "$item" ] || continue
    name="$(basename "$item")"
    dest="$dst_dir/$name"

    if [ -e "$dest" ] || [ -L "$dest" ]; then
      if [ -d "$dest" ] && [ -d "$item" ]; then
        # 同名目录 -> 递归合并
        echo "合并目录: $name"
        merge_move "$item" "$dest"
        # 源目录内容已全部移走则删除空目录
        if [ -z "$(ls -A "$item" 2>/dev/null)" ]; then
          echo "  清理空目录: $name"
          if [ $DRY_RUN -eq 0 ]; then
            rmdir "$item"
          fi
        fi
      elif [ -f "$dest" ] && [ -f "$item" ]; then
        # 同名文件冲突 -> 比较大小判断是否真重复
        s1=$(stat -c%s "$item")
        s2=$(stat -c%s "$dest")
        if [ "$s1" = "$s2" ]; then
          # 大小一致 -> 真重复,删除源文件
          echo "删除重复(目标已有相同文件, $s1 字节): $name"
          if [ $DRY_RUN -eq 0 ]; then
            if rm "$item"; then
              DELETED=$((DELETED+1))
            else
              echo "  删除失败: $name"
              FAILED=$((FAILED+1))
            fi
          else
            DELETED=$((DELETED+1))
          fi
        else
          # 大小不同 -> 保留两版,源文件以"_新版本"后缀移入目标
          ext="${name##*.}"
          base="${name%.*}"
          newname="${base}_新版本.${ext}"
          newdest="$dst_dir/$newname"
          i=2
          while [ -e "$newdest" ]; do
            newname="${base}_新版本${i}.${ext}"
            newdest="$dst_dir/$newname"
            i=$((i+1))
          done
          echo "大小不同($s1 vs $s2),另存为新版本: $newname"
          if [ $DRY_RUN -eq 0 ]; then
            if mv "$item" "$newdest"; then
              MOVED=$((MOVED+1))
            else
              echo "  移动失败: $name"
              FAILED=$((FAILED+1))
            fi
          else
            MOVED=$((MOVED+1))
          fi
        fi
      else
        # 目录/文件类型冲突
        echo "跳过(目录/文件类型冲突): $name"
        SKIPPED=$((SKIPPED+1))
      fi
    else
      # 目标不存在 -> 直接移动
      echo "移动: $name"
      if [ $DRY_RUN -eq 0 ]; then
        if mv "$item" "$dest"; then
          MOVED=$((MOVED+1))
        else
          echo "  移动失败: $name"
          FAILED=$((FAILED+1))
        fi
      else
        MOVED=$((MOVED+1))
      fi
    fi
  done
}

echo "开始移动: $SRC -> $DST"
echo "------------------------------------------"
merge_move "$SRC" "$DST"

# --- 设置 99:100 权限(Unraid nobody:users) ---
if [ $DRY_RUN -eq 0 ] && [ -d "$DST" ]; then
  echo "------------------------------------------"
  echo "设置权限 99:100(Unraid nobody:users) ..."
  chown -R 99:100 "$DST"
  # 目录 775, 文件 664(与源目录权限一致)
  find "$DST" -type d -exec chmod 775 {} +
  find "$DST" -type f -exec chmod 664 {} +
  echo "权限设置完成"
fi

echo "=========================================="
echo "完成: 移动 $MOVED 个, 删除重复 $DELETED 个, 跳过 $SKIPPED 个, 失败 $FAILED 个"
if [ $DRY_RUN -eq 1 ]; then
  echo "(演练模式,未实际移动/删除文件)"
fi
