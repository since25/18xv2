import { api } from './client'

export interface DedupeScanJobRequest {
  tree_import_id: number
  scope_path_prefix?: string | null
  included_extensions?: string[]
  candidate_threshold?: number
  high_confidence_threshold?: number
  noise_words?: string[]
  regex_patterns?: string[]
}

export interface DedupeConfirmJobRequest {
  candidate_ids: number[]
}

export interface DedupeDeletePlanCreateRequest {
  name: string
  candidate_ids: number[]
  rate_limit_seconds?: number
}

export interface DedupeDeletePlanExecuteRequest {
  confirm: boolean
}

export interface DedupeJobFrame {
  job_id: string
  job_type: 'scan' | 'confirm' | 'delete'
  stage: string
  current: number
  total: number
  done: boolean
  error: string | null
  summary: Record<string, unknown> | null
  started_at: string
  finished_at: string | null
}

export interface DedupeActiveJobs {
  scan: DedupeJobFrame | null
  confirm: DedupeJobFrame | null
  delete: DedupeJobFrame | null
}

export interface DedupeGroup {
  id: number
  scan_run_id: number
  tree_import_id: number
  representative_name: string
  normalized_name: string
  score_max: number
  confidence_level: string
  status: string
  review_note: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DedupeCandidate {
  id: number
  group_id: number
  node_file_id: number
  raw_name: string
  raw_path: string
  file_ext: string | null
  normalized_name: string
  similarity_score: number
  suggested_action: string
  suggested_reason: string | null
  user_action: string
  user_reason: string | null
}

export interface DedupeGroupListResponse {
  items: DedupeGroup[]
  total: number
  page: number
  page_size: number
}

export interface DedupeGroupDetailResponse {
  group: DedupeGroup
  candidates: DedupeCandidate[]
}

export interface DedupeDeletePlan {
  id: number
  name: string
  source_scan_run_id: number | null
  tree_import_id: number
  status: string
  rate_limit_seconds: number
  total_items: number
  deleted_count: number
  failed_count: number
  skipped_count: number
  created_at: string | null
  confirmed_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface DedupeDeletePlanItem {
  id: number
  plan_id: number
  candidate_id: number
  node_file_id: number
  remote_file_id: string
  raw_path: string
  remote_path: string | null
  confirmation_level: string
  delete_reason: string
  status: string
  error_message: string | null
  deleted_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface DedupeDeletePlanDetailResponse {
  plan: DedupeDeletePlan
  items: DedupeDeletePlanItem[]
}

export interface DedupeDeletePlanListResponse {
  items: DedupeDeletePlan[]
  total: number
}

export interface DedupeGroupListParams {
  status?: string
  confidence_level?: string
  page?: number
  page_size?: number
}

export function startDedupeScanJob(payload: DedupeScanJobRequest) {
  return api.post<{ job_id: string; status: string }>('/dedupe/scan-jobs', payload)
}

export function startDedupeConfirmJob(payload: DedupeConfirmJobRequest) {
  return api.post<{ job_id: string; status: string }>('/dedupe/confirm-jobs', payload)
}

export function startDedupeDeleteJob(planId: number, payload: DedupeDeletePlanExecuteRequest) {
  return api.post<{ job_id: string; status: string }>(`/dedupe/delete-plans/${planId}/execute-jobs`, payload)
}

export function getDedupeActiveJobs() {
  return api.get<DedupeActiveJobs>('/dedupe/jobs/active')
}

export function listDedupeGroups(params: DedupeGroupListParams = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') q.set(key, String(value))
  })
  const qs = q.toString()
  return api.get<DedupeGroupListResponse>(`/dedupe/groups${qs ? '?' + qs : ''}`)
}

export function getDedupeGroup(id: number) {
  return api.get<DedupeGroupDetailResponse>(`/dedupe/groups/${id}`)
}

export function reviewDedupeGroup(
  id: number,
  payload: { keep_candidate_ids: number[]; delete_candidate_ids: number[]; note?: string | null },
) {
  return api.post<{ group_id: number; status: string }>(`/dedupe/groups/${id}/review`, payload)
}

export function createDedupeDeletePlan(payload: DedupeDeletePlanCreateRequest) {
  return api.post<{ plan_id: number; status: string; total_items: number }>('/dedupe/delete-plans', payload)
}

export function listDedupeDeletePlans() {
  return api.get<DedupeDeletePlanListResponse>('/dedupe/delete-plans')
}

export function getDedupeDeletePlan(id: number) {
  return api.get<DedupeDeletePlanDetailResponse>(`/dedupe/delete-plans/${id}`)
}

export function subscribeDedupeJob(
  jobId: string,
  onFrame: (frame: DedupeJobFrame | { error: string }) => void,
  onDone?: (frame: DedupeJobFrame) => void,
) {
  const es = new EventSource(`/api/dedupe/jobs/${jobId}/progress`)
  es.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onFrame(data)
    if (data.done) {
      es.close()
      onDone?.(data as DedupeJobFrame)
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}
