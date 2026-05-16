// ── 导入批次 ────────────────────────────────────────────────
export interface TreeImport {
  id: number
  source_filename: string
  imported_at: string
  status: string
  note: string | null
  source_type: string
}
export interface ImportListResponse {
  total: number
  items: TreeImport[]
}
export interface RemoteFetchRequest {
  cid: string
  path_label?: string
  depth_limit?: number
  folders_only?: boolean
}
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
export interface KeywordAlias {
  id: number
  alias: string
  alias_normalized: string
  source: string
  note: string | null
  created_at: string | null
}
export interface KeywordEntry {
  id: number
  canonical_name: string
  canonical_name_normalized: string
  keyword_type: 'whitelist' | 'blacklist' | 'ignore' | 'tag'
  status: string
  note: string | null
  aliases: KeywordAlias[]
  created_at: string | null
  updated_at: string | null
}
export interface KeywordEntryListResponse {
  total: number
  entries: KeywordEntry[]
}
export interface KeywordEntryCreatePayload {
  canonical_name: string
  keyword_type: KeywordEntry['keyword_type']
  aliases: string[]
  note?: string | null
}
export interface KeywordEntryUpdatePayload {
  canonical_name?: string
  keyword_type?: KeywordEntry['keyword_type']
  status?: string
  note?: string | null
}
export interface KeywordEntryBatchImportPayload {
  keywords: string[]
  keyword_type: KeywordEntry['keyword_type']
  import_id: number | null
  pattern?: string | null
  flags?: string | null
  source: string
  note?: string | null
  examples_by_keyword: Record<string, string[]>
  source_folder_name_by_keyword: Record<string, string>
}
export interface KeywordEntryBatchImportResponse {
  created_count: number
  existing_count: number
  entries: KeywordEntry[]
}
export interface KeywordMergePayload {
  canonical_entry_id: number
  merge_entry_ids: number[]
  note?: string | null
}
export interface KeywordOperationLog {
  id: number
  action: string
  keyword_entry_id: number | null
  related_keyword_entry_id: number | null
  detail: string | null
  created_at: string | null
}
export interface SimilarKeywordSuggestion {
  keyword: string
  matched_entry_id: number
  matched_canonical_name: string
  score: number
}
export interface SimilarKeywordPreviewResponse {
  total: number
  suggestions: SimilarKeywordSuggestion[]
}
export interface KeywordHit {
  id: number
  raw_keyword: string
  normalized_keyword: string
  keyword_entry_id: number | null
  canonical_name_snapshot: string | null
  source_path: string
  source_folder_name: string
  import_id: number | null
  match_rule: string | null
  match_source: string
  created_at: string | null
}

// ── 关键词命中 ───────────────────────────────────────────────
export interface KeywordHitRebuildResponse {
  import_id: number
  deleted_count: number
  created_count: number
  scanned_folder_count: number
  scanned_file_count: number
  matched_keyword_count: number
}
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
export interface KeywordDuplicatePair {
  keyword_1: KeywordEntry
  keyword_2: KeywordEntry
  score: number
}
export interface KeywordDuplicateScanResponse {
  pairs: KeywordDuplicatePair[]
}
export interface ExtractedKeyword {
  keyword: string
  count: number
  source: string
  examples: string[]
  match_status: string
  matched_entry_id: number | null
  matched_canonical_name: string | null
  similar_score: number | null
}
export interface ExtractedKeywordListResponse {
  import_id: number | null
  total_nodes: number
  total_keywords: number
  total_actionable_keywords: number
  total_existing_keywords: number
  total_ignored_keywords: number
  total_blacklisted_keywords: number
  total_similar_keywords: number
  keywords: ExtractedKeyword[]
}
export interface RegexMatchPreviewItem {
  node_id: number
  folder_name: string
  raw_path: string
  extracted_keyword: string
  match_status: string
  matched_entry_id: number | null
  matched_canonical_name: string | null
  similar_score: number | null
}
export interface RegexExtractPreviewResponse {
  import_id: number | null
  pattern: string
  flags: string
  total_nodes: number
  total_matches: number
  total_actionable_matches: number
  preview: RegexMatchPreviewItem[]
}
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
export interface AuthMeResponse {
  username: string
}

