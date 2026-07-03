import { api } from './client'

export interface EmbyDeletePlanItem {
  id: number
  group: string
  target_type: string
  target_path: string | null
  remote_file_id: string | null
  display_name: string
  status: string
  blocked_reason: string | null
  error_message: string | null
}

export interface EmbyDeletePlan {
  id: number
  source: string
  emby_item_id: string
  scope: string
  status: string
  summary: string
  total_items: number
  deleted_count: number
  failed_count: number
  blocked_count: number
  items: EmbyDeletePlanItem[]
}

export type EmbyDeleteScope = 'movie' | 'episode' | 'season' | 'series'

export interface EmbySnapshotActor {
  name: string
  role: string | null
  provider_ids: Record<string, string>
}

export interface EmbyMetadataCandidate {
  id: number
  target_list: string
  status: string
  emby_item_id: string
  snapshot_id: number
  created_at: string
  applied_at: string | null
  snapshot_title: string | null
  snapshot_nfo_path: string | null
  snapshot_actors: EmbySnapshotActor[]
}

export function getEmbyDeletePlan(id: number) {
  return api.get<EmbyDeletePlan>(`/emby-media-actions/delete-plans/${id}`)
}

export function confirmEmbyDeletePlan(id: number) {
  return api.post<{ plan_id: number; total: number; deleted: number; failed: number; blocked: number }>(
    `/emby-media-actions/delete-plans/${id}/confirm`,
    { confirm: true },
  )
}

export function createEmbyDeletePlanForScope(id: number, scope: EmbyDeleteScope) {
  return api.post<EmbyDeletePlan>(`/emby-media-actions/delete-plans/${id}/scope`, { scope })
}

export function getEmbyMetadataCandidate(id: number) {
  return api.get<EmbyMetadataCandidate>(`/emby-media-actions/metadata-candidates/${id}`)
}

export function applyEmbyMetadataCandidate(id: number, actors: string[], note: string | null) {
  return api.post<EmbyMetadataCandidate>(`/emby-media-actions/metadata-candidates/${id}/apply`, { actors, note })
}
