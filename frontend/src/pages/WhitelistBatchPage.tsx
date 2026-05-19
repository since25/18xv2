import { useEffect, useState } from 'react'
import {
  Button, Card, Empty, Input, Pagination, Popconfirm, Progress,
  Select, Space, Statistic, Table, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudDownloadOutlined, ReloadOutlined, ScanOutlined, UndoOutlined,
} from '@ant-design/icons'

import { api } from '../api/client'
import type {
  ImportListResponse, KeywordEntry, KeywordEntryListResponse,
} from '../api/types'
import {
  bulkDismissCandidates, dismissCandidate, getActiveJobs, listCandidates, restoreCandidate,
  startScanJob, startSubmitJob, subscribeJobProgress,
  type JobFrame, type WhitelistCandidate,
} from '../api/whitelistBatch'

const { Title } = Typography

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

export default function WhitelistBatchPage() {
  // —— 基础数据 ——
  const [treeImports, setTreeImports] = useState<{ id: number; source_filename: string }[]>([])
  const [selectedTreeImportId, setSelectedTreeImportId] = useState<number | undefined>()
  const [keywords, setKeywords] = useState<KeywordEntry[]>([])
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<number[]>([])
  const [perKeywordLimit, setPerKeywordLimit] = useState(10)

  // —— Job 进度 ——
  const [scanJob, setScanJob] = useState<JobFrame | null>(null)
  const [submitJob, setSubmitJob] = useState<JobFrame | null>(null)

  // —— 候选列表 ——
  const [candidates, setCandidates] = useState<WhitelistCandidate[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const pageSize = 100
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // —— 筛选 ——
  const [filterLifecycle, setFilterLifecycle] = useState('pending')
  const [filterKeywordId, setFilterKeywordId] = useState<number | undefined>()
  const [filterDuplicate, setFilterDuplicate] = useState('')
  const [searchText, setSearchText] = useState('')

  // —— 加载基础数据 ——
  useEffect(() => {
    api.get<ImportListResponse>('/imports/data?limit=100')
      .then((r) => {
        setTreeImports(r.items ?? [])
        if ((r.items ?? []).length > 0 && selectedTreeImportId === undefined) {
          setSelectedTreeImportId(r.items[0].id)
        }
      })
      .catch(() => message.error('加载目录树列表失败'))

    api.get<KeywordEntryListResponse>('/keywords?keyword_type=whitelist&status=active&limit=5000')
      .then((r) => setKeywords(r.entries ?? []))
      .catch(() => message.error('加载白名单关键词失败'))

    // 接回进行中的 job
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // —— 加载候选 ——
  useEffect(() => {
    loadCandidates()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filterLifecycle, filterKeywordId, filterDuplicate, searchText])

  function loadCandidates() {
    listCandidates({
      lifecycle_status: filterLifecycle || undefined,
      matched_keyword_entry_id: filterKeywordId,
      duplicate_status: filterDuplicate || undefined,
      search: searchText || undefined,
      page, page_size: pageSize,
    }).then((r) => {
      setCandidates(r.items)
      setTotal(r.total)
    }).catch(() => message.error('加载候选失败'))
  }

  // —— 启动扫描 ——
  async function handleScan() {
    if (!selectedTreeImportId) {
      message.warning('请先选择目录树批次')
      return
    }
    try {
      const resp = await startScanJob({
        tree_import_id: selectedTreeImportId,
        keyword_entry_ids: selectedKeywordIds.length ? selectedKeywordIds : undefined,
        per_keyword_limit: perKeywordLimit,
      })
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
    } catch (e: any) {
      if (e?.status === 409) message.warning('已有扫描任务在运行')
      else message.error('扫描启动失败')
    }
  }

  // —— 启动提交 ——
  async function handleSubmit() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) {
      message.warning('请先勾选要提交的候选项')
      return
    }
    try {
      const resp = await startSubmitJob({ candidate_ids: ids })
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
    } catch (e: any) {
      if (e?.status === 409) message.warning('已有提交任务在运行')
      else message.error('提交启动失败')
    }
  }

  // —— 单行操作 ——
  async function handleDismiss(cand: WhitelistCandidate) {
    try {
      await dismissCandidate(cand.id)
      message.success(`已丢弃 ${cand.source_title}`)
      loadCandidates()
    } catch (e: any) {
      message.error(e?.message ?? '丢弃失败')
    }
  }

  async function handleRestore(cand: WhitelistCandidate) {
    try {
      await restoreCandidate(cand.id)
      message.success('已恢复为 pending')
      loadCandidates()
    } catch (e: any) {
      message.error(e?.message ?? '恢复失败')
    }
  }

  async function handleBulkDismiss() {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) {
      message.warning('请先勾选要丢弃的候选项')
      return
    }
    try {
      const r = await bulkDismissCandidates(ids)
      message.success(`批量丢弃完成：${r.dismissed} 条已丢弃，${r.skipped} 条跳过`)
      setSelectedIds(new Set())
      loadCandidates()
    } catch (e: any) {
      message.error(e?.message ?? '批量丢弃失败')
    }
  }

  const columns: ColumnsType<WhitelistCandidate> = [
    { title: '资源标题', dataIndex: 'source_title', width: 280, ellipsis: true },
    { title: '命中关键词', dataIndex: 'matched_keyword', width: 120 },
    {
      title: 'duplicate', dataIndex: 'duplicate_status', width: 130,
      render: (s: string, row) => {
        const color = s === 'clear' ? 'green' : s === 'duplicate_found' ? 'orange' : 'red'
        return <Tag color={color} title={row.duplicate_reason ?? undefined}>{s}</Tag>
      },
    },
    {
      title: 'lifecycle', dataIndex: 'lifecycle_status', width: 120,
      render: (s: string) => {
        const color = s === 'pending' ? 'blue' : s === 'submitted' ? 'green' :
                       s === 'dismissed' ? 'default' : 'red'
        return <Tag color={color}>{s}</Tag>
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
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Title level={3}>白名单批处理</Title>

      <Card title="扫描控制台" className="soft-card">
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Space wrap>
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
          </Space>

          {scanJob && (
            <Card size="small" type="inner" title={`扫描进度（${scanJob.stage}）`}>
              <Progress
                percent={scanJob.total ? Math.round((scanJob.current / scanJob.total) * 100) : 0}
                status={scanJob.error ? 'exception' : scanJob.done ? 'success' : 'active'}
              />
              <div style={{ marginTop: 4 }}>{scanJob.current}/{scanJob.total}</div>
              {scanJob.summary && (
                <Space size="large" style={{ marginTop: 12 }}>
                  <Statistic title="新增" value={(scanJob.summary as any).new ?? 0} />
                  <Statistic title="更新" value={(scanJob.summary as any).updated ?? 0} />
                  <Statistic title="跳过" value={(scanJob.summary as any).skipped ?? 0} />
                  <Statistic title="失败关键词" value={(scanJob.summary as any).failed_keywords ?? 0} />
                </Space>
              )}
              {scanJob.error && <div style={{ color: 'red', marginTop: 8 }}>错误：{scanJob.error}</div>}
            </Card>
          )}
        </Space>
      </Card>

      <Card title="候选列表" className="soft-card"
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} onClick={loadCandidates}>刷新</Button>
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
        <Space style={{ marginBottom: 12 }} wrap>
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
        </Space>

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
              showSizeChanger={false}
              onChange={setPage}
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
              <Statistic title="成功" value={(submitJob.summary as any).submitted ?? 0} />
              <Statistic title="失败" value={(submitJob.summary as any).failed ?? 0} />
              <Statistic title="跳过" value={(submitJob.summary as any).skipped ?? 0} />
            </Space>
          )}
          {submitJob.error && <div style={{ color: 'red', marginTop: 8 }}>错误：{submitJob.error}</div>}
        </Card>
      )}
    </Space>
  )
}
