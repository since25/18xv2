-- IINA/mpv 快捷键桥接脚本：读取当前播放路径，调用项目待审核投递脚本。
-- 复制到 IINA 的 scripts 目录后，可在 key binding 中绑定：
--   script-binding iina_review_intake/review-intake-whitelist
--   script-binding iina_review_intake/review-intake-blacklist

local mp = require("mp")

local helper = os.getenv("REVIEW_INTAKE_HELPER")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/scripts/review_intake_shortcut.py"
local python = os.getenv("REVIEW_INTAKE_PYTHON")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/.venv/bin/python"

local function submit(bucket)
  local path = mp.get_property("path")
  if not path or path == "" then
    mp.osd_message("未获取到当前视频路径", 2)
    return
  end

  local args = {
    python,
    helper,
    bucket,
    "--path",
    path,
    "--source",
    "iina_lua",
  }

  mp.osd_message("提交待审核中...", 1)
  mp.command_native_async({
    name = "subprocess",
    args = args,
    playback_only = false,
    capture_stdout = true,
    capture_stderr = true,
  }, function(success, result)
    if success and result and result.status == 0 then
      mp.osd_message(result.stdout or "已提交待审核", 2)
      return
    end

    local stderr = result and result.stderr or "提交失败"
    mp.osd_message(stderr, 4)
  end)
end

mp.add_key_binding(nil, "review-intake-whitelist", function()
  submit("whitelist")
end)

mp.add_key_binding(nil, "review-intake-blacklist", function()
  submit("blacklist")
end)
