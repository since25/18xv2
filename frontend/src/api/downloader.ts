import { api } from './client'

export interface DownloaderStatus {
  enabled: boolean
  node_key: string
  base_url_configured: boolean
  remote_ready: boolean
  remote: Record<string, unknown> | null
  latest_sync: Record<string, unknown> | null
}

export interface DownloaderCandidate {
  candidate_id: number
  package_id: number
  remote_package_id: number
  library_id: number | null
  title: string
  channel_title: string | null
  published_at: string | null
  boundary_status: string
  media_count: number
  known_total_size: number
  current_download_status: string
  package_revision: number
  completed_revision: number | null
  keyword_entry_id: number
  keyword: string
  matched_term: string
  match_reason: string | null
  status: string
  updated_at: string | null
}

export interface DownloaderCandidateList {
  items: DownloaderCandidate[]
  total: number
  page: number
  page_size: number
}

export interface DownloaderTask {
  id: number
  remote_task_id: string
  source: string | null
  task_type: string | null
  title: string | null
  status: string
  total_count: number
  success_count: number
  failed_count: number
  current_file: Record<string, unknown> | null
  observed_at: string | null
}

export interface DownloaderTaskHistory {
  id: number
  remote_task_id: string
  status: string
  total_count: number
  success_count: number
  failed_count: number
  current_file: Record<string, unknown> | null
  observed_at: string | null
  files: Array<Record<string, unknown>>
}

export function getDownloaderStatus() {
  return api.get<DownloaderStatus>('/downloader/status')
}

export function syncDownloaderPackages() {
  return api.post<{ packages_seen: number; candidates_created: number }>('/downloader/sync')
}

export function listDownloaderCandidates(params: { status?: string; search?: string; page?: number; pageSize?: number } = {}) {
  const query = new URLSearchParams()
  query.set('candidate_status', params.status ?? 'pending')
  if (params.search) query.set('search', params.search)
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.pageSize ?? 50))
  return api.get<DownloaderCandidateList>(`/downloader/packages?${query.toString()}`)
}

export function selectDownloaderCandidate(candidateId: number, selected: boolean) {
  return api.post<{ candidate_id: number; status: string }>(`/downloader/packages/${candidateId}/select`, { selected })
}

export function submitDownloaderBatches(candidateIds: number[]) {
  return api.post<{ submitted: number; skipped: number; failed: number }>('/downloader/download-batches', { candidate_ids: candidateIds })
}

export function listDownloaderTasks() {
  return api.get<{ items: DownloaderTask[]; total: number }>('/downloader/tasks?limit=100')
}

export function listDownloaderTaskHistory(taskId: string) {
  return api.get<{ task_id: string; items: DownloaderTaskHistory[] }>(
    `/downloader/tasks/${encodeURIComponent(taskId)}/history?limit=100`,
  )
}

export function syncDownloaderTasks() {
  return api.post<{ tasks_seen: number; tasks_updated: number }>('/downloader/tasks/sync')
}

export function controlDownloader(state: 'pause' | 'resume') {
  return api.post('/downloader/control', { state })
}

export function cancelDownloaderTask(taskId: string) {
  return api.post(`/downloader/tasks/${encodeURIComponent(taskId)}/cancel`)
}

export function retryDownloaderTask(taskId: string) {
  return api.post(`/downloader/tasks/${encodeURIComponent(taskId)}/retry`)
}
