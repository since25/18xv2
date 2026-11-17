import { api } from './client'
import type { components } from './schema.gen'

export type DedupeScanJobRequest = components['schemas']['DedupeScanJobRequest']

export type DedupeConfirmJobRequest = components['schemas']['DedupeConfirmJobRequest']

export type DedupeDeletePlanCreateRequest = components['schemas']['DedupeDeletePlanCreateRequest']

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

export type DedupeActiveJobs = components['schemas']['DedupeActiveJobsResponse']

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

export type DedupeCandidate = components['schemas']['DedupeCandidateResponse']

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

export type DedupeDeletePlan = components['schemas']['DedupeDeletePlanResponse']

export type DedupeDeletePlanItem = components['schemas']['DedupeDeletePlanItemResponse']

export type DedupeDeletePlanDetailResponse = components['schemas']['DedupeDeletePlanDetailResponse']

export type DedupeDeletePlanListResponse = components['schemas']['DedupeDeletePlanListResponse']

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