export interface LoginResponse {
  success: boolean
  username: string
}

// ── 磁力下载 ─────────────────────────────────────────────────
export interface MagnetArticleCandidate {
  source_tid: number
  source_title: string
  source_magnet: string
  source_detail_url: string | null
  source_section: string | null
  source_category: string | null
  source_sub_type: string | null
  source_size: number | null
  matched_keyword: string | null
  matched_alias: string | null
  match_score: number
}
export interface MagnetArticleSearchResponse {
  query: string
  keyword_entry_id: number | null
  total_candidates: number
  candidates: MagnetArticleCandidate[]
}
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
export interface MagnetTask {
  id: number
  batch_id: string | null
  keyword_entry_id: number | null
  source_tid: number
  source_title: string
  source_magnet: string
  source_detail_url: string | null
  source_section: string | null
  matched_keyword: string | null
  matched_alias: string | null
  match_score: string | null
  duplicate_status: string
  duplicate_detail: string | null
  status: string
  target_cid: string | null
  task_id_115: string | null
  submitted_to_115_at: string | null
  failure_reason: string | null
  operation_log: string | null
  created_at: string
  updated_at: string
}
export interface MagnetTaskBatchResponse {
  created_count: number
  submitted_count: number
  duplicate_skipped_count: number
  tasks: MagnetTask[]
}
export interface MagnetTaskBatchSummary {
  batch_id: string
  created_at: string
  total_count: number
  submitted_count: number
  duplicate_skipped_count: number
  failed_count: number
  pending_count: number
  items: MagnetTask[]
}
export interface MagnetTaskBatchSummaryListResponse {
  total: number
  batches: MagnetTaskBatchSummary[]
}
export interface WhitelistBatchCandidate {
  source_tid: number
  source_title: string
  source_magnet: string
  source_detail_url: string | null
  source_section: string | null
  matched_keyword: string | null
  matched_alias: string | null
  match_score: number
  keyword_entry_id: number | null
  duplicate_status: string
  duplicate_reason: string | null
  matched_import_id: number | null
  matched_import_label: string | null
  target_path: string
}
export interface WhitelistBatchPreviewResponse {
  scanned_keyword_count: number
  total_candidates: number
  selected_candidates: number
  candidates: WhitelistBatchCandidate[]
}
export interface WhitelistBatchSubmitResponse {
  scanned_keyword_count: number
  total_candidates: number
  selected_candidates: number
  created_count: number
  submitted_count: number
  duplicate_skipped_count: number
  failed_count: number
  tasks: MagnetTask[]
}

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
export interface QrLoginSession {
  session_id: string
  app: string
  file_name: string
  uid: string
  status: number
  message: string
  qr_content: string
  qr_image_url: string
  saved_path: string | null
  cookies: string | null
  error: string | null
  created_at: string
  updated_at: string
}

