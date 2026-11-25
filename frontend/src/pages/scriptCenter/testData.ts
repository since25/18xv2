// 脚本中心测试用的数据构造（标题、路径都是虚构的）
import type { ScriptJob } from '@/api/scriptJobs'
import type { ScriptRun, ScriptRunCounts } from '@/api/scriptRuns'

export const ZERO: ScriptRunCounts = {
  deleted_dirs: 0, deleted_files: 0, empty_dirs: 0, moved_new: 0, moved_rescan: 0, ambiguous: 0,
  skipped: 0, errors: 0, warnings: 0, unparsed_lines: 0, moved: 0, duplicates_removed: 0, failed: 0,
  pages_ok: 0, pages_failed: 0, posts_found: 0, title_blocked: 0, torrent_blocked: 0, skipped_seen: 0,
  submitted: 0, submit_failed: 0, parse_failed: 0,
}

export function makeRun(overrides: Partial<ScriptRun> = {}): ScriptRun {
  return {
    id: 1,
    run_key: 'DEL_SOMETHING:1',
    script_name: 'DEL_SOMETHING',
    started_at: '2026-11-01T04:09:00Z',
    finished_at: '2026-11-01T04:10:00Z',
    exit_code: 0,
    status: 'success',
    counts: { ...ZERO, deleted_dirs: 6, deleted_files: 44, moved_new: 12, moved_rescan: 2 },
    items_truncated: false,
    received_at: '2026-11-01T04:10:01Z',
    trigger: 'report',
    dry_run: false,
    error_reason: null,
    has_log: false,
    ...overrides,
  }
}

export function makeJob(overrides: Partial<ScriptJob> = {}): ScriptJob {
  return {
    job_name: 'sehuatang',
    label: '色花堂抓取',
    executor: '18x',
    enabled: true,
    run_time: '01:28',
    params: { pages: 4, forum_url: 'https://sehuatang.org/f?page={page}', qb_category: '国产BT' },
    runnable: true,
    next_run_at: '2026-11-26T17:28:00Z',
    active_run: null,
    latest_run: null,
    alert: null,
    site_session: { configured: true, updated_at: '2026-11-25T10:00:00Z' },
    ...overrides,
  }
}

export const DEL_JOB = makeJob({
  job_name: 'DEL_SOMETHING',
  label: '整理脚本',
  run_time: '12:09',
  params: { delete_dirs: ['/mnt/cache/docker1/SSD_cache'], organize_jobs: [], merge_on_conflict: true, fix_permissions: true },
  site_session: null,
})

/** antd 会在两个汉字的按钮文字中间插空格，按按钮角色和忽略空白的名称查找 */
export function buttonName(label: string) {
  return new RegExp(`^${[...label].join('\\s*')}$`)
}
