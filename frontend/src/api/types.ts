import type { components } from './schema.gen'

// ── 导入批次 ────────────────────────────────────────────────
export interface TreeImport {
  id: number
  source_filename: string
  imported_at: string
  status: string
  note: string | null
  source_type: string
}
export type ImportListResponse = components['schemas']['TreeImportPageResponse']
export type RemoteFetchRequest = components['schemas']['RemoteFetchRequest']
export interface TreeImportEntry {
  id: number
  entry_type: 'folder' | 'file'
  raw_name: string
  normalized_name: string
  raw_path: string
  parent_path: string | null
  depth: number
  remote_id: string | null
}
export interface TreeImportEntryListResponse {
  total: number
  items: TreeImportEntry[]
}

// ── 关键词 ───────────────────────────────────────────────────
export type KeywordAlias = components['schemas']['KeywordAliasResponse']
export type KeywordMergePolicy = 'normal' | 'fallback_only'
export type KeywordEntry = components['schemas']['KeywordEntryResponse']
export type KeywordEntryListResponse = components['schemas']['KeywordEntryListResponse']
export interface KeywordEntryCreatePayload {
  canonical_name: string
  keyword_type: KeywordEntry['keyword_type']
  merge_policy: KeywordMergePolicy
  aliases: string[]
  note?: string | null
}
export interface KeywordEntryUpdatePayload {
  canonical_name?: string
  keyword_type?: KeywordEntry['keyword_type']
  merge_policy?: KeywordMergePolicy
  status?: string
  note?: string | null
}
export interface KeywordEntryBatchImportPayload {
  keywords: string[]
  keyword_type: KeywordEntry['keyword_type']
  merge_policy: KeywordMergePolicy
  import_id: number | null
  pattern?: string | null
  flags?: string | null
  source: string
  note?: string | null
  examples_by_keyword: Record<string, string[]>
  source_folder_name_by_keyword: Record<string, string>
}
export type KeywordEntryBatchImportResponse = components['schemas']['KeywordEntryBatchImportResponse']
export type KeywordMergePayload = components['schemas']['KeywordEntryMergeRequest']
export type KeywordOperationLog = components['schemas']['KeywordOperationLogResponse']
export type SimilarKeywordSuggestion = components['schemas']['SimilarKeywordSuggestionResponse']
export type SimilarKeywordPreviewResponse = components['schemas']['SimilarKeywordPreviewResponse']
export type KeywordHit = components['schemas']['KeywordHitResponse']

// ── 关键词命中 ───────────────────────────────────────────────
export type KeywordHitRebuildResponse = components['schemas']['KeywordHitRebuildResponse']
export interface TreeHitSummaryItem {
  keyword_entry_id: number
  canonical_name: string
  keyword_type: string
  status: string
  hit_count: number
  sample_paths: string[]
}
export interface TreeHitSummaryResponse {
  total: number
  items: TreeHitSummaryItem[]
}
export type KeywordDuplicatePair = components['schemas']['KeywordDuplicatePairResponse']
export type KeywordDuplicateScanResponse = components['schemas']['KeywordDuplicateScanResponse']
export type ExtractedKeyword = components['schemas']['ExtractedKeywordResponse']
export type ExtractedKeywordListResponse = components['schemas']['ExtractedKeywordListResponse']
export type RegexMatchPreviewItem = components['schemas']['RegexMatchPreviewResponse']
export type RegexExtractPreviewResponse = components['schemas']['RegexExtractPreviewResponse']
export interface ManualPathRegexExtractPayload {
  import_id?: number | null
  raw_path: string
  pattern: string
  flags: string
  group_index: number
  limit: number
}
export interface DeleteResponse {
  deleted: boolean
}

// ── 认证 ─────────────────────────────────────────────────────
export type AuthMeResponse = components['schemas']['MeResponse']

export type LoginResponse = components['schemas']['LoginResponse']

// ── 磁力下载 ─────────────────────────────────────────────────
export type MagnetArticleCandidate = components['schemas']['ArticleCandidateResponse']
export type MagnetArticleSearchResponse = components['schemas']['ArticleSearchResponse']
export interface MagnetDuplicateCheckItem {
  source_tid: number
  duplicate_status: string
  duplicate_reason: string | null
  search_terms: string[]
  matched_terms: string[]
  matched_import_id: number | null
  matched_import_label: string | null
  matched_nodes: Array<{
    id: string
    name: string
    path: string
    parent_id: string | null
    is_file: boolean
  }>
}
export interface MagnetDuplicateCheckResponse {
  items: MagnetDuplicateCheckItem[]
}
export type MagnetTask = components['schemas']['MagnetTaskResponse']
export type MagnetTaskBatchResponse = components['schemas']['MagnetTaskBatchResponse']
export type MagnetTaskBatchSummary = components['schemas']['MagnetTaskBatchSummaryResponse']
export type MagnetTaskBatchSummaryListResponse = components['schemas']['MagnetTaskBatchSummaryListResponse']
// ── 授权 / QR 登录 ────────────────────────────────────────────
export interface QrLoginClientOption {
  app: string
  label: string
}
export interface QrLoginClientsResponse {
  clients: QrLoginClientOption[]
}
export interface QrLoginRecord {
  app: string
  file_name: string
  saved_path: string
  uid: string
  created_at: string
  updated_at: string
}
export interface QrLoginRecordsResponse {
  records: QrLoginRecord[]
}
export type QrLoginSession = components['schemas']['SessionResponse']

