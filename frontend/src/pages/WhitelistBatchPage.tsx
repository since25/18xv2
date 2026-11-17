import { useEffect, useState } from 'react'
import {
  Button, Card, Empty, Input, Pagination, Popconfirm, Progress,
  Select, Space, Statistic, Table, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudDownloadOutlined, ReloadOutlined, ScanOutlined, UndoOutlined,
} from '@ant-design/icons'

import { api } from '../api/client'
import type {
  ImportListResponse, KeywordEntry, KeywordEntryListResponse,
} from '../api/types'
import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import StatusTag from '@/components/StatusTag'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'
import {
  bulkDismissCandidates, dismissCandidate, getActiveJobs, listCandidates, restoreCandidate,
  startScanJob, startSubmitJob, subscribeJobProgress,
  type JobFrame, type WhitelistCandidate,
} from '../api/whitelistBatch'

const { Text } = Typography

const LIFECYCLE_OPTIONS = [
  { label: '全部 lifecycle', value: '' },
  { label: '待提交 pending', value: 'pending' },
  { label: '已提交 submitted', value: 'submitted' },
  { label: '已丢弃 dismissed', value: 'dismissed' },
  { label: '失败 failed', value: 'failed' },
]

const DUPLICATE_OPTIONS = [
  { label: '全部 duplicate', value: '' },
  { label: 'clear', value: 'clear' },
  { label: 'duplicate_found', value: 'duplicate_found' },
  { label: 'task_exists', value: 'task_exists' },
]

const EMPTY_FRAME = (job_id: string, job_type: 'scan' | 'submit', total: number): JobFrame => ({
  job_id, job_type,
  stage: '等待开始', current: 0, total,
  done: false, error: null, summary: null,
  started_at: new Date().toISOString(), finished_at: null,
})

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function errorStatus(error: unknown) {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status?: unknown }).status
    return typeof status === 'number' ? status : undefined
  }
  return undefined
}

// 读取出错时弹固定文字（保持原来的提示），401 交给全局登录过期处理；错误继续抛出给取数工具
function failWith(text: string) {
  return (error: unknown): never => {
    if (errorStatus(error) !== 401) message.error(text)
    throw error
  }
}

// 操作出错时的提示：401 交给全局登录过期处理
function showActionError(error: Error, fallback: string) {
  if (errorStatus(error) === 401) return
  message.error(errorMessage(error, fallback))
}

function summaryValue(summary: Record<string, number> | null, key: string) {
  return summary?.[key] ?? 0
}

