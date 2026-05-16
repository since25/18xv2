import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Segmented,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CloudDownloadOutlined, DeleteOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import type {
  ImportListResponse,
  KeywordEntry,
  KeywordEntryListResponse,
  MagnetArticleCandidate,
  MagnetArticleSearchResponse,
  MagnetDuplicateCheckItem,
  MagnetDuplicateCheckResponse,
  MagnetTask,
  MagnetTaskBatchResponse,
  MagnetTaskBatchSummary,
  MagnetTaskBatchSummaryListResponse,
  RemoteFetchRequest,
  TreeImport,
  WhitelistBatchCandidate,
  WhitelistBatchPreviewResponse,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { Paragraph, Text, Title } = Typography

const DUPLICATE_COLOR: Record<string, string> = {
  clear: 'green',
  duplicate_found: 'red',
  task_exists: 'orange',
}

const TASK_STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  submitted: 'green',
  duplicate_skipped: 'orange',
  failed: 'red',
}

const DEFAULT_TARGET_CID = '3412729136586281899'

export default function MagnetTasksPage() {
  const [query, setQuery] = useState('')
  const [keywordEntryId, setKeywordEntryId] = useState<number | null>(null)
  const [targetCid, setTargetCid] = useState(DEFAULT_TARGET_CID)
  const [candidates, setCandidates] = useState<MagnetArticleCandidate[]>([])
  const [duplicateMap, setDuplicateMap] = useState<Record<number, MagnetDuplicateCheckItem>>({})
  const [taskBatches, setTaskBatches] = useState<MagnetTaskBatchSummary[]>([])
  const [selectedRowKeys, setSelectedRowKeys] = useState<Array<string | number>>([])
  const [searching, setSearching] = useState(false)
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [loadingTasks, setLoadingTasks] = useState(false)
  const [clearingTasks, setClearingTasks] = useState(false)
  const [whitelistEntries, setWhitelistEntries] = useState<KeywordEntry[]>([])
  const [selectedWhitelistKeywordIds, setSelectedWhitelistKeywordIds] = useState<number[]>([])
  const [perKeywordLimit, setPerKeywordLimit] = useState(10)
  const [totalLimit, setTotalLimit] = useState(100)
  const [submitLimit, setSubmitLimit] = useState(20)
  const [batchPreview, setBatchPreview] = useState<WhitelistBatchCandidate[]>([])
  const [previewingBatch, setPreviewingBatch] = useState(false)
  const [submittingBatch, setSubmittingBatch] = useState(false)
  const [batchStats, setBatchStats] = useState<WhitelistBatchPreviewResponse | null>(null)
  const [selectedBatchPreviewKeys, setSelectedBatchPreviewKeys] = useState<Array<string | number>>([])
  const [batchPreviewSearch, setBatchPreviewSearch] = useState('')
  const [batchDuplicateFilter, setBatchDuplicateFilter] = useState<'all' | 'clear' | 'duplicate_found' | 'task_exists'>('all')

  const [treeImports, setTreeImports] = useState<TreeImport[]>([])
  const [selectedTreeImportId, setSelectedTreeImportId] = useState<number | null>(null)
  const [remoteCid, setRemoteCid] = useState('')
  const [remotePathLabel, setRemotePathLabel] = useState('')
  const [remoteDepthLimit, setRemoteDepthLimit] = useState(3)
  const [fetchingTree, setFetchingTree] = useState(false)

  const selectedCandidates = useMemo(
    () => candidates.filter((item) => selectedRowKeys.includes(item.source_tid)),
    [candidates, selectedRowKeys],
  )

  const getBatchPreviewRowKey = (record: WhitelistBatchCandidate) => `${record.source_tid}-${record.keyword_entry_id ?? 'na'}`

  const filteredBatchPreview = useMemo(() => {
    const needle = batchPreviewSearch.trim().toLowerCase()
    return batchPreview.filter((item) => {
      if (batchDuplicateFilter !== 'all' && item.duplicate_status !== batchDuplicateFilter) {
        return false
      }
      if (!needle) {
        return true
      }
      const haystacks = [
        item.source_title,
        item.matched_keyword ?? '',
        item.matched_alias ?? '',
        item.target_path,
        String(item.source_tid),
      ]
      return haystacks.some((value) => value.toLowerCase().includes(needle))
    })
  }, [batchDuplicateFilter, batchPreview, batchPreviewSearch])

  const selectedBatchPreviewItems = useMemo(() => {
    const selected = new Set(selectedBatchPreviewKeys.map(String))
    return batchPreview.filter((item) => selected.has(getBatchPreviewRowKey(item)))
  }, [batchPreview, selectedBatchPreviewKeys])

  const ensureTreeImportSelected = () => {
    if (selectedTreeImportId !== null) {
      return true
    }
    message.warning('请先选择目录树批次。磁力去重现在只允许本地目录树匹配，不再调用 115 搜索接口。')
    return false
  }

  const loadTaskBatches = async () => {
    setLoadingTasks(true)
    try {
      const response = await api.get<MagnetTaskBatchSummaryListResponse>('/magnet-tasks/batches?limit=20')
      setTaskBatches(response.batches ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingTasks(false)
    }
  }

  const loadTreeImports = async () => {
    try {
      const response = await api.get<ImportListResponse>('/imports/data?limit=100')
      setTreeImports(response.items ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const loadWhitelistEntries = async () => {
    try {
      const response = await api.get<KeywordEntryListResponse>('/keywords?keyword_type=whitelist&status=active&limit=5000')
      setWhitelistEntries(response.entries ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const fetchRemoteTree = async () => {
    if (!remoteCid.trim()) {
      message.warning('请先输入 115 目录 CID')
      return
    }
    setFetchingTree(true)
    try {
      const payload: RemoteFetchRequest = {
        cid: remoteCid.trim(),
        path_label: remotePathLabel.trim(),
        depth_limit: remoteDepthLimit,
        folders_only: true,
      }
      const result = await api.post<TreeImport>('/imports/remote-fetch', payload)
      message.success(`目录树快照已创建，批次 #${result.id}`)
      await loadTreeImports()
      setSelectedTreeImportId(result.id)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setFetchingTree(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadTaskBatches()
      void loadTreeImports()
      void loadWhitelistEntries()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  const searchCandidates = async () => {
    if (!query.trim()) {
      message.warning('请先输入搜索词')
      return
    }

    setSearching(true)
    try {
      const response = await api.post<MagnetArticleSearchResponse>('/magnet-tasks/search', {
        query: query.trim(),
        keyword_entry_id: keywordEntryId,
        limit: 30,
      })
      setCandidates(response.candidates ?? [])
      setDuplicateMap({})
      setSelectedRowKeys([])
      message.success(`搜索完成，共 ${response.total_candidates} 条候选`)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setSearching(false)
    }
  }

  const checkDuplicates = async () => {
    if (!selectedCandidates.length) {
      message.warning('请先勾选候选项')
      return
    }
    if (!ensureTreeImportSelected()) {
      return
    }

    setChecking(true)
    try {
      const response = await api.post<MagnetDuplicateCheckResponse>('/magnet-tasks/duplicate-check', {
        items: selectedCandidates.map((item) => ({
          source_tid: item.source_tid,
          source_title: item.source_title,
          source_magnet: item.source_magnet,
          matched_keyword: item.matched_keyword,
          matched_alias: item.matched_alias,
        })),
        tree_import_id: selectedTreeImportId ?? null,
      })
      setDuplicateMap(Object.fromEntries((response.items ?? []).map((item) => [item.source_tid, item])))
      const duplicateCount = (response.items ?? []).filter((item) => item.duplicate_status !== 'clear').length
      message.success(`去重检查完成，发现 ${duplicateCount} 条重复或已存在任务`)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setChecking(false)
    }
  }

  const submitTasks = async () => {
    if (!selectedCandidates.length) {
      message.warning('请先勾选候选项')
      return
    }
    if (!ensureTreeImportSelected()) {
      return
    }

    setSubmitting(true)
    try {
      const response = await api.post<MagnetTaskBatchResponse>('/magnet-tasks/submit', {
        items: selectedCandidates.map((item) => ({
          source_tid: item.source_tid,
          source_title: item.source_title,
          source_magnet: item.source_magnet,
          source_detail_url: item.source_detail_url,
          source_section: item.source_section,
          matched_keyword: item.matched_keyword,
          matched_alias: item.matched_alias,
          match_score: item.match_score,
          keyword_entry_id: keywordEntryId,
        })),
        target_cid: targetCid.trim() || null,
        force_submit: false,
        tree_import_id: selectedTreeImportId ?? null,
      })
      message.success(
        `已创建 ${response.created_count} 条任务，提交 ${response.submitted_count} 条，跳过 ${response.duplicate_skipped_count} 条`,
      )
      await loadTaskBatches()
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const clearTaskHistory = async () => {
    setClearingTasks(true)
    try {
      const response = await api.delete<{ deleted_count: number }>('/magnet-tasks/history')
      message.success(`已清理 ${response.deleted_count} 条磁力任务记录`)
      setTaskBatches([])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setClearingTasks(false)
    }
  }

  const previewWhitelistBatch = async () => {
    if (!ensureTreeImportSelected()) {
      return
    }

    setPreviewingBatch(true)
    try {
      const response = await api.post<WhitelistBatchPreviewResponse>('/magnet-tasks/whitelist-batch/preview', {
        tree_import_id: selectedTreeImportId,
        keyword_entry_ids: selectedWhitelistKeywordIds,
        per_keyword_limit: perKeywordLimit,
        total_limit: totalLimit,
        submit_limit: submitLimit,
        force_submit: false,
      })
      setBatchPreview(response.candidates ?? [])
      setBatchStats(response)
      setSelectedBatchPreviewKeys([])
      message.success(`批量预览完成，筛出 ${response.selected_candidates} 条可提交候选`)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setPreviewingBatch(false)
    }
  }

  const submitWhitelistBatch = async () => {
    if (!ensureTreeImportSelected()) {
      return
    }
    if (!selectedBatchPreviewItems.length) {
      message.warning('请先在预览结果里勾选准备提交的候选项')
      return
    }

    setSubmittingBatch(true)
    try {
      const itemsToSubmit = selectedBatchPreviewItems.slice(0, submitLimit)
      const response = await api.post<MagnetTaskBatchResponse>('/magnet-tasks/submit', {
        items: itemsToSubmit.map((item) => ({
          source_tid: item.source_tid,
          source_title: item.source_title,
          source_magnet: item.source_magnet,
          source_detail_url: item.source_detail_url,
          source_section: item.source_section,
          matched_keyword: item.matched_keyword,
          matched_alias: item.matched_alias,
          match_score: item.match_score,
          keyword_entry_id: item.keyword_entry_id,
          target_path: item.target_path,
        })),
        force_submit: false,
        tree_import_id: selectedTreeImportId ?? null,
      })
      message.success(
        `批量任务完成，创建 ${response.created_count} 条，提交 ${response.submitted_count} 条，跳过 ${response.duplicate_skipped_count} 条`,
      )
      await loadTaskBatches()
      const submittedTidSet = new Set(response.tasks.map((item) => item.source_tid))
      const submittedKeySet = new Set(
        itemsToSubmit.filter((item) => submittedTidSet.has(item.source_tid)).map((item) => getBatchPreviewRowKey(item)),
      )
      setBatchPreview((current) => current.filter((item) => !submittedKeySet.has(getBatchPreviewRowKey(item))))
      setSelectedBatchPreviewKeys((current) => current.filter((key) => !submittedKeySet.has(String(key))))
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setSubmittingBatch(false)
    }
  }

  const candidateColumns: ColumnsType<MagnetArticleCandidate> = [
    {
      title: '候选资源',
      dataIndex: 'source_title',
      render: (value: string, record) => {
        const duplicate = duplicateMap[record.source_tid]
        return (
          <div>
            <Text strong>{value}</Text>
            <div className="meta-tags">
              <Tag>{`tid ${record.source_tid}`}</Tag>
              <Tag>{`score ${record.match_score}`}</Tag>
              {record.matched_keyword && <Tag color="blue">{record.matched_keyword}</Tag>}
              {record.matched_alias && <Tag>{`别名 ${record.matched_alias}`}</Tag>}
              <Tag color={DUPLICATE_COLOR[duplicate?.duplicate_status ?? 'default'] ?? 'default'}>
                {duplicate?.duplicate_status ?? '未检查'}
              </Tag>
            </div>
            <div className="ellipsis-stack">
              {record.source_detail_url && <div>{record.source_detail_url}</div>}
              <div>{record.source_magnet.slice(0, 120)}...</div>
              {duplicate?.duplicate_reason && <div>{duplicate.duplicate_reason}</div>}
              {duplicate?.matched_import_id && (
                <div>
                  {`命中批次 #${duplicate.matched_import_id} · ${duplicate.matched_import_label ?? '未命名批次'}`}
                  <Link style={{ marginLeft: 8 }} to={`/nodes?import_id=${duplicate.matched_import_id}`}>
                    查看内容
                  </Link>
                </div>
              )}
              {duplicate?.matched_terms?.length ? (
                <div>{`匹配词：${duplicate.matched_terms.join('、')}`}</div>
              ) : null}
              {duplicate?.matched_nodes?.length ? (
                <div>
                  {duplicate.matched_nodes.slice(0, 3).map((node) => (
                    <div key={`${record.source_tid}-${node.path}`}>{node.path}</div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )
      },
    },
  ]

  const batchPreviewColumns: ColumnsType<WhitelistBatchCandidate> = [
    {
      title: '白名单命中资源',
      dataIndex: 'source_title',
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div className="meta-tags">
            <Tag>{`tid ${record.source_tid}`}</Tag>
            <Tag>{`score ${record.match_score}`}</Tag>
            {record.matched_keyword && <Tag color="blue">{record.matched_keyword}</Tag>}
            {record.matched_alias && <Tag>{`别名 ${record.matched_alias}`}</Tag>}
            <Tag color={DUPLICATE_COLOR[record.duplicate_status] ?? 'default'}>{record.duplicate_status}</Tag>
          </div>
          <div className="ellipsis-stack">
            {record.source_detail_url && <div>{record.source_detail_url}</div>}
            <div>{record.target_path}</div>
            <div>{record.source_magnet.slice(0, 120)}...</div>
            {record.duplicate_reason && <div>{record.duplicate_reason}</div>}
            {record.matched_import_id ? (
              <div>
                {`命中批次 #${record.matched_import_id} · ${record.matched_import_label ?? '未命名批次'}`}
                <Link style={{ marginLeft: 8 }} to={`/nodes?import_id=${record.matched_import_id}`}>
                  查看内容
                </Link>
              </div>
            ) : null}
          </div>
        </div>
      ),
    },
  ]

  const taskColumns: ColumnsType<MagnetTask> = [
    {
      title: '任务',
      dataIndex: 'source_title',
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div className="meta-tags">
            <Tag>{`#${record.id}`}</Tag>
            <Tag>{`tid ${record.source_tid}`}</Tag>
            <Tag color={TASK_STATUS_COLOR[record.status] ?? 'default'}>{record.status}</Tag>
            <Tag color={DUPLICATE_COLOR[record.duplicate_status] ?? 'default'}>{record.duplicate_status}</Tag>
          </div>
          <div className="ellipsis-stack">
            {record.failure_reason && <div>{record.failure_reason}</div>}
            {record.operation_log && <div>{record.operation_log}</div>}
          </div>
        </div>
      ),
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_to_115_at',
      width: 180,
      render: (value: string | null) => formatDateTime(value),
    },
  ]

  return (
    <div className="page-shell">
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>磁力下载台</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            支持两种模式：手动搜词精细提交，或按白名单批量检索并自动落到 /已整理/关键词/磁力名称。
          </Paragraph>
        </div>
      </div>

      <Card className="soft-card" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            style={{ width: 220 }}
            placeholder="搜索词"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={() => void searchCandidates()}
          />
          <InputNumber
            style={{ width: 160 }}
            placeholder="关键词 ID"
            value={keywordEntryId ?? undefined}
            onChange={(value) => setKeywordEntryId(typeof value === 'number' ? value : null)}
          />
          <Input
            style={{ width: 220 }}
            placeholder="115 保存目录 CID（可选）"
            value={targetCid}
            onChange={(event) => setTargetCid(event.target.value)}
          />
          <Button type="primary" icon={<SearchOutlined />} loading={searching} onClick={() => void searchCandidates()}>
            搜索预览
          </Button>
          <Button loading={checking} onClick={() => void checkDuplicates()} disabled={selectedTreeImportId === null}>
            检查重复
          </Button>
          <Button loading={submitting} onClick={() => void submitTasks()} disabled={selectedTreeImportId === null}>
            提交勾选项
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void loadTaskBatches()} loading={loadingTasks}>
            刷新最近任务
          </Button>
        </Space>
      </Card>

      <Card className="soft-card" style={{ marginBottom: 16 }} title="白名单批处理">
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="适合日常增量跑"
            description="系统会按 active whitelist 批量检索外部库，跨关键词合并候选，再结合本地目录树去重。预览后可以人工筛掉误匹配，再提交到 115；提交时自动创建目录 /已整理/关键词/磁力名称。"
          />
          <Space wrap align="start">
            <Select
              mode="multiple"
              showSearch
              allowClear
              maxTagCount={4}
              placeholder="选择白名单关键词（留空则跑全部 active whitelist）"
              style={{ width: 420 }}
              value={selectedWhitelistKeywordIds}
              onChange={(values) => setSelectedWhitelistKeywordIds(values)}
              optionFilterProp="label"
              filterOption={(input, option) => String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
              options={whitelistEntries.map((entry) => ({
                value: entry.id,
                label: `#${entry.id} · ${entry.canonical_name}`,
              }))}
            />
            <InputNumber
              min={1}
              max={100}
              addonBefore="每词"
              value={perKeywordLimit}
              onChange={(value) => setPerKeywordLimit(Number(value ?? 10))}
            />
            <InputNumber
              min={1}
              max={500}
              addonBefore="总预览"
              value={totalLimit}
              onChange={(value) => setTotalLimit(Number(value ?? 100))}
            />
            <InputNumber
              min={1}
              max={100}
              addonBefore="单次提交"
              value={submitLimit}
              onChange={(value) => setSubmitLimit(Number(value ?? 20))}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void loadWhitelistEntries()}>
              刷新白名单
            </Button>
            <Button type="primary" loading={previewingBatch} onClick={() => void previewWhitelistBatch()}>
              预览批处理
            </Button>
            <Button loading={submittingBatch} onClick={() => void submitWhitelistBatch()}>
              提交已勾选项到 115
            </Button>
          </Space>
          <Text type="secondary">
            每词：每个白名单关键词最多取多少条外部候选。总预览：本次预览页最多保留多少条合并后的候选。单次提交：每次点击提交时，最多提交多少条已勾选结果；如果勾选数量超过这个值，需要重复提交下一批。
          </Text>
          <Space size={16} wrap>
            <Statistic title="Active 白名单" value={whitelistEntries.length} />
            <Statistic title="已选关键词" value={selectedWhitelistKeywordIds.length || whitelistEntries.length} />
            <Statistic title="本次预览候选" value={batchPreview.length} />
            <Statistic title="已勾选候选" value={selectedBatchPreviewItems.length} />
            <Statistic title="提交上限" value={submitLimit} />
          </Space>
        </Space>
      </Card>

      <Collapse
        ghost
        style={{ marginBottom: 16 }}
        items={[{
          key: 'tree',
          label: '目录树去重设置（本地匹配，无 API 风控）',
          children: (
            <Card className="soft-card" size="small">
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Alert
                  type="warning"
                  showIcon
                  message="磁力去重只使用本地目录树"
                  description="如果没有先选择目录树批次，系统不会再回退去调用 115 搜索接口。请先选一个手动上传或 115 拉取得到的目录树批次。"
                />
                <Space wrap>
                  <Tooltip title="这里会显示所有目录树批次，包括手动上传和 115 拉取的快照。">
                    <Select
                      showSearch
                      allowClear
                      optionFilterProp="label"
                      placeholder="选择目录树批次（必选）"
                      style={{ width: 420 }}
                      value={selectedTreeImportId ?? undefined}
                      onChange={(value) => setSelectedTreeImportId(value ?? null)}
                      options={treeImports.map((item) => ({
                        value: item.id,
                        label: `#${item.id} · ${item.source_filename} [${item.source_type}]`,
                      }))}
                    />
                  </Tooltip>
                  <Button icon={<ReloadOutlined />} onClick={() => void loadTreeImports()}>
                    刷新批次
                  </Button>
                  {selectedTreeImportId ? (
                    <Button href={`/nodes?import_id=${selectedTreeImportId}`}>
                      查看选中批次内容
                    </Button>
                  ) : null}
                </Space>
                <Space wrap>
                  <Input
                    style={{ width: 200 }}
                    placeholder="115 目录 CID"
                    value={remoteCid}
                    onChange={(event) => setRemoteCid(event.target.value)}
                  />
                  <Input
                    style={{ width: 220 }}
                    placeholder="路径标签（如：根目录）"
                    value={remotePathLabel}
                    onChange={(event) => setRemotePathLabel(event.target.value)}
                  />
                  <InputNumber
                    style={{ width: 120 }}
                    addonBefore="深度"
                    min={1}
                    max={6}
                    value={remoteDepthLimit}
                    onChange={(value) => setRemoteDepthLimit(Number(value ?? 3))}
                  />
                  <Button
                    icon={<CloudDownloadOutlined />}
                    loading={fetchingTree}
                    onClick={() => void fetchRemoteTree()}
                  >
                    拉取目录树快照
                  </Button>
                </Space>
              </Space>
            </Card>
          ),
        }]}
      />

      {!candidates.length && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="还没有搜索结果。"
          description="先输入搜索词，再走“搜索预览 → 检查重复 → 提交勾选项”的流程。"
        />
      )}

      <Card className="soft-card" title={`搜索候选（${candidates.length}）`} style={{ marginBottom: 16 }}>
        <Table
          rowKey="source_tid"
          dataSource={candidates}
          columns={candidateColumns}
          pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 条` }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys as Array<string | number>),
          }}
        />
      </Card>

      <Card className="soft-card" title={`白名单批处理预览（${batchPreview.length}）`} style={{ marginBottom: 16 }}>
        {batchStats ? (
          <Alert
            style={{ marginBottom: 16 }}
            type="success"
            showIcon
            message={`本次扫描 ${batchStats.scanned_keyword_count} 个白名单关键词，产出 ${batchStats.total_candidates} 条候选`}
            description={`现在预览结果支持手动筛选和勾选。每次提交最多处理 ${submitLimit} 条已勾选结果，已提交的记录会从预览区移除，剩余部分可以继续复核后再提交。`}
          />
        ) : (
          <Alert
            style={{ marginBottom: 16 }}
            type="info"
            showIcon
            message="还没有白名单批处理预览结果。"
            description="先选择目录树批次，再点“预览批处理”。"
          />
        )}
        <Space wrap style={{ marginBottom: 16 }}>
          <Segmented
            value={batchDuplicateFilter}
            onChange={(value) => setBatchDuplicateFilter(value as 'all' | 'clear' | 'duplicate_found' | 'task_exists')}
            options={[
              { label: '全部', value: 'all' },
              { label: 'clear', value: 'clear' },
              { label: 'duplicate_found', value: 'duplicate_found' },
              { label: 'task_exists', value: 'task_exists' },
            ]}
          />
          <Input
            style={{ width: 280 }}
            placeholder="按标题 / 关键词 / 目标路径筛选"
            value={batchPreviewSearch}
            onChange={(event) => setBatchPreviewSearch(event.target.value)}
          />
          <Button
            onClick={() => setSelectedBatchPreviewKeys(filteredBatchPreview.map((item) => getBatchPreviewRowKey(item)))}
          >
            勾选当前筛选结果
          </Button>
          <Button
            onClick={() => setSelectedBatchPreviewKeys(
              filteredBatchPreview
                .filter((item) => item.duplicate_status === 'clear')
                .map((item) => getBatchPreviewRowKey(item)),
            )}
          >
            仅勾选 clear
          </Button>
          <Button onClick={() => setSelectedBatchPreviewKeys([])}>
            清空勾选
          </Button>
        </Space>
        <Table
          rowKey={(record) => `${record.source_tid}-${record.keyword_entry_id ?? 'na'}`}
          dataSource={filteredBatchPreview}
          columns={batchPreviewColumns}
          pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 条` }}
          rowSelection={{
            selectedRowKeys: selectedBatchPreviewKeys,
            onChange: (keys) => setSelectedBatchPreviewKeys(keys as Array<string | number>),
          }}
        />
      </Card>

      <Card
        className="soft-card"
        title={`最近磁力任务批次（${taskBatches.length}）`}
        extra={(
          <Popconfirm title="确认清理最近磁力任务记录？" onConfirm={() => void clearTaskHistory()}>
            <Button danger icon={<DeleteOutlined />} loading={clearingTasks}>
              清理记录
            </Button>
          </Popconfirm>
        )}
      >
        {taskBatches.length ? (
          <Collapse
            items={taskBatches.map((batch) => ({
              key: batch.batch_id,
              label: (
                <Space wrap>
                  <Text strong>{batch.batch_id}</Text>
                  <Tag>{formatDateTime(batch.created_at)}</Tag>
                  <Tag color="blue">{`提交 ${batch.submitted_count}/${batch.total_count}`}</Tag>
                  {batch.duplicate_skipped_count ? <Tag color="orange">{`跳过 ${batch.duplicate_skipped_count}`}</Tag> : null}
                  {batch.failed_count ? <Tag color="red">{`失败 ${batch.failed_count}`}</Tag> : null}
                  {batch.pending_count ? <Tag>{`待处理 ${batch.pending_count}`}</Tag> : null}
                </Space>
              ),
              children: (
                <Table
                  rowKey="id"
                  dataSource={batch.items}
                  columns={taskColumns}
                  pagination={false}
                  size="small"
                />
              ),
            }))}
          />
        ) : (
          <Alert type="info" showIcon message="还没有最近磁力任务记录。" />
        )}
      </Card>
    </div>
  )
}
