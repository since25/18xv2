import { api } from './client'

export type ReviewBucket = 'whitelist' | 'blacklist'
export type ReviewStatus = 'pending' | 'approved' | 'dismissed'

export interface ReviewKeywordCandidate {
  keyword: string
  count: number
  source: string
  examples: string[]
  match_status: string
  matched_entry_id: number | null
  matched_canonical_name: string | null
  matched_keyword_type: string | null
  similar_score: number | null
}

export interface ReviewIntakeItem {
  id: number
  bucket: ReviewBucket
  raw_path: string
  normalized_path: string
  path_hash: string
  source: string
  note: string | null
  keyword_candidates: ReviewKeywordCandidate[]
  status: ReviewStatus
  approved_keyword_entry_id: number | null
  approved_keyword: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

export interface ReviewIntakeListResponse {
  items: ReviewIntakeItem[]
  total: number
  page: number
  page_size: number
}

export interface ReviewIntakeSummary {
  whitelist_pending: number
  blacklist_pending: number
  whitelist_approved: number
  blacklist_approved: number
  whitelist_dismissed: number
  blacklist_dismissed: number
}

export interface ReviewIntakeCreatePayload {
  bucket: ReviewBucket
  raw_path: string
  source?: string
  note?: string | null
}

export interface ReviewIntakeListParams {
  bucket?: ReviewBucket
  status?: ReviewStatus | ''
  search?: string
  page?: number
  page_size?: number
}

function query(params: ReviewIntakeListParams = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') q.set(key, String(value))
  })
  const qs = q.toString()
  return qs ? `?${qs}` : ''
}

export function createReviewIntakeItem(payload: ReviewIntakeCreatePayload) {
  return api.post<ReviewIntakeItem>('/review-intake/items', {
    source: 'manual_web',
    ...payload,
  })
}

export function listReviewIntakeItems(params: ReviewIntakeListParams) {
  return api.get<ReviewIntakeListResponse>(`/review-intake/items${query(params)}`)
}

export function getReviewIntakeSummary() {
  return api.get<ReviewIntakeSummary>('/review-intake/summary')
}

export function approveReviewIntakeItem(id: number, keyword: string, note?: string | null) {
  return api.post<ReviewIntakeItem>(`/review-intake/items/${id}/approve`, {
    keyword,
    note: note ?? null,
  })
}

export function dismissReviewIntakeItem(id: number, note?: string | null) {
  return api.post<ReviewIntakeItem>(`/review-intake/items/${id}/dismiss`, {
    note: note ?? null,
  })
}

export function restoreReviewIntakeItem(id: number) {
  return api.post<ReviewIntakeItem>(`/review-intake/items/${id}/restore`)
}

export function deleteReviewIntakeItem(id: number) {
  return api.delete<{ ok: boolean }>(`/review-intake/items/${id}`)
}

// 把噪声片段写进「忽略」类关键词库，之后提取时会被过滤掉。
// 复用现有的关键词创建接口，不新增后端端点。
export function createIgnoreKeyword(word: string) {
  return api.post<{ id: number }>('/keywords', {
    canonical_name: word,
    keyword_type: 'ignore',
  })
}
