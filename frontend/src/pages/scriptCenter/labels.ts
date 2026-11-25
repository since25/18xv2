// 脚本中心共用的名称、状态文字和一句话结果
import type { ScriptRun, ScriptRunCounts, ScriptRunItemKind, ScriptRunStatus, ScriptTodayStatus } from '@/api/scriptRuns'

export const SCRIPT_LABELS: Record<string, string> = {
  sehuatang: '色花堂抓取',
  DEL_SOMETHING: '整理脚本',
  MOVE_SSD_CACHE_TO_DISK2: '搬运脚本',
}

export const RUN_STATUS: Record<ScriptRunStatus, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  success: { label: '正常', color: 'success' },
  warning: { label: '有警告', color: 'warning' },
  failed: { label: '失败', color: 'error' },
  stopped: { label: '已停止', color: 'default' },
  interrupted: { label: '已中断', color: 'warning' },
}

export const TODAY_STATUS: Record<ScriptTodayStatus, { label: string; color: string }> = {
  ...RUN_STATUS,
  pending: { label: '今天还没到运行时间', color: 'default' },
  missing: { label: '今天没有运行记录', color: 'error' },
  disabled: { label: '已停用', color: 'default' },
  not_tracked: { label: '未接入日报', color: 'default' },
}

// 页签顺序：先看结果，再看问题
export const KIND_LABELS: Array<[ScriptRunItemKind, string]> = [
  ['submitted', '已提交'],
  ['deleted_file', '清理-文件'],
  ['deleted_dir', '清理-目录'],
  ['moved_new', '新命中'],
  ['moved_rescan', '重新归位'],
  ['empty_dir', '空文件夹'],
  ['title_blocked', '标题被拦'],
  ['torrent_blocked', '种子被拦'],
  ['submit_failed', '提交失败'],
  ['parse_failed', '解析失败'],
  ['error', '报错'],
  ['warning', '警告'],
  ['ambiguous', '词条歧义'],
  ['skipped', '跳过'],
]

export function scriptLabel(name: string) {
  return SCRIPT_LABELS[name] ?? name
}

const ZERO_COUNTS: Required<ScriptRunCounts> = {
  deleted_dirs: 0, deleted_files: 0, empty_dirs: 0, moved_new: 0, moved_rescan: 0, ambiguous: 0,
  skipped: 0, errors: 0, warnings: 0, unparsed_lines: 0, moved: 0, duplicates_removed: 0, failed: 0,
  pages_ok: 0, pages_failed: 0, posts_found: 0, title_blocked: 0, torrent_blocked: 0, skipped_seen: 0,
  submitted: 0, submit_failed: 0, parse_failed: 0,
}

/** 接口里的计数字段都有默认值，类型上是可选的；这里补齐成 0 */
export function fullCounts(counts: ScriptRunCounts): Required<ScriptRunCounts> {
  return { ...ZERO_COUNTS, ...counts } as Required<ScriptRunCounts>
}

/** 一次运行的一句话结果 */
export function describeRun(run: ScriptRun) {
  const c = fullCounts(run.counts)
  if (run.script_name === 'sehuatang') {
    return `提交 ${c.submitted}，标题拦 ${c.title_blocked}，种子拦 ${c.torrent_blocked}，跳过 ${c.skipped_seen}，失败 ${c.submit_failed + c.parse_failed}`
  }
  if (run.script_name === 'DEL_SOMETHING') {
    const parts = [
      `清理 ${c.deleted_dirs + c.deleted_files}（目录 ${c.deleted_dirs}，文件 ${c.deleted_files}）`,
      `新命中 ${c.moved_new}`,
    ]
    if (c.moved_rescan > 0) parts.push(`重新归位 ${c.moved_rescan}`)
    if (c.empty_dirs > 0) parts.push(`空文件夹 ${c.empty_dirs}`)
    if (c.errors > 0) parts.push(`报错 ${c.errors}`)
    if (c.warnings > 0) parts.push(`警告 ${c.warnings}`)
    return parts.join('，')
  }
  return `移动 ${c.moved}，删除重复 ${c.duplicates_removed}，跳过 ${c.skipped}，失败 ${c.failed}`
}
