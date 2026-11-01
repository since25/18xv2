import { api } from './client'

export interface DownloaderStatus {
  enabled: boolean
  node_key: string
  base_url_configured: boolean
  remote_ready: boolean
  remote: Record<string, unknown> | null
  latest_sync: {
    kind?: string
    status?: string
    packages_seen?: number
    candidates_created?: number
    tasks_seen?: number
    error_message?: string | null
    started_at?: string | null
    finished_at?: string | null
  } | null
}

export interface InboxKeyword {
  keyword_entry_id: number
  keyword: string
  matched_term: string
}

export interface InboxItem {
  package_id: number
  remote_package_id: number
  title: string
  channel_title: string | null
  published_at: string | null
  media_count: number
  known_total_size: number
  current_download_status: string
  index_revision: number
  completed_revision: number | null
  new_media_count: number | null
  candidate_ids: number[]
  keywords: InboxKeyword[]
  ignored_at: string | null
  ignored_reason: string | null
  last_download_error?: string | null
  channel_error?: string | null
}

export interface InboxResponse {
  items: InboxItem[]
  total: number
  page: number
  page_size: number
  counts: { candidates: number; ignored: number }
}

export interface TaskRow {
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
  remote_created_at: string | null
  remote_updated_at: string | null
  finished_at: string | null
  total_bytes: number
  downloaded_bytes: number
  channel_title: string | null
  duration_seconds: number | null
  download_speed_bytes: number
  package_id: number | null
  package_title: string | null
}

export interface TaskFile {
  message_id: string
  filename: string | null
  status: string | null
  total_size: number
  downloaded_size: number
  error: string | null
}

export interface TaskHistory {
  id?: number
  status?: string
  observed_at?: string | null
  total_count?: number
  success_count?: number
  failed_count?: number
  files?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export interface TaskDetail {
  task: TaskRow
  files: TaskFile[]
  failed_files: TaskFile[]
  history: TaskHistory[]
}

export interface DownloaderSummary {
  today_count: number
  today_bytes: number
  week_count: number
  week_bytes: number
  active_count: number
  week_failed_files: number
}

export interface TaskFilters {
  status?: string[]
  since?: string
  until?: string
  channel?: string
  keywordEntryId?: number
  search?: string
  page?: number
  pageSize?: number
}

export interface InboxFilters {
  view?: 'candidates' | 'ignored'
  downloadStatus?: string
  keywordEntryId?: number
  search?: string
  page?: number
  pageSize?: number
}

function queryString(entries: Array<[string, string | number | undefined | null]>) {
  const query = new URLSearchParams()
  for (const [key, value] of entries) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  }
  return query.toString()
}

export function getDownloaderStatus() {
  return api.get<DownloaderStatus>('/downloader/status')
}

export function syncDownloaderPackages() {
  return api.post<{
    packages_seen: number
    packages_updated?: number
    candidates_created: number
    candidates_dismissed?: number
  }>('/downloader/sync')
}

export function syncDownloaderTasks() {
  return api.post<{ tasks_seen: number; tasks_updated: number }>('/downloader/tasks/sync')
}

export function listInbox(params: InboxFilters = {}) {
  const query = queryString([
    ['view', params.view ?? 'candidates'],
    ['download_status', params.downloadStatus],
    ['keyword_entry_id', params.keywordEntryId],
    ['search', params.search],
    ['page', params.page ?? 1],
    ['page_size', params.pageSize ?? 50],
  ])
  return api.get<InboxResponse>(`/downloader/packages?${query}`)
}

export function ignorePackages(payload: { candidateIds?: number[]; packageIds?: number[]; reason?: string }) {
  const body: { candidate_ids?: number[]; package_ids?: number[]; reason?: string } = {}
  if (payload.candidateIds) body.candidate_ids = payload.candidateIds
  if (payload.packageIds) body.package_ids = payload.packageIds
  if (payload.reason) body.reason = payload.reason
  return api.post<{ ignored: number }>('/downloader/packages/ignore', body)
}

export function ignoreChannel(channelTitle: string) {
  return api.post<{ ignored: number; package_ids: number[] }>('/downloader/packages/ignore', {
    channel_title: channelTitle,
    reason: 'channel',
  })
}

export function unignorePackages(packageIds: number[]) {
  return api.post<{ restored: number }>('/downloader/packages/unignore', { package_ids: packageIds })
}

export function submitDownloaderBatches(candidateIds: number[]) {
  return api.post<{ submitted: number; skipped: number; failed: number }>('/downloader/download-batches', {
    candidate_ids: candidateIds,
  })
}

export function listTasks(filters: TaskFilters = {}) {
  const query = queryString([
    ['status', filters.status?.join(',')],
    ['since', filters.since],
    ['until', filters.until],
    ['channel', filters.channel],
    ['keyword_entry_id', filters.keywordEntryId],
    ['search', filters.search],
    ['page', filters.page ?? 1],
    ['page_size', filters.pageSize ?? 20],
  ])
  return api.get<{ items: TaskRow[]; total: number }>(`/downloader/tasks?${query}`)
}

export function getTaskDetail(taskId: string) {
  return api.get<TaskDetail>(`/downloader/tasks/${encodeURIComponent(taskId)}/detail`)
}

export function getDownloaderSummary() {
  return api.get<DownloaderSummary>('/downloader/summary')
}

export function listDownloaderChannels() {
  return api.get<{ items: string[] }>('/downloader/channels').then((payload) => payload.items ?? [])
}

export function listDownloaderKeywords() {
  return api
    .get<{ entries: Array<{ id: number; canonical_name: string }> }>('/keywords?keyword_type=whitelist&status=active&limit=5000')
    .then((payload) => payload.entries ?? [])
}

export function retryDownloaderTask(taskId: string, options: { onlyFailed?: boolean } = {}) {
  return api.post(`/downloader/tasks/${encodeURIComponent(taskId)}/retry`, {
    only_failed: options.onlyFailed ?? false,
  })
}

export function controlDownloader(state: 'pause' | 'resume') {
  return api.post('/downloader/control', { state })
}

export function cancelDownloaderTask(taskId: string) {
  return api.post(`/downloader/tasks/${encodeURIComponent(taskId)}/cancel`)
}