// ── 整理任务 ─────────────────────────────────────────────────
export type OrganizeTask = components['schemas']['OrganizeTaskResponse']
export type TaskBatchResponse = components['schemas']['OrganizeTaskBatchResponse']
export type DupConflictGroup = components['schemas']['DuplicateTargetConflictGroup']
export type DupConflictListResponse = components['schemas']['DuplicateTargetConflictListResponse']
export type AmbiguousConflictImportResponse = components['schemas']['AmbiguousConflictResolutionImportResponse']

// ── 整理计划 ─────────────────────────────────────────────────
export interface PlanItem {
  id: number
  node_id: number | null
  source_path: string
  suggested_target_path: string
  action_type: string
  confidence: number
  conflict_status: string
  reason: string | null
}
export type PlanSummary = components['schemas']['PlanSummaryResponse']
export interface PlanDetail {
  id: number
  strategy_version: string
  scope_desc: string
  status: string
  dry_run: boolean
  created_at: string
  items: PlanItem[]
}
export type PlanSummaryPage = components['schemas']['PlanSummaryPageResponse']
export interface PlanBatchResponse {
  total: number
  plans: PlanDetail[]
}
export type BatchPlanOperationLog = components['schemas']['BatchPlanOperationLogResponse']
export interface BatchPlanOperationResponse {
  requested_count: number
  processed_count: number
  jobs: JobDetail[]
  deleted_plan_ids: number[]
  skipped_plan_ids: number[]
  errors: string[]
}

// ── 执行任务 ─────────────────────────────────────────────────
export interface ExecutionLog {
  id: number
  node_id: number | null
  action_type: string
  before_path: string
  after_path: string
  api_status: string
  success: boolean
  error_message: string | null
  raw_response: string | null
  created_at: string | null
}
export interface JobDetail {
  id: number
  plan_id: number
  dry_run: boolean
  status: string
  rollback_status: string
  requested_by: string | null
  operator_note: string | null
  started_at: string | null
  finished_at: string | null
  logs: ExecutionLog[]
}

// ── 系统 ─────────────────────────────────────────────────────
export interface HealthzResponse {
  status: string
  service_status?: string
  auth_mode?: string
  authorization_status?: string
  client_115: boolean
  client_115_error: string | null
}
export interface CookieStatusItem {
  app: string
  app_description: string
  file_name: string
  saved_path: string
  uid: string
  status: 'ok' | 'error'
  user_name: string | null
  error: string | null
}
export interface SystemStatusResponse {
  token_status: 'ok' | 'error' | 'cooldown' | 'reauth_required' | 'missing'
  token_error: string | null
  token_error_at: string | null
  token_expires_at: string | null
  cookies: CookieStatusItem[]
}

export type OpenAuthSession = components['schemas']['OpenAuthSessionResponse']

export interface OpenAuthRecord {
  created_at: string
  token_expires_at: string | null
}

export interface OpenAuthRecordsResponse {
  records: OpenAuthRecord[]
}

// ── 歧义冲突解决 ─────────────────────────────────────────────
// 歧义冲突中的关键词候选项（含 ID 和展示名称）
export type AmbiguousKeywordOption = components['schemas']['AmbiguousKeywordOption']

// 单条歧义冲突记录（一个源路径对应多个关键词候选）
export type AmbiguousConflictItem = components['schemas']['AmbiguousConflictItem']

// 歧义冲突列表接口响应
export type AmbiguousConflictListResponse = components['schemas']['AmbiguousConflictListResponse']

// 单条歧义冲突解决项（用户选择将某路径映射到哪个关键词）
export type AmbiguousResolveItem = components['schemas']['AmbiguousResolveItem']

// 批量提交歧义冲突解决方案的请求体
export type AmbiguousResolveRequest = components['schemas']['AmbiguousResolveRequest']

// 歧义冲突解决接口的响应
export type AmbiguousResolveResponse = components['schemas']['AmbiguousResolveResponse']

// ── 节点详情（重复冲突懒加载第一层）────────────────────────────
// 单个节点的详情（包含原始名称、路径和 115 文件夹 ID）
export type NodeDetailItem = components['schemas']['NodeDetailItem']

// 节点详情批量查询响应（key 为节点 ID）
export type NodeDetailResponse = components['schemas']['NodeDetailResponse']

// ── 115 文件元信息（重复冲突懒加载第二层）───────────────────────
// 单个文件的元信息（大小、修改时间、错误信息）
export type FileInfoItem = components['schemas']['FileInfoItem']

// 文件元信息批量查询响应（key 为 cid）
export type FileInfoResponse = components['schemas']['FileInfoResponse']

// ── 重复目标冲突解决 ──────────────────────────────────────────
// 单条重复冲突的解决方案（保留哪个任务、跳过哪些任务）
export type DuplicateResolution = components['schemas']['DuplicateResolution']

// 重复冲突批量解决接口的响应
export type DuplicateResolveResponse = components['schemas']['DuplicateResolveResponse']