export default function WhitelistBatchPage() {
  // —— 基础数据 ——
  const [selectedTreeImportId, setSelectedTreeImportId] = useState<number | undefined>()
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<number[]>([])
  const [perKeywordLimit, setPerKeywordLimit] = useState(10)

  // —— Job 进度 ——
  const [scanJob, setScanJob] = useState<JobFrame | null>(null)
  const [submitJob, setSubmitJob] = useState<JobFrame | null>(null)

  // —— 候选列表 ——
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(100)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // —— 筛选 ——
  const [filterLifecycle, setFilterLifecycle] = useState('pending')
  const [filterKeywordId, setFilterKeywordId] = useState<number | undefined>()
  const [filterDuplicate, setFilterDuplicate] = useState('')
  const [searchText, setSearchText] = useState('')

  // —— 加载基础数据 ——
  // 目录树列表：首次取到且还没选时默认选第一个（出错弹固定文字）
  const { data: treeImports } = useApiQuery(
    () => api.get<ImportListResponse>('/imports/data?limit=100')
      .then((r) => {
        if ((r.items ?? []).length > 0 && selectedTreeImportId === undefined) {
          setSelectedTreeImportId(r.items[0].id)
        }
        return (r.items ?? []) as { id: number; source_filename: string }[]
      })
      .catch(failWith('加载目录树列表失败')),
    [],
    { silent: true, initialData: [] as { id: number; source_filename: string }[] },
  )

  const { data: keywords } = useApiQuery(
    () => api.get<KeywordEntryListResponse>('/keywords?keyword_type=whitelist&status=active&limit=5000')
      .then((r) => r.entries ?? [])
      .catch(failWith('加载白名单关键词失败')),
    [],
    { silent: true, initialData: [] as KeywordEntry[] },
  )

  // —— 加载候选 ——（筛选、翻页变化时自动重新加载；出错弹固定文字）
  const candidatesQuery = useApiQuery(
    () => listCandidates({
      lifecycle_status: filterLifecycle || undefined,
      matched_keyword_entry_id: filterKeywordId,
      duplicate_status: filterDuplicate || undefined,
      search: searchText || undefined,
      page, page_size: pageSize,
    }).then((r) => ({ items: r.items, total: r.total }))
      .catch(failWith('加载候选失败')),
    [page, pageSize, filterLifecycle, filterKeywordId, filterDuplicate, searchText],
    { silent: true, initialData: { items: [] as WhitelistCandidate[], total: 0 } },
  )
  const candidates = candidatesQuery.data.items
  const total = candidatesQuery.data.total
  const loadCandidates = candidatesQuery.reload

  // 接回进行中的 job（进度推送订阅保留原写法）
  useEffect(() => {
    getActiveJobs().then((data) => {
      if (data.scan) {
        setScanJob(data.scan)
        subscribeJobProgress(data.scan.job_id, (frame) => {
          if (!('job_id' in frame)) return
          setScanJob(frame)
        }, () => loadCandidates())
      }
      if (data.submit) {
        setSubmitJob(data.submit)
        subscribeJobProgress(data.submit.job_id, (frame) => {
          if (!('job_id' in frame)) return
          setSubmitJob(frame)
        }, () => loadCandidates())
      }
    }).catch(() => { /* 无 active job，忽略 */ })
  }, [loadCandidates])

  // —— 启动扫描 ——
  // 409 要单独提示，所以设为 silent，出错提示在下面自行处理
  const scanAction = useApiAction(startScanJob, { silent: true })

  async function handleScan() {
    if (!selectedTreeImportId) {
      message.warning('请先选择目录树批次')
      return
    }
    const result = await scanAction.run({
      tree_import_id: selectedTreeImportId,
      keyword_entry_ids: selectedKeywordIds.length ? selectedKeywordIds : undefined,
      per_keyword_limit: perKeywordLimit,
    })
    if (!result.ok) {
      if (errorStatus(result.error) === 409) message.warning('已有扫描任务在运行')
      else showActionError(result.error, '扫描启动失败')
      return
    }
    const resp = result.data
    setScanJob(EMPTY_FRAME(resp.job_id, 'scan', 0))
    subscribeJobProgress(resp.job_id, (frame) => {
      if (!('job_id' in frame)) {
        message.error(`SSE 错误：${frame.error}`)
        return
      }
      setScanJob(frame)
    }, (finalFrame) => {
      if (finalFrame.error) {
        message.error(`扫描失败：${finalFrame.error}`)
      } else {
        message.success('扫描完成')
      }
      loadCandidates()
    })
  }

  // —— 启动提交 ——
  const submitAction = useApiAction(startSubmitJob, { silent: true })

  async function handleSubmit() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) {
      message.warning('请先勾选要提交的候选项')
      return
    }
    const result = await submitAction.run({ candidate_ids: ids })
    if (!result.ok) {
      if (errorStatus(result.error) === 409) message.warning('已有提交任务在运行')
      else showActionError(result.error, '提交启动失败')
      return
    }
    const resp = result.data
    setSubmitJob(EMPTY_FRAME(resp.job_id, 'submit', ids.length))
    subscribeJobProgress(resp.job_id, (frame) => {
      if (!('job_id' in frame)) return
      setSubmitJob(frame)
    }, (finalFrame) => {
      if (finalFrame.error) {
        message.error(`提交失败：${finalFrame.error}`)
      } else {
        const s = (finalFrame.summary || {}) as { submitted?: number; failed?: number; skipped?: number }
        message.success(`提交完成：成功 ${s.submitted ?? 0}，失败 ${s.failed ?? 0}，跳过 ${s.skipped ?? 0}`)
      }
      setSelectedIds(new Set())
      loadCandidates()
    })
  }

  // —— 单行操作 ——（成功后刷新候选，不等待刷新完成）
  const dismissAction = useApiAction((cand: WhitelistCandidate) => dismissCandidate(cand.id), {
    successMessage: (_data, cand) => `已丢弃 ${cand.source_title}`,
    onSuccess: () => { void loadCandidates() },
  })

  async function handleDismiss(cand: WhitelistCandidate) {
    await dismissAction.run(cand)
  }

  const restoreAction = useApiAction((cand: WhitelistCandidate) => restoreCandidate(cand.id), {
    successMessage: '已恢复为 pending',
    onSuccess: () => { void loadCandidates() },
  })

  async function handleRestore(cand: WhitelistCandidate) {
    await restoreAction.run(cand)
  }

  const bulkDismissAction = useApiAction((ids: number[]) => bulkDismissCandidates(ids), {
    successMessage: (r) => `批量丢弃完成：${r.dismissed} 条已丢弃，${r.skipped} 条跳过`,
    onSuccess: () => {
      setSelectedIds(new Set())
      void loadCandidates()
    },
  })

  async function handleBulkDismiss() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) {
      message.warning('请先勾选要丢弃的候选项')
      return
    }
    await bulkDismissAction.run(ids)
  }

  const columns: ColumnsType<WhitelistCandidate> = [
    { title: '资源标题', dataIndex: 'source_title', width: 280, ellipsis: true },
    { title: '命中关键词', dataIndex: 'matched_keyword', width: 120 },
    {
      title: 'duplicate', dataIndex: 'duplicate_status', width: 130,
      render: (s: string, row) => {
        return <StatusTag domain="workflow" value={s} tooltip={row.duplicate_reason ?? undefined} />
      },
    },
    {
      title: 'lifecycle', dataIndex: 'lifecycle_status', width: 120,
      render: (s: string) => {
        return <StatusTag domain="workflow" value={s} />
      },
    },
    { title: 'score', dataIndex: 'match_score', width: 80, render: (v: number) => v.toFixed(2) },
    {
      title: '操作', key: 'op', width: 200,
      render: (_: unknown, row) => {
        if (row.lifecycle_status === 'pending') {
          return (
            <Popconfirm title="确认丢弃？下次扫描不会再出现" onConfirm={() => handleDismiss(row)}>
              <Button size="small" danger>丢弃</Button>
            </Popconfirm>
          )
        }
        if (row.lifecycle_status === 'dismissed' || row.lifecycle_status === 'failed') {
          return (
            <Button size="small" icon={<UndoOutlined />} onClick={() => handleRestore(row)}>
              恢复
            </Button>
          )
        }
        if (row.lifecycle_status === 'submitted' && row.magnet_task_id) {
          return (
            <Button size="small" onClick={() => window.open(`/magnet-tasks?task_id=${row.magnet_task_id}`, '_blank')}>
              查看任务
            </Button>
          )
        }
        return null
      },
    },
  ]

  const scanRunning = !!scanJob && !scanJob.done
  const submitRunning = !!submitJob && !submitJob.done

  return (
    <PageScaffold title="白名单批处理" description="扫描白名单候选，批量提交或丢弃资源。">

      <Card title="扫描控制台" className="soft-card">
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <DataToolbar>
            <Select
              style={{ minWidth: 280 }}
              placeholder="选择目录树批次"
              value={selectedTreeImportId}
              onChange={setSelectedTreeImportId}
              options={treeImports.map((t) => ({
                value: t.id, label: `#${t.id} ${t.source_filename}`,
              }))}
            />
            <Select
              mode="multiple"
              style={{ minWidth: 320 }}
              placeholder="留空 = 所有 active 白名单"
              value={selectedKeywordIds}
              onChange={setSelectedKeywordIds}
              options={keywords.map((k) => ({ value: k.id, label: k.canonical_name }))}
              maxTagCount="responsive"
              allowClear
            />
            <Input
              addonBefore="每词上限" type="number" style={{ width: 160 }}
              value={perKeywordLimit}
              onChange={(e) => setPerKeywordLimit(Number(e.target.value) || 10)}
            />
            <Button
              type="primary" icon={<ScanOutlined />} onClick={handleScan}
              loading={scanRunning}
            >
              开始扫描
            </Button>
          </DataToolbar>

          {scanJob && (
            <Card size="small" type="inner" title={`扫描进度（${scanJob.stage}）`}>
              <Progress
                percent={scanJob.total ? Math.round((scanJob.current / scanJob.total) * 100) : 0}
                status={scanJob.error ? 'exception' : scanJob.done ? 'success' : 'active'}
              />
              <div style={{ marginTop: 4 }}>{scanJob.current}/{scanJob.total}</div>
              {scanJob.summary && (
                <Space size="large" style={{ marginTop: 12 }}>
                  <Statistic title="新增" value={summaryValue(scanJob.summary, 'new')} />
                  <Statistic title="更新" value={summaryValue(scanJob.summary, 'updated')} />
                  <Statistic title="跳过" value={summaryValue(scanJob.summary, 'skipped')} />
                  <Statistic title="失败关键词" value={summaryValue(scanJob.summary, 'failed_keywords')} />
                </Space>
              )}
              {scanJob.error && (
                <div style={{ marginTop: 8 }}>
                  <Text type="danger">错误：{scanJob.error}</Text>
                </div>
              )}
            </Card>
          )}
        </Space>
      </Card>

      <Card title="候选列表" className="soft-card"
            extra={
              <Space wrap>
                <Button icon={<ReloadOutlined />} onClick={() => void loadCandidates()}>刷新</Button>
                <Popconfirm
                  title="批量丢弃"
                  description={`确认丢弃勾选的 ${selectedIds.size} 条？下次扫描不会再出现。已提交项会自动跳过。`}
                  okText="确认丢弃" okButtonProps={{ danger: true }}
                  onConfirm={handleBulkDismiss}
                  disabled={selectedIds.size === 0}
                >
                  <Button danger disabled={selectedIds.size === 0}>
                    丢弃勾选（{selectedIds.size}）
                  </Button>
                </Popconfirm>
                <Button
                  type="primary" icon={<CloudDownloadOutlined />}
                  disabled={selectedIds.size === 0 || submitRunning}
                  onClick={handleSubmit}
                >
                  提交勾选（{selectedIds.size}）
                </Button>
              </Space>
            }
      >
        <div style={{ marginBottom: 12 }}>
          <DataToolbar>
            <Select
              style={{ width: 160 }} value={filterLifecycle}
              onChange={(v) => { setFilterLifecycle(v); setPage(1) }}
              options={LIFECYCLE_OPTIONS}
            />
            <Select
              style={{ width: 220 }} value={filterKeywordId} allowClear
              placeholder="按关键词筛选"
              onChange={(v) => { setFilterKeywordId(v); setPage(1) }}
              options={keywords.map((k) => ({ value: k.id, label: k.canonical_name }))}
              showSearch optionFilterProp="label"
            />
            <Select
              style={{ width: 180 }} value={filterDuplicate}
              onChange={(v) => { setFilterDuplicate(v); setPage(1) }}
              options={DUPLICATE_OPTIONS}
            />
            <Input.Search
              placeholder="搜索标题/关键词" style={{ width: 240 }}
              allowClear
              onSearch={(v) => { setSearchText(v); setPage(1) }}
            />
          </DataToolbar>
        </div>

        {candidates.length === 0 ? (
          <Empty description="没有候选；试试扫描或更换筛选" />
        ) : (
          <>
            <Table
              size="small" rowKey="id" pagination={false}
              columns={columns} dataSource={candidates}
              rowSelection={{
                selectedRowKeys: Array.from(selectedIds),
                onChange: (keys) => setSelectedIds(new Set(keys as number[])),
                getCheckboxProps: (row) => ({
                  // pending 可勾（提交/丢弃都行），failed 可勾（仅丢弃有效）
                  disabled: !['pending', 'failed'].includes(row.lifecycle_status),
                }),
              }}
            />
            <Pagination
              style={{ marginTop: 12, textAlign: 'right' }}
              current={page} pageSize={pageSize} total={total}
              showSizeChanger
              pageSizeOptions={[100, 200, 500]}
              showTotal={(t) => `共 ${t} 条`}
              onChange={(p, ps) => {
                setPage(p)
                if (ps !== pageSize) setPageSize(ps)
              }}
              onShowSizeChange={(_p, ps) => {
                setPageSize(ps)
                setPage(1)
              }}
            />
          </>
        )}
      </Card>

      {submitJob && (
        <Card title={`提交进度（${submitJob.stage}）`} className="soft-card">
          <Progress
            percent={submitJob.total ? Math.round((submitJob.current / submitJob.total) * 100) : 0}
            status={submitJob.error ? 'exception' : submitJob.done ? 'success' : 'active'}
          />
          <div style={{ marginTop: 4 }}>{submitJob.current}/{submitJob.total}</div>
          {submitJob.summary && (
            <Space size="large" style={{ marginTop: 12 }}>
              <Statistic title="成功" value={summaryValue(submitJob.summary, 'submitted')} />
              <Statistic title="失败" value={summaryValue(submitJob.summary, 'failed')} />
              <Statistic title="跳过" value={summaryValue(submitJob.summary, 'skipped')} />
            </Space>
          )}
          {submitJob.error && (
            <div style={{ marginTop: 8 }}>
              <Text type="danger">错误：{submitJob.error}</Text>
            </div>
          )}
        </Card>
      )}
    </PageScaffold>
  )
}
