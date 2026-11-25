import { api } from './client'
import type { components } from './schema.gen'

export type ScriptRun = components['schemas']['ScriptRunResponse']
export type ScriptRunCounts = components['schemas']['ScriptRunCounts']
export type ScriptRunStatus = ScriptRun['status']
export type ScriptRunItem = components['schemas']['ScriptRunItemResponse']
export type ScriptRunLogChunk = components['schemas']['ScriptRunLogChunk']
export type ScriptTodayStatus = ScriptRunStatus | 'pending' | 'missing' | 'disabled' | 'not_tracked'
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
  | 'submitted'
  | 'title_blocked'
  | 'torrent_blocked'
  | 'submit_failed'
  | 'parse_failed'

export interface ScriptRunDay {
  date: string
  has_run: boolean
  cleaned: number
  moved_new: number
}

// 汇总接口没有声明响应模型，类型在这里手写
export interface ScriptRunSummary {
  timezone: string
  days: ScriptRunDay[]
  scripts: Array<{
    script_name: string
    expected_time: string
    executor: string
    enabled: boolean
    latest_run: ScriptRun | null
    today_status: ScriptTodayStatus
  }>
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

export function stopScriptRun(runId: number) {
  return api.post<{ ok: boolean }>(`/script-runs/${runId}/stop`)
}

export function getScriptRunLog(runId: number, offset: number) {
  return api.get<ScriptRunLogChunk>(`/script-runs/${runId}/log?offset=${offset}`)
}