// ── 整理任务 ─────────────────────────────────────────────────
export interface OrganizeTask {
  id: number
  import_id: number | null
  node_id: number | null
  keyword_entry_id: number | null
  source_path: string
  target_path: string
  matched_canonical_name: string | null
  status: string
  failure_reason: string | null
  operation_log: string | null
  executed_at: string | null
  created_at: string
  updated_at: string
}
export interface TaskBatchResponse {
  import_id: number
  keyword_entry_id: number | null
  deleted_count: number
  created_count: number
  skipped_ambiguous_count: number
  tasks: OrganizeTask[]
}
export interface DupConflictGroup {
  target_path: string
  tasks: OrganizeTask[]
}
export interface DupConflictListResponse {
  import_id: number
  conflict_count: number
  groups: DupConflictGroup[]
}
export interface AmbiguousConflictImportResponse {
  import_id: number
  created_count: number
  replaced_count: number
  skipped_count: number
  errors: string[]
  tasks: OrganizeTask[]
}

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
export interface PlanSummary {
  id: number
  strategy_version: string
  scope_desc: string
  status: string
  dry_run: boolean
  created_at: string
  item_count: number
  latest_job_id: number | null
  latest_job_status: string | null
  latest_job_dry_run: boolean | null
}
export interface PlanDetail {
  id: number
  strategy_version: string
  scope_desc: string
  status: string
  dry_run: boolean
  created_at: string
  items: PlanItem[]
}
export interface PlanSummaryPage {
  total: number
  items: PlanSummary[]
}
export interface PlanBatchResponse {
  total: number
  plans: PlanDetail[]
}
export interface BatchPlanOperationLog {
  id: number
  action: string
  requested_count: number
  processed_count: number
  requested_plan_ids: number[]
  processed_plan_ids: number[]
  skipped_plan_ids: number[]
  errors: string[]
  requested_by: string | null
  operator_note: string | null
  created_at: string
}
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

export interface OpenAuthSession {
  session_id: string
  uid: string
  status: number
  message: string
  qrcode: string
  qr_image_url: string
  error: string | null
  created_at: string
  updated_at: string
}

export interface OpenAuthRecord {
  created_at: string
  token_expires_at: string | null
}

export interface OpenAuthRecordsResponse {
  records: OpenAuthRecord[]
}

// ── 歧义冲突解决 ─────────────────────────────────────────────
// 歧义冲突中的关键词候选项（含 ID 和展示名称）
export interface AmbiguousKeywordOption {
  id: number
  name: string
}

// 单条歧义冲突记录（一个源路径对应多个关键词候选）
export interface AmbiguousConflictItem {
  source_path: string
  keyword_options: AmbiguousKeywordOption[]
}

// 歧义冲突列表接口响应
export interface AmbiguousConflictListResponse {
  import_id: number
  conflict_count: number
  items: AmbiguousConflictItem[]
}

// 单条歧义冲突解决项（用户选择将某路径映射到哪个关键词）
export interface AmbiguousResolveItem {
  source_path: string
  keyword_entry_id: number
}

// 批量提交歧义冲突解决方案的请求体
export interface AmbiguousResolveRequest {
  import_id: number
  resolutions: AmbiguousResolveItem[]
  replace_existing?: boolean
}

// 歧义冲突解决接口的响应
export interface AmbiguousResolveResponse {
  import_id: number
  created_count: number
  replaced_count: number
  skipped_count: number
  errors: string[]
}

// ── 节点详情（重复冲突懒加载第一层）────────────────────────────
// 单个节点的详情（包含原始名称、路径和 115 文件夹 ID）
export interface NodeDetailItem {
  raw_name: string
  raw_path: string
  cid: string | null
}

// 节点详情批量查询响应（key 为节点 ID）
export interface NodeDetailResponse {
  details: Record<number, NodeDetailItem>
}

// ── 115 文件元信息（重复冲突懒加载第二层）───────────────────────
// 单个文件的元信息（大小、修改时间、错误信息）
export interface FileInfoItem {
  size: number | null
  modified_at: string | null
  error: string | null
}

// 文件元信息批量查询响应（key 为 cid）
export interface FileInfoResponse {
  results: Record<string, FileInfoItem>
}

// ── 重复目标冲突解决 ──────────────────────────────────────────
// 单条重复冲突的解决方案（保留哪个任务、跳过哪些任务）
export interface DuplicateResolution {
  target_path: string
  keep_task_id: number
  skip_task_ids: number[]
  delete_from_115?: boolean
}

// 重复冲突批量解决接口的响应
export interface DuplicateResolveResponse {
  resolved_count: number
  deleted_from_115_count: number
  errors: string[]
}
