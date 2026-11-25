// 本文件由 scripts/export_openapi.py 根据后端接口定义自动生成，请勿手工修改。
// 后端接口或数据模型变化后，运行 scripts/gen-api-types.sh 重新生成。

export interface components {
  schemas: {
    'ActiveJobsResponse': {
      scan: components['schemas']['JobFrame'] | null
      submit: components['schemas']['JobFrame'] | null
    }
    'AmbiguousConflictItem': {
      source_path: string
      keyword_options: components['schemas']['AmbiguousKeywordOption'][]
    }
    'AmbiguousConflictListResponse': {
      import_id: number
      conflict_count: number
      items: components['schemas']['AmbiguousConflictItem'][]
    }
    'AmbiguousConflictResolutionImportResponse': {
      import_id: number
      created_count: number
      replaced_count: number
      skipped_count: number
      errors: string[]
      tasks: components['schemas']['OrganizeTaskResponse'][]
    }
    'AmbiguousKeywordOption': {
      id: number
      name: string
    }
    'AmbiguousResolveItem': {
      source_path: string
      keyword_entry_id: number
    }
    'AmbiguousResolveRequest': {
      import_id: number
      resolutions: components['schemas']['AmbiguousResolveItem'][]
      replace_existing?: boolean
    }
    'AmbiguousResolveResponse': {
      import_id: number
      created_count: number
      replaced_count: number
      skipped_count: number
      errors: string[]
    }
    'ArticleCandidateResponse': {
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
    'ArticleSearchRequest': {
      keyword_entry_id?: number | null
      query: string
      limit?: number
    }
    'ArticleSearchResponse': {
      query: string
      keyword_entry_id: number | null
      total_candidates: number
      candidates: components['schemas']['ArticleCandidateResponse'][]
    }
    'AuthCodeRequest': {
      auth_code: string
    }
    'AuthCodeResponse': {
      success: boolean
      message: string
    }
    'BatchDeletePlanRequest': {
      plan_ids: number[]
    }
    'BatchExecutePlanRequest': {
      plan_ids: number[]
      dry_run?: boolean
      confirm_real_run?: boolean
      requested_by?: string | null
      operator_note?: string | null
    }
    'BatchPlanOperationLogResponse': {
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
    'BatchPlanOperationResponse': {
      requested_count: number
      processed_count: number
      jobs: components['schemas']['JobResponse'][]
      deleted_plan_ids: number[]
      skipped_plan_ids: number[]
      errors: string[]
    }
    'Body_import_ambiguous_conflicts_tsv_organize_tasks_ambiguous_conflicts_import_tsv_post': {
      file: string
    }
    'Body_import_tree_imports_tree_post': {
      file: string
    }
    'BulkDismissRequest': {
      candidate_ids: number[]
    }
    'CandidateListResponse': {
      items: components['schemas']['CandidateResponse'][]
      total: number
      page: number
      page_size: number
    }
    'CandidateResponse': {
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
    'CreateSessionRequest': {
      app: string
      file_name: string
    }
    'DedupeActiveJobsResponse': {
      scan: components['schemas']['DedupeJobFrame'] | null
      confirm: components['schemas']['DedupeJobFrame'] | null
      delete: components['schemas']['DedupeJobFrame'] | null
    }
    'DedupeCandidateResponse': {
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
    'DedupeConfirmJobRequest': {
      candidate_ids: number[]
    }
    'DedupeDeletePlanCreateRequest': {
      name: string
      candidate_ids: number[]
      rate_limit_seconds?: number
    }
    'DedupeDeletePlanDetailResponse': {
      plan: components['schemas']['DedupeDeletePlanResponse']
      items: components['schemas']['DedupeDeletePlanItemResponse'][]
    }
    'DedupeDeletePlanExecuteRequest': {
      confirm?: boolean
    }
    'DedupeDeletePlanItemResponse': {
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
    'DedupeDeletePlanListResponse': {
      items: components['schemas']['DedupeDeletePlanResponse'][]
      total: number
    }
    'DedupeDeletePlanResponse': {
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
    'DedupeGroupDetailResponse': {
      group: components['schemas']['DedupeGroupResponse']
      candidates: components['schemas']['DedupeCandidateResponse'][]
    }
    'DedupeGroupListResponse': {
      items: components['schemas']['DedupeGroupResponse'][]
      total: number
      page: number
      page_size: number
    }
    'DedupeGroupResponse': {
      id: number
      scan_run_id: number
      tree_import_id: number
      representative_name: string
      normalized_name: string
      score_max: number
      confidence_level: string
      status: string
      review_note: string | null
      created_at: string | null
      updated_at: string | null
    }
    'DedupeJobFrame': {
      job_id: string
      job_type: "scan" | "confirm" | "delete"
      stage: string
      current: number
      total: number
      done: boolean
      error: string | null
      summary: Record<string, unknown> | null
      started_at: string
      finished_at: string | null
    }
    'DedupeReviewRequest': {
      keep_candidate_ids?: number[]
      delete_candidate_ids?: number[]
      note?: string | null
    }
    'DedupeScanJobRequest': {
      tree_import_id: number
      scope_path_prefix?: string | null
      included_extensions?: string[]
      candidate_threshold?: number
      high_confidence_threshold?: number
      noise_words?: string[]
      regex_patterns?: string[]
    }
    'DirectoryPickerRequest': {
      title?: string
      initial_path?: string | null
    }
    'DirectoryPickerResponse': {
      path: string
    }
    'DismissRequest': {
      reason?: string | null
    }
    'DownloaderControlRequest': {
      state: "pause" | "resume"
    }
    'DownloaderIgnoreRequest': {
      candidate_ids?: number[] | null
      package_ids?: number[] | null
      channel_title?: string | null
      reason?: string | null
    }
    'DownloaderKeywordQuickAddRequest': {
      keyword: string
      list_type: "whitelist" | "blacklist"
      dry_run?: boolean
    }
    'DownloaderPackageSubmitRequest': {
      package_ids: number[]
    }
    'DownloaderRetryRequest': {
      only_failed?: boolean
    }
    'DownloaderSelectRequest': {
      selected: boolean
    }
    'DownloaderSubmitRequest': {
      candidate_ids: number[]
    }
    'DownloaderTaskListResponse': {
      items: Record<string, unknown>[]
      total: number
    }
    'DownloaderUnignoreRequest': {
      package_ids: number[]
    }
    'DuplicateCheckItemRequest': {
      source_tid: number
      source_title: string
      source_magnet: string
      matched_keyword?: string | null
      matched_alias?: string | null
    }
    'DuplicateCheckItemResponse': {
      source_tid: number
      duplicate_status: string
      duplicate_reason: string | null
      search_terms: string[]
      matched_terms: string[]
      matched_import_id: number | null
      matched_import_label: string | null
      matched_nodes: components['schemas']['NodePayload'][]
    }
    'DuplicateCheckRequest': {
      items: components['schemas']['DuplicateCheckItemRequest'][]
      tree_import_id?: number | null
    }
    'DuplicateCheckResponse': {
      items: components['schemas']['DuplicateCheckItemResponse'][]
    }
    'DuplicateResolution': {
      target_path: string
      keep_task_id: number
      skip_task_ids: number[]
      delete_from_115?: boolean
    }
    'DuplicateResolveRequest': {
      resolutions: components['schemas']['DuplicateResolution'][]
    }
    'DuplicateResolveResponse': {
      resolved_count: number
      deleted_from_115_count: number
      errors: string[]
    }
    'DuplicateTargetConflictGroup': {
      target_path: string
      tasks: components['schemas']['OrganizeTaskResponse'][]
    }
    'DuplicateTargetConflictListResponse': {
      import_id: number
      conflict_count: number
      groups: components['schemas']['DuplicateTargetConflictGroup'][]
    }
    'EmbyActorPayload': {
      name: string
      role?: string | null
      provider_ids?: Record<string, string>
    }
    'EmbyDeleteConfirmRequest': {
      confirm?: boolean
    }
    'EmbyDeletePlanItemResponse': {
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
    'EmbyDeletePlanResponse': {
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
      items: components['schemas']['EmbyDeletePlanItemResponse'][]
    }
    'EmbyDeleteScopeRequest': {
      scope: "movie" | "episode" | "season" | "series"
    }
    'EmbyMediaIntakeRequest': {
      action: "delete_plan" | "metadata_blacklist" | "metadata_whitelist"
      path?: string | null
      url?: string | null
      title?: string | null
      emby_item_id?: string | null
      emby_payload?: Record<string, unknown> | null
      nfo_path?: string | null
      source?: string
      nfo_xml?: string | null
      actors?: components['schemas']['EmbyActorPayload'][]
    }
    'EmbyMediaIntakeResponse': {
      ok: boolean
      delete_plan: components['schemas']['EmbyDeletePlanResponse'] | null
      metadata_candidate: components['schemas']['EmbyMetadataCandidateResponse'] | null
    }
    'EmbyMetadataApplyRequest': {
      actors: string[]
      note?: string | null
    }
    'EmbyMetadataCandidateResponse': {
      id: number
      target_list: string
      status: string
      emby_item_id: string
      snapshot_id: number
      created_at: string
      applied_at: string | null
      snapshot_title: string | null
      snapshot_nfo_path: string | null
      snapshot_actors: components['schemas']['EmbyActorPayload'][]
    }
    'ExecutePlanRequest': {
      dry_run?: boolean
      confirm_real_run?: boolean
      requested_by?: string | null
      operator_note?: string | null
    }
    'ExecutionLogResponse': {
      id: number
      node_id: number
      action_type: string
      before_path: string
      after_path: string
      api_status: string
      success: boolean
      error_message: string | null
      raw_response: string | null
      created_at: string
    }
    'ExtractedKeywordListResponse': {
      import_id: number | null
      total_nodes: number
      total_keywords: number
      total_actionable_keywords: number
      total_existing_keywords: number
      total_ignored_keywords: number
      total_blacklisted_keywords: number
      total_similar_keywords: number
      keywords: components['schemas']['ExtractedKeywordResponse'][]
    }
    'ExtractedKeywordResponse': {
      keyword: string
      count: number
      source: string
      examples: string[]
      match_status: string
      matched_entry_id: number | null
      matched_canonical_name: string | null
      similar_score: number | null
    }
    'FileInfoItem': {
      size: number | null
      modified_at: string | null
      error: string | null
    }
    'FileInfoRequest': {
      cids: string[]
    }
    'FileInfoResponse': {
      results: Record<string, components['schemas']['FileInfoItem']>
    }
    'HTTPValidationError': {
      detail: components['schemas']['ValidationError'][]
    }
    'JellyfinConflictItem': {
      keyword_entry_id: number | null
      canonical_name_snapshot: string
      status: string
      last_error: string | null
    }
    'JellyfinConflictResponse': {
      items: components['schemas']['JellyfinConflictItem'][]
    }
    'JellyfinJobResponse': {
      job_id: string
      job_type: string
      stage: string
      current: number
      total: number
      done: boolean
      error: string | null
      summary: Record<string, unknown> | null
      started_at: string | null
      finished_at: string | null
    }
    'JellyfinStatusResponse': {
      scan_enabled: boolean
      sync_enabled: boolean
      local_roots: string[]
      strm_roots: string[]
      latest_scan: components['schemas']['JellyfinJobResponse'] | null
      latest_sync: components['schemas']['JellyfinJobResponse'] | null
      counts: Record<string, number>
      collections: Record<string, number>
    }
    'JellyfinUnmatchedItem': {
      id: number
      source: "local" | "strm_115"
      path: string
      match_state: "unmatched" | "nfo_error"
      match_note: string | null
    }
    'JellyfinUnmatchedResponse': {
      total: number
      items: components['schemas']['JellyfinUnmatchedItem'][]
    }
    'JobFrame': {
      job_id: string
      job_type: "scan" | "submit"
      stage: string
      current: number
      total: number
      done: boolean
      error: string | null
      summary: components['schemas']['ScanSummary'] | components['schemas']['SubmitSummary'] | null
      started_at: string
      finished_at: string | null
    }
    'JobResponse': {
      id: number
      plan_id: number
      dry_run: boolean
      status: string
      requested_by: string | null
      operator_note: string | null
      confirmation_validated: boolean
      rollback_status: string
      started_at: string
      finished_at: string | null
      logs: components['schemas']['ExecutionLogResponse'][]
      rollback_records: components['schemas']['RollbackRecordResponse'][]
    }
    'KeywordAliasAddRequest': {
      aliases: string[]
      source?: string
    }
    'KeywordAliasResponse': {
      created_at: string | null
      id: number
      alias: string
      alias_normalized: string
      source: string
      note: string | null
    }
    'KeywordCandidateListResponse': {
      import_id: number
      total_nodes: number
      total_candidates: number
      candidates: components['schemas']['KeywordCandidateResponse'][]
    }
    'KeywordCandidateRequest': {
      import_id: number
      node_ids?: number[] | null
      min_count?: number
      limit?: number
    }
    'KeywordCandidateResponse': {
      keyword: string
      count: number
      score: number
      bracket_hits: number
      examples: string[]
    }
    'KeywordDuplicatePairResponse': {
      keyword_1: components['schemas']['KeywordEntryResponse']
      keyword_2: components['schemas']['KeywordEntryResponse']
      score: number
      keyword_1_reference_count: number
      keyword_2_reference_count: number
    }
    'KeywordDuplicateScanRequest': {
      keyword_type?: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist" | null
      status?: string | null
      threshold?: number
    }
    'KeywordDuplicateScanResponse': {
      pairs: components['schemas']['KeywordDuplicatePairResponse'][]
    }
    'KeywordEntryBatchImportRequest': {
      keywords: string[]
      keyword_type: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist"
      merge_policy?: "normal" | "fallback_only"
      import_id?: number | null
      pattern?: string | null
      flags?: string | null
      source?: string
      note?: string | null
      examples_by_keyword?: Record<string, string[]>
      source_folder_name_by_keyword?: Record<string, string>
    }
    'KeywordEntryBatchImportResponse': {
      created_count: number
      existing_count: number
      entries: components['schemas']['KeywordEntryResponse'][]
    }
    'KeywordEntryCreateRequest': {
      canonical_name: string
      keyword_type: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist"
      merge_policy?: "normal" | "fallback_only"
      aliases?: string[]
      note?: string | null
    }
    'KeywordEntryListResponse': {
      total: number
      entries: components['schemas']['KeywordEntryResponse'][]
    }
    'KeywordEntryMergeRequest': {
      canonical_entry_id: number
      merge_entry_ids: number[]
      note?: string | null
    }
    'KeywordEntryResponse': {
      created_at: string | null
      id: number
      canonical_name: string
      canonical_name_normalized: string
      keyword_type: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist"
      status: string
      merge_policy: "normal" | "fallback_only"
      note: string | null
      updated_at: string | null
      aliases: components['schemas']['KeywordAliasResponse'][]
    }
    'KeywordEntryUpdateRequest': {
      canonical_name?: string | null
      keyword_type?: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist" | null
      merge_policy?: "normal" | "fallback_only" | null
      status?: string | null
      note?: string | null
    }
    'KeywordHitRebuildRequest': {
      import_id: number
      include_files?: boolean
      include_folders?: boolean
      replace_existing?: boolean
    }
    'KeywordHitRebuildResponse': {
      import_id: number
      deleted_count: number
      created_count: number
      scanned_folder_count: number
      scanned_file_count: number
      matched_keyword_count: number
    }
    'KeywordHitResponse': {
      created_at: string | null
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
    }
    'KeywordLibraryBatchCreateRequest': {
      keywords: string[]
      list_type: "whitelist" | "blacklist" | "ignore" | "tag"
      source?: string
      import_id?: number | null
      pattern?: string | null
      flags?: string | null
      note?: string | null
    }
    'KeywordLibraryBatchCreateResponse': {
      created_count: number
      skipped_count: number
      entries: components['schemas']['KeywordLibraryEntryResponse'][]
    }
    'KeywordLibraryEntryResponse': {
      created_at: string | null
      id: number
      keyword: string
      keyword_normalized: string
      list_type: string
      source: string
      import_id: number | null
      pattern: string | null
      flags: string | null
      note: string | null
    }
    'KeywordMovePlanGenerateRequest': {
      import_id: number
      keyword?: string | null
      keyword_entry_id?: number | null
      target_path: string
      dry_run?: boolean
      case_sensitive?: boolean
      node_ids?: number[] | null
    }
    'KeywordOperationLogResponse': {
      created_at: string | null
      id: number
      action: string
      keyword_entry_id: number | null
      related_keyword_entry_id: number | null
      detail: string | null
    }
    'KeywordTreeHitSummaryListResponse': {
      total: number
      items: components['schemas']['KeywordTreeHitSummaryResponse'][]
    }
    'KeywordTreeHitSummaryResponse': {
      keyword_entry_id: number
      canonical_name: string
      keyword_type: "whitelist" | "blacklist" | "ignore" | "tag" | "emby_blacklist" | "emby_whitelist"
      status: string
      hit_count: number
      sample_paths: string[]
    }
    'LocalCleanupDeleteItemResponse': {
      path: string
      entry_type: string
      success: boolean
      status: string
      error_message: string | null
    }
    'LocalCleanupDeleteRequest': {
      root_path: string
      paths: string[]
      dry_run?: boolean
      confirm_delete?: boolean
      remove_empty_dirs?: boolean
    }
    'LocalCleanupDeleteResponse': {
      root_path: string
      dry_run: boolean
      total_requested: number
      total_processed: number
      removed_empty_dirs: number
      items: components['schemas']['LocalCleanupDeleteItemResponse'][]
    }
    'LocalCleanupScanCandidateResponse': {
      entry_type: string
      path: string
      name: string
      size_bytes: number | null
      decision: string
      reasons: string[]
    }
    'LocalCleanupScanRequest': {
      root_path: string
      blacklist_keywords?: string[]
      fuzzy_match?: boolean
      suffix_filter?: string[]
      max_file_size_mb?: number
      include_files?: boolean
      include_directories?: boolean
      max_results?: number
    }
    'LocalCleanupScanResponse': {
      root_path: string
      total_candidates: number
      total_delete_candidates: number
      total_keep_candidates: number
      skipped_count: number
      items: components['schemas']['LocalCleanupScanCandidateResponse'][]
    }
    'LocalOrganizeCandidateResponse': {
      source_path: string
      source_name: string
      matched_keyword: string
      target_path: string
      status: string
      reasons: string[]
    }
    'LocalOrganizeDebugRequest': {
      folder_name: string
      whitelist_keywords?: string[]
      fuzzy_match?: boolean
    }
    'LocalOrganizeDebugResponse': {
      folder_name: string
      normalized_folder_name: string
      status: string
      matched_rule_count: number
      matched_rules: components['schemas']['LocalOrganizeDebugRuleMatchResponse'][]
    }
    'LocalOrganizeDebugRuleMatchResponse': {
      keyword_entry_id: number | null
      canonical_name: string
      matched_terms: string[]
      all_terms: string[]
    }
    'LocalOrganizeExecuteItemResponse': {
      source_path: string
      target_path: string
      success: boolean
      status: string
      error_message: string | null
    }
    'LocalOrganizeExecuteRequest': {
      root_path: string
      target_root: string
      items: components['schemas']['LocalOrganizeCandidateResponse'][]
      dry_run?: boolean
      confirm_execute?: boolean
    }
    'LocalOrganizeExecuteResponse': {
      root_path: string
      target_root: string
      dry_run: boolean
      total_requested: number
      total_processed: number
      items: components['schemas']['LocalOrganizeExecuteItemResponse'][]
    }
    'LocalOrganizeScanRequest': {
      root_path: string
      target_root: string
      whitelist_keywords?: string[]
      fuzzy_match?: boolean
      max_results?: number
    }
    'LocalOrganizeScanResponse': {
      root_path: string
      target_root: string
      total_candidates: number
      total_move_candidates: number
      total_ambiguous: number
      skipped_count: number
      truncated_count: number
      items: components['schemas']['LocalOrganizeCandidateResponse'][]
    }
    'LocalTreeExportFileResponse': {
      filename: string
      path: string
      size_bytes: number
      updated_at: number
    }
    'LocalTreeExportRequest': {
      root_path: string
      root_name?: string | null
      output_name?: string | null
      include_files?: boolean
    }
    'LocalTreeExportResponse': {
      root_path: string
      root_name: string
      output_path: string
      output_filename: string
      folder_count: number
      file_count: number
      line_count: number
    }
    'LoginRequest': {
      username: string
      password: string
    }
    'LoginResponse': {
      success: boolean
      username: string
    }
    'LogoutResponse': {
      success: boolean
    }
    'MagnetTaskBatchResponse': {
      created_count: number
      submitted_count: number
      duplicate_skipped_count: number
      tasks: components['schemas']['MagnetTaskResponse'][]
    }
    'MagnetTaskBatchSummaryListResponse': {
      total: number
      batches: components['schemas']['MagnetTaskBatchSummaryResponse'][]
    }
    'MagnetTaskBatchSummaryResponse': {
      batch_id: string
      created_at: string
      total_count: number
      submitted_count: number
      duplicate_skipped_count: number
      failed_count: number
      pending_count: number
      items: components['schemas']['MagnetTaskResponse'][]
    }
    'MagnetTaskCreateItem': {
      source_tid: number
      source_title: string
      source_magnet: string
      source_detail_url?: string | null
      source_section?: string | null
      matched_keyword?: string | null
      matched_alias?: string | null
      match_score?: number
      keyword_entry_id?: number | null
      target_path?: string | null
      target_cid?: string | null
    }
    'MagnetTaskCreateRequest': {
      items: components['schemas']['MagnetTaskCreateItem'][]
      target_cid?: string | null
      force_submit?: boolean
      tree_import_id?: number | null
    }
    'MagnetTaskResponse': {
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
    'ManualKeywordExtractRequest': {
      import_id: number
      keywords: string[]
      node_ids?: number[] | null
      case_sensitive?: boolean
      limit?: number
    }
    'ManualPathRegexExtractRequest': {
      import_id?: number | null
      raw_path: string
      pattern: string
      flags?: string
      group_index?: number
      limit?: number
    }
    'MeResponse': {
      username: string
    }
    'NodeDetailItem': {
      raw_name: string
      raw_path: string
      cid: string | null
    }
    'NodeDetailRequest': {
      task_ids: number[]
    }
    'NodeDetailResponse': {
      details: Record<string, components['schemas']['NodeDetailItem']>
    }
    'NodePageResponse': {
      total: number
      items: components['schemas']['NodeResponse'][]
    }
    'NodePayload': {
      id: string
      name: string
      path: string
      parent_id: string | null
      is_file: boolean | null
    }
    'NodeResponse': {
      id: number
      import_id: number
      raw_name: string
      normalized_name: string
      raw_path: string
      parent_path: string | null
      depth: number
      node_type: string
      parent_id: number | null
      fingerprint_hint: string
      tags: components['schemas']['NodeTagResponse'][]
    }
    'NodeTagResponse': {
      id: number
      tag: string
      score: number
      source: string
    }
    'NoiseFileCandidateListResponse': {
      import_id: number
      total_files: number
      total_candidates: number
      candidates: components['schemas']['NoiseFileCandidateResponse'][]
    }
    'NoiseFileCandidateRequest': {
      import_id: number
      file_ids?: number[] | null
      node_ids?: number[] | null
      min_count?: number
      limit?: number
      suspicious_only?: boolean
    }
    'NoiseFileCandidateResponse': {
      filename: string
      count: number
      score: number
      reasons: string[]
      examples: string[]
    }
    'NoiseFileDeleteItemResponse': {
      file_id: number
      raw_path: string
      remote_file_id: string | null
      success: boolean
      status: string
      error_message: string | null
    }
    'NoiseFileDeleteRequest': {
      import_id: number
      file_ids: number[]
      dry_run?: boolean
      confirm_delete?: boolean
    }
    'NoiseFileDeleteResponse': {
      import_id: number
      dry_run: boolean
      total_requested: number
      total_processed: number
      items: components['schemas']['NoiseFileDeleteItemResponse'][]
    }
    'NoiseFilePreviewGroupResponse': {
      filename: string
      count: number
      items: components['schemas']['NoiseFilePreviewItemResponse'][]
    }
    'NoiseFilePreviewItemResponse': {
      file_id: number
      filename: string
      raw_path: string
      parent_path: string | null
    }
    'NoiseFilePreviewRequest': {
      import_id: number
      filenames: string[]
      limit_per_filename?: number
    }
    'NoiseFilePreviewResponse': {
      import_id: number
      total_selected_files: number
      groups: components['schemas']['NoiseFilePreviewGroupResponse'][]
    }
    'OpenAuthSessionResponse': {
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
    'OrganizeTaskBatchResponse': {
      import_id: number
      keyword_entry_id: number | null
      deleted_count: number
      created_count: number
      skipped_ambiguous_count: number
      tasks: components['schemas']['OrganizeTaskResponse'][]
    }
    'OrganizeTaskCreateRequest': {
      import_id?: number | null
      node_id?: number | null
      keyword_entry_id?: number | null
      source_path: string
      target_path: string
      matched_canonical_name?: string | null
    }
    'OrganizeTaskGenerateFromImportRequest': {
      import_id: number
      replace_existing?: boolean
    }
    'OrganizeTaskGenerateFromKeywordRequest': {
      import_id: number
      keyword_entry_id: number
      target_root: string
      replace_existing?: boolean
    }
    'OrganizeTaskPlanGenerateRequest': {
      import_id: number
      keyword_entry_id?: number | null
      task_ids?: number[] | null
      dry_run?: boolean
    }
    'OrganizeTaskResponse': {
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
    'OrganizeTaskUpdateRequest': {
      target_path?: string | null
      status?: string | null
    }
    'PathPresetResponse': {
      label: string
      path: string
    }
    'PlanBatchResponse': {
      total: number
      plans: components['schemas']['PlanResponse'][]
    }
    'PlanGenerateRequest': {
      import_id: number
      node_ids?: number[] | null
      strategy_version?: string
      dry_run?: boolean
    }
    'PlanItemResponse': {
      id: number
      node_id: number
      source_path: string
      suggested_target_path: string
      action_type: string
      confidence: number
      conflict_status: string
      reason: string | null
    }
    'PlanResponse': {
      id: number
      strategy_version: string
      scope_desc: string
      status: string
      dry_run: boolean
      created_at: string
      items: components['schemas']['PlanItemResponse'][]
    }
    'PlanSummaryPageResponse': {
      total: number
      items: components['schemas']['PlanSummaryResponse'][]
    }
    'PlanSummaryResponse': {
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
    'RegexExtractPreviewResponse': {
      import_id: number | null
      pattern: string
      flags: string
      total_nodes: number
      total_matches: number
      total_actionable_matches: number
      preview: components['schemas']['RegexMatchPreviewResponse'][]
    }
    'RegexKeywordExtractRequest': {
      import_id: number
      pattern: string
      node_ids?: number[] | null
      flags?: string
      group_index?: number
      min_count?: number
      limit?: number
    }
    'RegexMatchPreviewResponse': {
      node_id: number
      folder_name: string
      raw_path: string
      extracted_keyword: string
      match_status: string
      matched_entry_id: number | null
      matched_canonical_name: string | null
      similar_score: number | null
    }
    'RemoteFetchRequest': {
      cid: string
      path_label?: string
      depth_limit?: number
      folders_only?: boolean
    }
    'ReviewIntakeApproveRequest': {
      keyword: string
      note?: string | null
    }
    'ReviewIntakeBatchApproveEntry': {
      id: number
      keyword: string
    }
    'ReviewIntakeBatchApproveRequest': {
      items: components['schemas']['ReviewIntakeBatchApproveEntry'][]
      note?: string | null
    }
    'ReviewIntakeBatchIdsRequest': {
      ids: number[]
      note?: string | null
    }
    'ReviewIntakeBatchResponse': {
      succeeded: number
      failed: number
      results: components['schemas']['ReviewIntakeBatchResultItem'][]
    }
    'ReviewIntakeBatchResultItem': {
      id: number
      ok: boolean
      item: components['schemas']['ReviewIntakeItemResponse'] | null
      error: string | null
    }
    'ReviewIntakeCreateRequest': {
      bucket: "whitelist" | "blacklist" | "keyword"
      raw_path: string
      source?: string
      note?: string | null
      keyword?: string | null
      pattern?: string
      flags?: string
      group_index?: number
      limit?: number
    }
    'ReviewIntakeDismissRequest': {
      note?: string | null
    }
    'ReviewIntakeItemResponse': {
      id: number
      bucket: "whitelist" | "blacklist" | "keyword"
      raw_path: string
      normalized_path: string
      path_hash: string
      source: string
      note: string | null
      keyword_candidates: components['schemas']['ReviewKeywordCandidate'][]
      status: string
      approved_keyword_entry_id: number | null
      approved_keyword: string | null
      reviewed_at: string | null
      created_at: string
      updated_at: string
    }
    'ReviewIntakeListResponse': {
      items: components['schemas']['ReviewIntakeItemResponse'][]
      total: number
      page: number
      page_size: number
    }
    'ReviewIntakePathRequest': {
      raw_path: string
      source?: string
      note?: string | null
      keyword?: string | null
      pattern?: string
      flags?: string
      group_index?: number
      limit?: number
    }
    'ReviewIntakeSummaryResponse': {
      whitelist_pending: number
      blacklist_pending: number
      whitelist_approved: number
      blacklist_approved: number
      whitelist_dismissed: number
      blacklist_dismissed: number
      keyword_pending: number
      keyword_approved: number
      keyword_dismissed: number
    }
    'ReviewKeywordCandidate': {
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
    'RollbackRecordResponse': {
      id: number
      node_id: number
      log_id: number | null
      undo_action: string
      undo_payload: string | null
      status: string
      note: string | null
      created_at: string
    }
    'ScanJobRequest': {
      tree_import_id: number
      keyword_entry_ids?: number[] | null
      per_keyword_limit?: number
    }
    'ScanSummary': {
      scanned_keywords: number
      new: number
      updated: number
      skipped: number
      failed_keywords: number
    }
    'ScriptJobChange': {
      id: number
      job_name: string
      changed_at: string
      before: Record<string, unknown>
      after: Record<string, unknown>
    }
    'ScriptJobChangeListResponse': {
      items: components['schemas']['ScriptJobChange'][]
    }
    'ScriptJobListResponse': {
      items: components['schemas']['ScriptJobView'][]
    }
    'ScriptJobRunRequest': {
      dry_run?: boolean
    }
    'ScriptJobRunStarted': {
      run_id: number
      status: string
    }
    'ScriptJobUpdate': {
      enabled?: boolean | null
      run_time?: string | null
      executor?: string | null
      params?: Record<string, unknown> | null
    }
    'ScriptJobView': {
      job_name: string
      label: string
      executor: string
      enabled: boolean
      run_time: string
      params: Record<string, unknown>
      runnable: boolean
      next_run_at: string | null
    }
    'ScriptRunCounts': {
      deleted_dirs?: number
      deleted_files?: number
      empty_dirs?: number
      moved_new?: number
      moved_rescan?: number
      ambiguous?: number
      skipped?: number
      errors?: number
      warnings?: number
      unparsed_lines?: number
      moved?: number
      duplicates_removed?: number
      failed?: number
      pages_ok?: number
      pages_failed?: number
      posts_found?: number
      title_blocked?: number
      torrent_blocked?: number
      skipped_seen?: number
      submitted?: number
      submit_failed?: number
      parse_failed?: number
    }
    'ScriptRunCreate': {
      run_key: string
      script_name: "sehuatang" | "DEL_SOMETHING" | "MOVE_SSD_CACHE_TO_DISK2"
      started_at: string
      finished_at: string
      exit_code: number
      counts: components['schemas']['ScriptRunCounts']
      items?: components['schemas']['ScriptRunItemPayload'][]
    }
    'ScriptRunItemPayload': {
      kind: "deleted_dir" | "deleted_file" | "empty_dir" | "moved_new" | "moved_rescan" | "ambiguous" | "skipped" | "error" | "warning" | "submitted" | "title_blocked" | "torrent_blocked" | "submit_failed" | "parse_failed"
      path?: string | null
      target_path?: string | null
      keyword?: string | null
      message?: string | null
    }
    'ScriptRunItemResponse': {
      id: number
      kind: string
      path: string | null
      target_path: string | null
      keyword: string | null
      message: string | null
    }
    'ScriptRunItemsResponse': {
      total: number
      items: components['schemas']['ScriptRunItemResponse'][]
      kind_counts: Record<string, number>
    }
    'ScriptRunLogChunk': {
      text: string
      next_offset: number
      finished: boolean
    }
    'ScriptRunResponse': {
      id: number
      run_key: string
      script_name: string
      started_at: string
      finished_at: string | null
      exit_code: number | null
      status: "queued" | "running" | "success" | "warning" | "failed" | "stopped" | "interrupted"
      counts: components['schemas']['ScriptRunCounts']
      items_truncated: boolean
      received_at: string
      trigger: "report" | "scheduled" | "manual"
      dry_run: boolean
      error_reason: string | null
      has_log: boolean
    }
    'SessionResponse': {
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
    'SimilarKeywordPreviewRequest': {
      keywords: string[]
      threshold?: number
      limit?: number
    }
    'SimilarKeywordPreviewResponse': {
      total: number
      suggestions: components['schemas']['SimilarKeywordSuggestionResponse'][]
    }
    'SimilarKeywordSuggestionResponse': {
      keyword: string
      matched_entry_id: number
      matched_canonical_name: string
      score: number
    }
    'StrategyAnalyzeRequest': {
      node_ids?: number[] | null
      import_id?: number | null
    }
    'SubmitJobRequest': {
      candidate_ids: number[]
      force_submit?: boolean
    }
    'SubmitSummary': {
      submitted: number
      failed: number
      skipped: number
    }
    'TreeImportEntryPageResponse': {
      total: number
      items: components['schemas']['TreeImportEntryResponse'][]
    }
    'TreeImportEntryResponse': {
      id: number
      entry_type: string
      raw_name: string
      normalized_name: string
      raw_path: string
      parent_path: string | null
      depth: number
      remote_id: string | null
    }
    'TreeImportPageResponse': {
      total: number
      items: components['schemas']['TreeImportSummaryResponse'][]
    }
    'TreeImportResponse': {
      id: number
      source_filename: string
      imported_at: string
      status: string
      note: string | null
      source_type: string
    }
    'TreeImportSummaryResponse': {
      id: number
      source_filename: string
      imported_at: string
      status: string
      note: string | null
      source_type: string
    }
    'ValidationError': {
      loc: (string | number)[]
      msg: string
      type: string
      input: unknown
      ctx: Record<string, unknown>
    }
  }
}
