import { api } from './client'

// ── Types ──────────────────────────────────────────────────────────────
export interface ScanJobRequest {
  tree_import_id: number
  keyword_entry_ids?: number[]
  per_keyword_limit?: number
}

export interface SubmitJobRequest {
  candidate_ids: number[]
  force_submit?: boolean
}

export interface JobFrame {
  job_id: string
  job_type: 'scan' | 'submit'
  stage: string
  current: number
  total: number
  done: boolean
  error: string | null
  summary: Record<string, number> | null
  started_at: string
  finished_at: string | null
}

export interface ActiveJobs {
  scan: JobFrame | null
  submit: JobFrame | null
}

export interface WhitelistCandidate {
  id: number
  source_tid: number
  source_magnet: string
  source_title: string
  source_section: string | null
  source_detail_url: string | null
  matched_keyword_entry_id: number
  matched_keyword: string
  matched_alias: string | null
  match_score: number
  last_scanned_tree_import_id: number | null
  duplicate_status: string
  duplicate_reason: string | null
  matched_import_label: string | null
  target_path: string
  lifecycle_status: string
  magnet_task_id: number | null
  dismissed_at: string | null
  submitted_at: string | null
  failure_reason: string | null
  first_seen_at: string
  last_scanned_at: string
  updated_at: string
}

export interface CandidateListResponse {
  items: WhitelistCandidate[]
  total: number
  page: number
  page_size: number
}

export interface CandidateListParams {
  lifecycle_status?: string
  matched_keyword_entry_id?: number
  duplicate_status?: string
  search?: string
  page?: number
  page_size?: number
}

// ── API calls ──────────────────────────────────────────────────────────
export function startScanJob(payload: ScanJobRequest) {
  return api.post<{ job_id: string; status: string }>(
    '/whitelist-batch/scan-jobs',
    payload,
  )
}

export function startSubmitJob(payload: SubmitJobRequest) {
  return api.post<{ job_id: string; status: string }>(
    '/whitelist-batch/submit-jobs',
    payload,
  )
}

export function getActiveJobs() {
  return api.get<ActiveJobs>('/whitelist-batch/jobs/active')
}

export function listCandidates(params: CandidateListParams = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const qs = q.toString()
  return api.get<CandidateListResponse>(
    `/whitelist-batch/candidates${qs ? '?' + qs : ''}`,
  )
}

export function dismissCandidate(id: number, reason?: string) {
  return api.post<{ candidate_id: number; lifecycle_status: string }>(
    `/whitelist-batch/candidates/${id}/dismiss`,
    { reason: reason ?? null },
  )
}

export function bulkDismissCandidates(ids: number[]) {
  return api.post<{ dismissed: number; skipped: number }>(
    `/whitelist-batch/candidates/bulk-dismiss`,
    { candidate_ids: ids },
  )
}

export function restoreCandidate(id: number) {
  return api.post<{ candidate_id: number; lifecycle_status: string }>(
    `/whitelist-batch/candidates/${id}/restore`,
  )
}

export function deleteCandidate(id: number) {
  return api.delete<{ ok: boolean }>(`/whitelist-batch/candidates/${id}`)
}

// SSE 订阅辅助：返回 unsubscribe 函数
// onDone 接收最终帧；调用方据 finalFrame.error 区分成功/失败
export function subscribeJobProgress(
  jobId: string,
  onFrame: (frame: JobFrame | { error: string }) => void,
  onDone?: (finalFrame: JobFrame) => void,
): () => void {
  const es = new EventSource(`/api/whitelist-batch/jobs/${jobId}/progress`)
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    onFrame(data)
    if (data.done) {
      es.close()
      onDone?.(data as JobFrame)
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}
