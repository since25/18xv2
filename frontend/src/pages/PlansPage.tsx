import { useCallback, useEffect, useState } from 'react'
import {
  Table, Button, Tag, Space, Typography, Card, Select, message,
  Popconfirm, Checkbox, Input, Collapse, Descriptions,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { api } from '@/api/client'
import type {
  PlanSummary,
  PlanSummaryPage,
  BatchPlanOperationLog,
  BatchPlanOperationResponse,
  JobDetail,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { Title } = Typography

const JOB_COLOR: Record<string, string> = {
  completed: 'green',
  blocked: 'orange',
  failed: 'red',
  none: 'default',
}

const JOB_STATUS_OPTIONS = [
  { value: 'none', label: '未执行 (none)' },
  { value: 'completed', label: '已完成 (completed)' },
  { value: 'blocked', label: '阻塞 (blocked)' },
  { value: 'failed', label: '失败 (failed)' },
]

export default function PlansPage() {
  const navigate = useNavigate()

  const [plans, setPlans]             = useState<PlanSummary[]>([])
  const [total, setTotal]             = useState(0)
  const [loading, setLoading]         = useState(false)
  const [page, setPage]               = useState(1)
  const [pageSize, setPageSize]       = useState(30)

  // 筛选
  const [statusFilter, setStatusFilter]     = useState<string | null>('none')
  const [showCompleted, setShowCompleted]   = useState(false)
  const [minItems, setMinItems]             = useState('')
  const [maxItems, setMaxItems]             = useState('')

  // 执行选项
  const [selectedIds, setSelectedIds]       = useState<number[]>([])
  const [confirmReal, setConfirmReal]       = useState(false)
  const [requestedBy, setRequestedBy]       = useState('')
  const [operatorNote, setOperatorNote]     = useState('')

  // 批量操作历史
  const [batchLogs, setBatchLogs]           = useState<BatchPlanOperationLog[]>([])

  const buildParams = useCallback((p: number) => {
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String((p - 1) * pageSize),
      include_completed: String(showCompleted),
    })
    if (statusFilter) params.set('latest_job_status', statusFilter)
    if (minItems)     params.set('min_item_count', minItems)
    if (maxItems)     params.set('max_item_count', maxItems)
    return params
  }, [maxItems, minItems, pageSize, showCompleted, statusFilter])

  const load = useCallback(async (p = page) => {
    setLoading(true)
    try {
      const data = await api.get<PlanSummaryPage>(`/plans/data?${buildParams(p)}`)
      setPlans(data.items)
      setTotal(data.total)
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [buildParams, page])

  const loadBatchLogs = useCallback(async () => {
    try {
      const data = await api.get<BatchPlanOperationLog[]>('/plans/batch-logs?limit=10')
      setBatchLogs(data)
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1)
      void load(1)
    }, 0)

    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadBatchLogs()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [loadBatchLogs])

  const execPayload = (dryRun: boolean) => ({
    dry_run: dryRun,
    confirm_real_run: !dryRun && confirmReal,
    requested_by: requestedBy || undefined,
    operator_note: operatorNote || undefined,
  })

  const executePlan = async (planId: number, dryRun: boolean) => {
    if (!dryRun && !confirmReal) { message.warning('请先勾选「确认真实执行」'); return }
    try {
      const job = await api.post<JobDetail>(`/plans/${planId}/execute`, execPayload(dryRun))
      if (job.status === 'completed') {
        message.success(dryRun ? `计划 #${planId} dry-run 完成` : `计划 #${planId} 执行完成`)
      } else {
        message.warning(`计划 #${planId} 执行结果：${job.status}`)
      }
      load()
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const batchExecute = async (dryRun: boolean) => {
    if (!selectedIds.length) { message.warning('请先勾选计划'); return }
    if (!dryRun && !confirmReal) { message.warning('请先勾选「确认真实执行」'); return }
    try {
      const res = await api.post<BatchPlanOperationResponse>('/plans/batch-execute', {
        plan_ids: selectedIds, ...execPayload(dryRun),
      })
      const completedCount = (res.jobs ?? []).filter((job) => job.status === 'completed').length
      const blockedCount = (res.jobs ?? []).filter((job) => job.status === 'blocked').length
      const failedCount = (res.jobs ?? []).filter((job) => job.status === 'failed').length + (res.errors?.length ?? 0)
      if (blockedCount || failedCount) {
        message.warning(`批量执行：完成 ${completedCount}，blocked ${blockedCount}，失败 ${failedCount}`)
      } else {
        message.success(`批量执行：${completedCount} 个完成`)
      }
      setSelectedIds([])
      load(); loadBatchLogs()
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const batchDelete = async () => {
    if (!selectedIds.length) return
    try {
      const res = await api.post<BatchPlanOperationResponse>('/plans/batch-delete', { plan_ids: selectedIds })
      message.success(`删除 ${res.processed_count} 个计划`)
      setSelectedIds([])
      load(); loadBatchLogs()
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const columns: ColumnsType<PlanSummary> = [
    { title: 'ID', dataIndex: 'id', width: 65 },
    { title: '策略', dataIndex: 'strategy_version', ellipsis: true },
    { title: '项数', dataIndex: 'item_count', width: 60 },
    {
      title: '快照',
      dataIndex: 'dry_run',
      width: 65,
      render: (v: boolean) => <Tag color={v ? 'gold' : 'green'}>{v ? 'dry' : 'real'}</Tag>,
    },
    {
      title: '最近执行',
      dataIndex: 'latest_job_status',
      width: 100,
      render: (v: string | null) => {
        const normalized = v ?? 'none'
        return <Tag color={JOB_COLOR[normalized] ?? 'default'}>{normalized}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 165,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      width: 190,
      render: (_: unknown, r: PlanSummary) => (
        <Space size={4}>
          <Button size="small" onClick={() => navigate(`/plans/${r.id}`)}>详情</Button>
          <Button size="small" onClick={() => executePlan(r.id, true)}>Dry-run</Button>
          <Popconfirm
            title="确认真实执行？此操作不可撤销。"
            onConfirm={() => executePlan(r.id, false)}
            disabled={!confirmReal}
          >
            <Button size="small" danger disabled={!confirmReal}>执行</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 筛选和批量操作 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Title level={4} style={{ margin: 0 }}>整理计划</Title>
        <Select
          placeholder="最近执行结果" style={{ width: 180 }} allowClear
          options={JOB_STATUS_OPTIONS}
          value={statusFilter ?? undefined}
          onChange={(v: string | undefined) => setStatusFilter(v ?? null)}
        />
        <Select
          style={{ width: 120 }}
          value={pageSize}
          options={[20, 30, 50, 100].map((value) => ({ value, label: `${value} / 页` }))}
          onChange={(value: number) => setPageSize(value)}
        />
        <Input placeholder="最少项数" style={{ width: 90 }} value={minItems} onChange={(e) => setMinItems(e.target.value)} />
        <Input placeholder="最多项数" style={{ width: 90 }} value={maxItems} onChange={(e) => setMaxItems(e.target.value)} />
        <Checkbox checked={showCompleted} onChange={(e) => setShowCompleted(e.target.checked)}>显示已完成</Checkbox>
        <Button onClick={() => load()}>刷新</Button>
      </Space>

      {/* 执行选项 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Input placeholder="执行人（可选）" style={{ width: 130 }} value={requestedBy} onChange={(e) => setRequestedBy(e.target.value)} />
          <Input placeholder="备注（可选）" style={{ width: 180 }} value={operatorNote} onChange={(e) => setOperatorNote(e.target.value)} />
          <Checkbox
            checked={confirmReal}
            onChange={(e) => setConfirmReal(e.target.checked)}
            style={{ color: confirmReal ? '#ff4d4f' : undefined }}
          >
            确认真实执行（危险操作）
          </Checkbox>
          <Button onClick={() => batchExecute(true)} disabled={!selectedIds.length}>
            批量 Dry-run ({selectedIds.length})
          </Button>
          <Button danger onClick={() => batchExecute(false)} disabled={!selectedIds.length || !confirmReal}>
            批量真实执行
          </Button>
          <Popconfirm title={`删除 ${selectedIds.length} 个计划？`} onConfirm={batchDelete} disabled={!selectedIds.length}>
            <Button disabled={!selectedIds.length}>批量删除</Button>
          </Popconfirm>
          <Button onClick={() => setSelectedIds(plans.map((p) => p.id))}>全选当前页</Button>
          <Button onClick={() => setSelectedIds([])}>清空勾选</Button>
        </Space>
      </Card>

      {/* 计划表格 */}
      <Card bodyStyle={{ padding: 0 }}>
        <Table
          rowKey="id"
          dataSource={plans}
          columns={columns}
          loading={loading}
          size="small"
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: (keys) => setSelectedIds(keys as number[]),
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [20, 30, 50, 100],
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, size) => {
              if (size !== pageSize) {
                setPageSize(size)
                setPage(1)
                void load(1)
                return
              }
              setPage(p)
              void load(p)
            },
          }}
        />
      </Card>

      {/* 批量操作历史 */}
      {batchLogs.length > 0 && (
        <Card title="最近批量操作记录" style={{ marginTop: 16 }} size="small">
          <Collapse size="small"
            items={batchLogs.map((log) => ({
              key: log.id,
              label: (
                <Space>
                  <Tag>{log.action}</Tag>
                  <span>#{log.id}</span>
                  <span style={{ color: '#888', fontSize: 12 }}>{formatDateTime(log.created_at)}</span>
                  <span>请求 {log.requested_count} / 完成 {log.processed_count}</span>
                  {log.errors?.length > 0 && <Tag color="red">失败 {log.errors.length}</Tag>}
                </Space>
              ),
              children: (
                <Descriptions size="small" column={2} bordered>
                  <Descriptions.Item label="执行人">{log.requested_by ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="备注">{log.operator_note ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="完成计划 ID">
                    {log.processed_plan_ids?.join(', ') || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="跳过 ID">
                    {log.skipped_plan_ids?.join(', ') || '-'}
                  </Descriptions.Item>
                  {log.errors?.length > 0 && (
                    <Descriptions.Item label="错误" span={2}>
                      {log.errors.slice(0, 5).map((e, i) => <div key={i} style={{ color: '#ff4d4f', fontSize: 12 }}>{e}</div>)}
                    </Descriptions.Item>
                  )}
                </Descriptions>
              ),
            }))}
          />
        </Card>
      )}
    </div>
  )
}
