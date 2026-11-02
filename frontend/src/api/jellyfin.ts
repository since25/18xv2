import { api } from './client'

/** 后台任务字典，与 BackgroundJobService.to_dict 一致 */
export interface JellyfinJob {
  job_id: string
  job_type: string
  stage: string | null
  current: number | null
  total: number | null
  done: boolean
  error: string | null
  summary: Record<string, number | string | null> | null
  started_at: string | null
  finished_at: string | null
}

export interface JellyfinStatus {
  scan_enabled: boolean
  sync_enabled: boolean
  local_roots: string[]
  strm_roots: string[]
  latest_scan: JellyfinJob | null
  latest_sync: JellyfinJob | null
  counts: {
    active_items: number
    matched: number
    unmatched: number
    nfo_error: number
    pending_resolve: number
  }
  collections: {
    active: number
    conflict: number
    retired: number
  }
}

export type JellyfinMediaSource = 'local' | 'strm_115'
export type JellyfinUnmatchedState = 'unmatched' | 'nfo_error'

export interface JellyfinUnmatchedItem {
  id: number
  source: JellyfinMediaSource
  path: string
  match_state: string
  match_note: string | null
}

export interface JellyfinUnmatchedResponse {
  total: number
  items: JellyfinUnmatchedItem[]
}

export interface JellyfinConflictItem {
  keyword_entry_id: number | null
  canonical_name_snapshot: string | null
  status: string
  last_error: string | null
}

export function getJellyfinStatus() {
  return api.get<JellyfinStatus>('/jellyfin/status')
}

export function startJellyfinScan() {
  return api.post<{ job_id: string }>('/jellyfin/scan')
}

export function startJellyfinSync() {
  return api.post<{ job_id: string }>('/jellyfin/sync')
}

export function getJellyfinJob(jobId: string) {
  return api.get<JellyfinJob>(`/jellyfin/jobs/${encodeURIComponent(jobId)}`)
}

export function listJellyfinUnmatched(params: {
  source?: JellyfinMediaSource
  state?: JellyfinUnmatchedState
  limit: number
  offset: number
}) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  if (params.source) query.set('source', params.source)
  if (params.state) query.set('state', params.state)
  return api.get<JellyfinUnmatchedResponse>(`/jellyfin/unmatched?${query.toString()}`)
}

export function listJellyfinConflicts() {
  return api.get<{ items: JellyfinConflictItem[] }>('/jellyfin/conflicts')
}
