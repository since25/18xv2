-- IINA/mpv 快捷键桥接脚本：读取当前播放路径，提交 Emby 媒体动作。
-- 复制到 IINA 的 scripts 目录后，可在 key binding 中绑定：
--   script-binding iina_emby_media_actions/emby-delete-plan
--   script-binding iina_emby_media_actions/emby-blacklist-candidate
--   script-binding iina_emby_media_actions/emby-whitelist-candidate

local mp = require("mp")

local helper = os.getenv("EMBY_MEDIA_ACTIONS_HELPER")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/scripts/emby_media_action_shortcut.py"
local python = os.getenv("EMBY_MEDIA_ACTIONS_PYTHON")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/.venv/bin/python"
local base_url = os.getenv("EMBY_MEDIA_ACTIONS_BASE_URL")
  or "http://192.168.70.138:8010/api"
local log_path = os.getenv("EMBY_MEDIA_ACTIONS_LOG")
  or "/Users/wangyichuan/Library/Application Support/com.colliderli.iina/scripts/emby_media_actions.log"

local function log_line(message)
  local file = io.open(log_path, "a")
  if not file then
    return
  end
  file:write(os.date("%Y-%m-%d %H:%M:%S"), " ", message, "\n")
  file:close()
end

log_line("script loaded")

local function has_url_scheme(value)
  return value and value:match("^%a[%w+.-]*://") ~= nil
end

local function is_absolute_path(value)
  return value and (value:sub(1, 1) == "/" or has_url_scheme(value))
end

local function join_path(directory, filename)
  if not directory or directory == "" then
    return filename
  end
  if directory:sub(-1) == "/" then
    return directory .. filename
  end
  return directory .. "/" .. filename
end

local function current_media_path()
  local path = mp.get_property("path")
  local stream_open_filename = mp.get_property("stream-open-filename")
  local working_directory = mp.get_property("working-directory")
  local filename = mp.get_property("filename")

  log_line("path=" .. tostring(path))
  log_line("stream-open-filename=" .. tostring(stream_open_filename))
  log_line("working-directory=" .. tostring(working_directory))
  log_line("filename=" .. tostring(filename))

  if path and path ~= "" then
    if is_absolute_path(path) then
      return path
    end
    if working_directory and working_directory ~= "" then
      return join_path(working_directory, path)
    end
    return path
  end

  if stream_open_filename and stream_open_filename ~= "" then
    return stream_open_filename
  end

  if filename and filename ~= "" and working_directory and working_directory ~= "" then
    return join_path(working_directory, filename)
  end

  return nil
end

local function submit(action)
  local path = current_media_path()
  if not path or path == "" then
    log_line("submit failed: empty media path")
    mp.osd_message("未获取到当前视频路径", 2)
    return
  end
  log_line("submit action=" .. action .. " resolved_path=" .. path)

  local args = {
    python,
    helper,
    action,
    "--path",
    path,
    "--source",
    "iina_lua",
    "--base-url",
    base_url,
  }

  mp.osd_message("提交 Emby 媒体动作中...", 1)
  mp.command_native_async({
    name = "subprocess",
    args = args,
    playback_only = false,
    capture_stdout = true,
    capture_stderr = true,
  }, function(success, result)
    if success and result and result.status == 0 then
      log_line("submit ok stdout=" .. tostring(result.stdout))
      mp.osd_message(result.stdout or "已提交 Emby 媒体动作", 2)
      return
    end

    local stderr = result and result.stderr or "提交失败"
    log_line("submit failed success=" .. tostring(success) .. " status=" .. tostring(result and result.status) .. " stderr=" .. tostring(stderr))
    mp.osd_message(stderr, 4)
  end)
end

mp.add_key_binding(nil, "emby-delete-plan", function()
  submit("delete-plan")
end)

mp.add_key_binding(nil, "emby-blacklist-candidate", function()
  submit("blacklist")
end)

mp.add_key_binding(nil, "emby-whitelist-candidate", function()
  submit("whitelist")
end)
