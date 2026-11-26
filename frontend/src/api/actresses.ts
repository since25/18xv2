import { api } from './client'
import type { components } from './schema.gen'

type Schemas = components['schemas']

export type ActressStatus = Schemas['ActressSummary']['status']
export type ActressSummary = Schemas['ActressSummary']
export type ActressListResponse = Schemas['ActressListResponse']
export type ActressDetail = Schemas['ActressDetail']
export type ActressAliasItem = Schemas['ActressAliasItem']
export type ActressFilmItem = Schemas['ActressFilmItem']
export type ActressFilmActor = Schemas['ActressFilmActor']
export type ActressMarkItem = Schemas['ActressMarkItem']
export type ActressStatusRequest = Schemas['ActressStatusRequest']
export type ActressStatusResponse = Schemas['ActressStatusResponse']
export type ActressCandidateItem = Schemas['ActressCandidateItem']
export type ActressCandidateListResponse = Schemas['ActressCandidateListResponse']
export type ActressCountResponse = Schemas['ActressCountResponse']
export type ActressKeptItem = Schemas['ActressKeptItem']
export type ActressKeptListResponse = Schemas['ActressKeptListResponse']
export type ActressDeleteBatchSummary = Schemas['ActressDeleteBatchSummary']
export type ActressDeleteBatchListResponse = Schemas['ActressDeleteBatchListResponse']
export type ActressDeleteBatchDetail = Schemas['ActressDeleteBatchDetail']
export type ActressDeleteBatchFilmItem = Schemas['ActressDeleteBatchFilmItem']
export type ActressDeleteBatchFileItem = Schemas['ActressDeleteBatchFileItem']
export type ActressDeleteBatchStartResponse = Schemas['ActressDeleteBatchStartResponse']

export type ActressSort = 'film_count' | 'name'

export interface ActressListParams {
  status?: ActressStatus
  q?: string
  sort?: ActressSort
  page?: number
  page_size?: number
}

// ---------- 女优档案 ----------

export function listActresses(params: ActressListParams = {}) {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.q) query.set('q', params.q)
  if (params.sort) query.set('sort', params.sort)
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))
  const suffix = query.toString()
  return api.get<ActressListResponse>(suffix ? `/actresses?${suffix}` : '/actresses')
}

export function getActress(id: number) {
  return api.get<ActressDetail>(`/actresses/${id}`)
}

/** 批量改状态；返回状态有变化的人数和删除草稿增减的部数 */
export function setActressStatus(body: ActressStatusRequest) {
  return api.post<ActressStatusResponse>('/actresses/status', body)
}

export function addActressAlias(id: number, alias: string) {
  return api.post<ActressDetail>(`/actresses/${id}/aliases`, { alias })
}

export function removeActressAlias(id: number, aliasId: number) {
  return api.delete<ActressDetail>(`/actresses/${id}/aliases/${aliasId}`)
}

/** 把 id 这位合并进 intoId，返回合并后（intoId）的详情 */
export function mergeActress(id: number, intoId: number) {
  return api.post<ActressDetail>(`/actresses/${id}/merge`, { into_id: intoId })
}

/** 头像地址（给 <img src> 用）；前缀与 client.ts 的 /api 一致，取不到时后端返回 404 */
export function actressImageUrl(id: number) {
  return `/api/actresses/${id}/image`
}

// ---------- 待删清单与保留名单 ----------

export function listCandidates() {
  return api.get<ActressCandidateListResponse>('/actresses/candidates')
}

export function selectCandidates(filmDirs: string[], selected: boolean) {
  return api.post<ActressCountResponse>('/actresses/candidates/select', { film_dirs: filmDirs, selected })
}

export function keepCandidates(filmDirs: string[]) {
  return api.post<ActressCountResponse>('/actresses/candidates/keep', { film_dirs: filmDirs })
}

/** 只读检查这些片子在 115 上是否还在；后端一次最多 50 部 */
export function checkCandidatesRemote(filmDirs: string[]) {
  return api.post<ActressCountResponse>('/actresses/candidates/check-remote', { film_dirs: filmDirs })
}

export function listKept() {
  return api.get<ActressKeptListResponse>('/actresses/kept')
}

export function removeKept(filmDirs: string[]) {
  return api.post<ActressCountResponse>('/actresses/kept/remove', { film_dirs: filmDirs })
}

// ---------- 删除批次 ----------

/** 只删页面上勾选确认的这些片子；清单已变化时后端返回 409「清单有变化，请刷新后再确认」 */
export function createDeleteBatch(filmDirs: string[]) {
  return api.post<ActressDeleteBatchStartResponse>('/actresses/delete-batches', { film_dirs: filmDirs })
}

export function listDeleteBatches() {
  return api.get<ActressDeleteBatchListResponse>('/actresses/delete-batches')
}

export function getDeleteBatch(id: number) {
  return api.get<ActressDeleteBatchDetail>(`/actresses/delete-batches/${id}`)
}

export function resumeDeleteBatch(id: number) {
  return api.post<ActressDeleteBatchStartResponse>(`/actresses/delete-batches/${id}/resume`)
}
