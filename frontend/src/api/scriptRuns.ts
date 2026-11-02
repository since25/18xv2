import { api } from './client'

export type ScriptRunStatus = 'success' | 'warning' | 'failed'
export type ScriptTodayStatus = ScriptRunStatus | 'pending' | 'missing'
export type ScriptRunItemKind =
  | 'deleted_dir'
  | 'deleted_file'
  | 'moved_new'
  | 'moved_rescan'
  | 'empty_dir'
  | 'ambiguous'
  | 'skipped'
  | 'error'
  | 'warning'

export interface ScriptRunCounts {
  deleted_dirs: number
  deleted_files: number
  empty_dirs: number
  moved_new: number
  moved_rescan: number
  ambiguous: number
  skipped: number
  errors: number
  warnings: number
  unparsed_lines: number
  moved: number
  duplicates_removed: number
  failed: number
}

export interface ScriptRun {
  id: number
  run_key: string
  script_name: string
  started_at: string
  finished_at: string
  exit_code: number
  status: ScriptRunStatus
  counts: ScriptRunCounts
  items_truncated: boolean
  received_at: string
}

export interface ScriptRunDay {
  date: string
  has_run: boolean
  cleaned: number
  moved_new: number
}

export interface ScriptRunSummary {
  timezone: string
  days: ScriptRunDay[]
  scripts: Array<{
    script_name: string
    expected_time: string
    latest_run: ScriptRun | null
    today_status: ScriptTodayStatus
  }>
}

export interface ScriptRunItem {
  id: number
  kind: ScriptRunItemKind
  path: string | null
  target_path: string | null
  keyword: string | null
  message: string | null
}

export interface ScriptRunItemsResponse {
  total: number
  items: ScriptRunItem[]
  kind_counts: Partial<Record<ScriptRunItemKind, number>>
}

export function getScriptRunSummary(days = 7) {
  return api.get<ScriptRunSummary>(`/script-runs/summary?days=${days}`)
}

export function listScriptRuns(params: { limit: number; offset: number }) {
  return api.get<{ total: number; items: ScriptRun[] }>(`/script-runs?limit=${params.limit}&offset=${params.offset}`)
}

export function listScriptRunItems(
  runId: number,
  params: { kind?: ScriptRunItemKind; q?: string; limit: number; offset: number },
) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  if (params.kind) query.set('kind', params.kind)
  if (params.q) query.set('q', params.q)
  return api.get<ScriptRunItemsResponse>(`/script-runs/${runId}/items?${query.toString()}`)
}
