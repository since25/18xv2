import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudDownloadOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SaveOutlined,
  ScanOutlined,
} from '@ant-design/icons'

import { api } from '../api/client'
import type { ImportListResponse, TreeImport } from '../api/types'
import {
  createDedupeDeletePlan,
  getDedupeActiveJobs,
  getDedupeGroup,
  listDedupeDeletePlans,
  listDedupeGroups,
  reviewDedupeGroup,
  startDedupeConfirmJob,
  startDedupeDeleteJob,
  startDedupeScanJob,
  subscribeDedupeJob,
  type DedupeCandidate,
  type DedupeDeletePlan,
  type DedupeGroup,
  type DedupeJobFrame,
} from '../api/dedupe'

const { Text, Title } = Typography

const STATUS_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '待审核', value: 'pending_review' },
  { label: '已确认', value: 'confirmed' },
  { label: '已丢弃', value: 'dismissed' },
  { label: '已入计划', value: 'planned' },
]

const CONFIDENCE_OPTIONS = [
  { label: '全部等级', value: '' },
  { label: '文件名疑似', value: 'filename_suspected' },
  { label: '高概率', value: 'high_probability' },
  { label: '已验证', value: 'verified_duplicate' },
]

const ACTION_OPTIONS = [
  { label: '保留', value: 'keep' },
  { label: '删除', value: 'delete' },
  { label: '待定', value: 'undecided' },
]

const DEFAULT_EXTENSIONS = '.mp4,.mkv,.avi,.mov'

function emptyFrame(jobId: string, jobType: DedupeJobFrame['job_type'], total = 0): DedupeJobFrame {
  return {
    job_id: jobId,
    job_type: jobType,
    stage: '等待开始',
    current: 0,
    total,
    done: false,
    error: null,
    summary: null,
    started_at: new Date().toISOString(),
    finished_at: null,
  }
}

function confidenceTag(value: string) {
  const color = value === 'verified_duplicate' ? 'green' : value === 'high_probability' ? 'orange' : 'blue'
  return <Tag color={color}>{value}</Tag>
}

function statusTag(value: string) {
  const color = value === 'confirmed' ? 'green' : value === 'dismissed' ? 'default' : value === 'planned' ? 'purple' : 'blue'
  return <Tag color={color}>{value}</Tag>
}

function actionColor(value: string) {
  if (value === 'delete') return 'red'
  if (value === 'keep') return 'green'
  return 'default'
}

function progressPercent(frame: DedupeJobFrame | null) {
  if (!frame) return 0
  if (frame.done) return 100
  if (!frame.total) return 0
  return Math.round((frame.current / frame.total) * 100)
}

function parseLines(value?: string) {
  return (value ?? '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseExtensions(value?: string) {
  return (value ?? DEFAULT_EXTENSIONS)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export default function FileDedupePage() {
  const [form] = Form.useForm()
  const [imports, setImports] = useState<TreeImport[]>([])
  const [selectedImportId, setSelectedImportId] = useState<number>()
  const [groups, setGroups] = useState<DedupeGroup[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [statusFilter, setStatusFilter] = useState('')
  const [confidenceFilter, setConfidenceFilter] = useState('')
  const [selectedGroup, setSelectedGroup] = useState<DedupeGroup | null>(null)
  const [candidates, setCandidates] = useState<DedupeCandidate[]>([])
  const [candidateActions, setCandidateActions] = useState<Record<number, string>>({})
  const [reviewNote, setReviewNote] = useState('')
  const [deletePlans, setDeletePlans] = useState<DedupeDeletePlan[]>([])
  const [scanJob, setScanJob] = useState<DedupeJobFrame | null>(null)
  const [confirmJob, setConfirmJob] = useState<DedupeJobFrame | null>(null)
  const [deleteJob, setDeleteJob] = useState<DedupeJobFrame | null>(null)
  const [loadingGroups, setLoadingGroups] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const selectedDeleteIds = useMemo(
    () => candidates.filter((item) => candidateActions[item.id] === 'delete').map((item) => item.id),
    [candidateActions, candidates],
  )
  const selectedKeepIds = useMemo(
    () => candidates.filter((item) => candidateActions[item.id] === 'keep').map((item) => item.id),
    [candidateActions, candidates],
  )
  const reviewableIds = useMemo(
    () => candidates.filter((item) => candidateActions[item.id] !== 'undecided').map((item) => item.id),
    [candidateActions, candidates],
  )

  const loadGroups = useCallback(async () => {
    setLoadingGroups(true)
    try {
      const body = await listDedupeGroups({
        status: statusFilter || undefined,
        confidence_level: confidenceFilter || undefined,
        page,
        page_size: pageSize,
      })
      setGroups(body.items)
      setTotal(body.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载候选组失败')
    } finally {
      setLoadingGroups(false)
    }
  }, [confidenceFilter, page, pageSize, statusFilter])

  const loadDeletePlans = useCallback(async () => {
    try {
      const body = await listDedupeDeletePlans()
      setDeletePlans(body.items)
    } catch {
      setDeletePlans([])
    }
  }, [])

  const loadGroupDetail = useCallback(async (groupId: number) => {
    setLoadingDetail(true)
    try {
      const detail = await getDedupeGroup(groupId)
      setSelectedGroup(detail.group)
      setCandidates(detail.candidates)
      setReviewNote(detail.group.review_note ?? '')
      setCandidateActions(Object.fromEntries(
        detail.candidates.map((item) => [
          item.id,
          item.user_action !== 'undecided' ? item.user_action : item.suggested_action,
        ]),
      ))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载候选详情失败')
    } finally {
      setLoadingDetail(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api.get<ImportListResponse>('/imports/data?limit=100')
      .then((body) => {
        if (cancelled) return
        setImports(body.items)
        setSelectedImportId((current) => current ?? body.items.find((item) => item.source_type === 'file_upload')?.id ?? body.items[0]?.id)
      })
      .catch(() => message.error('加载目录树批次失败'))
    const timer = window.setTimeout(() => {
      if (!cancelled) void loadDeletePlans()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [loadDeletePlans])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadGroups()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadGroups])

  useEffect(() => {
    const unsubscribers: Array<() => void> = []
    getDedupeActiveJobs().then((jobs) => {
      if (jobs.scan) {
        setScanJob(jobs.scan)
        unsubscribers.push(subscribeDedupeJob(jobs.scan.job_id, (frame) => {
          if ('job_id' in frame) setScanJob(frame)
        }, () => void loadGroups()))
      }
      if (jobs.confirm) {
        setConfirmJob(jobs.confirm)
        unsubscribers.push(subscribeDedupeJob(jobs.confirm.job_id, (frame) => {
          if ('job_id' in frame) setConfirmJob(frame)
        }, () => {
          if (selectedGroup) void loadGroupDetail(selectedGroup.id)
          void loadGroups()
        }))
      }
      if (jobs.delete) {
        setDeleteJob(jobs.delete)
        unsubscribers.push(subscribeDedupeJob(jobs.delete.job_id, (frame) => {
          if ('job_id' in frame) setDeleteJob(frame)
        }, () => {
          void loadDeletePlans()
          void loadGroups()
        }))
      }
    }).catch(() => undefined)
    return () => {
      unsubscribers.forEach((unsubscribe) => unsubscribe())
    }
  }, [loadDeletePlans, loadGroupDetail, loadGroups, selectedGroup])

  async function handleScan(values: {
    scope_path_prefix?: string
    included_extensions?: string
    candidate_threshold?: number
    high_confidence_threshold?: number
    noise_words?: string
    regex_patterns?: string
  }) {
    if (!selectedImportId) {
      message.warning('请先选择目录树批次')
      return
    }
    try {
      const response = await startDedupeScanJob({
        tree_import_id: selectedImportId,
        scope_path_prefix: values.scope_path_prefix?.trim() || null,
        included_extensions: parseExtensions(values.included_extensions),
        candidate_threshold: values.candidate_threshold ?? 0.82,
        high_confidence_threshold: values.high_confidence_threshold ?? 0.92,
        noise_words: parseLines(values.noise_words),
        regex_patterns: parseLines(values.regex_patterns),
      })
      setScanJob(emptyFrame(response.job_id, 'scan'))
      subscribeDedupeJob(response.job_id, (frame) => {
        if (!('job_id' in frame)) {
          message.error(`SSE 错误：${frame.error}`)
          return
        }
        setScanJob(frame)
      }, (finalFrame) => {
        if (finalFrame.error) message.error(`扫描失败：${finalFrame.error}`)
        else message.success('本地扫描完成')
        void loadGroups()
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '扫描启动失败')
    }
  }

  async function saveReview() {
    if (!selectedGroup) return false
    await reviewDedupeGroup(selectedGroup.id, {
      keep_candidate_ids: selectedKeepIds,
      delete_candidate_ids: selectedDeleteIds,
      note: reviewNote || null,
    })
    message.success('审批已保存')
    await loadGroupDetail(selectedGroup.id)
    await loadGroups()
    return true
  }

  async function handleConfirmRemote() {
    if (!selectedGroup) return
    if (reviewableIds.length === 0) {
      message.warning('请先选择保留或删除项')
      return
    }
    try {
      const saved = await saveReview()
      if (!saved) return
      const response = await startDedupeConfirmJob({ candidate_ids: reviewableIds })
      setConfirmJob(emptyFrame(response.job_id, 'confirm', reviewableIds.length))
      subscribeDedupeJob(response.job_id, (frame) => {
        if ('job_id' in frame) setConfirmJob(frame)
      }, (finalFrame) => {
        if (finalFrame.error) message.error(`远端确认失败：${finalFrame.error}`)
        else message.success('远端确认完成')
        void loadGroupDetail(selectedGroup.id)
        void loadGroups()
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '远端确认启动失败')
    }
  }

  async function handleCreatePlan() {
    if (!selectedGroup) return
    if (selectedDeleteIds.length === 0) {
      message.warning('请先标记待删除项')
      return
    }
    try {
      const saved = await saveReview()
      if (!saved) return
      const response = await createDedupeDeletePlan({
        name: `去重删除计划 #${selectedGroup.id}`,
        candidate_ids: selectedDeleteIds,
        rate_limit_seconds: 2,
      })
      message.success(`删除计划已创建：#${response.plan_id}`)
      await loadDeletePlans()
      await loadGroups()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建删除计划失败')
    }
  }

  async function handleExecutePlan(planId: number) {
    try {
      const response = await startDedupeDeleteJob(planId, { confirm: true })
      setDeleteJob(emptyFrame(response.job_id, 'delete'))
      subscribeDedupeJob(response.job_id, (frame) => {
        if ('job_id' in frame) setDeleteJob(frame)
      }, (finalFrame) => {
        if (finalFrame.error) message.error(`删除计划执行失败：${finalFrame.error}`)
        else message.success('删除计划执行完成')
        void loadDeletePlans()
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除计划启动失败')
    }
  }

  const groupColumns: ColumnsType<DedupeGroup> = [
    {
      title: '代表文件名',
      dataIndex: 'representative_name',
      ellipsis: true,
      render: (value: string, row) => (
        <Button type="link" style={{ padding: 0, maxWidth: '100%' }} onClick={() => void loadGroupDetail(row.id)}>
          {value}
        </Button>
      ),
    },
    { title: '归一化', dataIndex: 'normalized_name', ellipsis: true },
    { title: '分数', dataIndex: 'score_max', width: 82, render: (value: number) => value.toFixed(2) },
    { title: '等级', dataIndex: 'confidence_level', width: 126, render: confidenceTag },
    { title: '状态', dataIndex: 'status', width: 112, render: statusTag },
  ]

  const candidateColumns: ColumnsType<DedupeCandidate> = [
    {
      title: '动作',
      width: 164,
      render: (_, row) => (
        <Radio.Group
          size="small"
          options={ACTION_OPTIONS}
          value={candidateActions[row.id] ?? 'undecided'}
          onChange={(event) => setCandidateActions((current) => ({ ...current, [row.id]: event.target.value }))}
        />
      ),
    },
    {
      title: '文件',
      dataIndex: 'raw_name',
      ellipsis: true,
      render: (value: string, row) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Text strong>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: row.raw_path }}>
            {row.raw_path}
          </Text>
        </Space>
      ),
    },
    {
      title: '建议',
      dataIndex: 'suggested_action',
      width: 86,
      render: (value: string) => <Tag color={actionColor(value)}>{value}</Tag>,
    },
    { title: '相似度', dataIndex: 'similarity_score', width: 78, render: (value: number) => value.toFixed(2) },
  ]

  const scanRunning = !!scanJob && !scanJob.done
  const confirmRunning = !!confirmJob && !confirmJob.done
  const deleteRunning = !!deleteJob && !deleteJob.done
  const latestPlan = deletePlans[0]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div className="page-header">
        <div>
          <Title level={3} style={{ margin: 0 }}>文件去重</Title>
          <Text type="secondary">扫描阶段只分析本地目录树，不调用 115 文件搜索 API。</Text>
        </div>
        <Space wrap>
          <Statistic title="候选组" value={total} />
          <Statistic title="删除计划" value={deletePlans.length} />
        </Space>
      </div>

      <Row gutter={[16, 16]} align="top">
        <Col xs={24} xl={6}>
          <Card title="扫描与规则" className="soft-card">
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                included_extensions: DEFAULT_EXTENSIONS,
                candidate_threshold: 0.82,
                high_confidence_threshold: 0.92,
              }}
              onFinish={(values) => void handleScan(values)}
            >
              <Form.Item label="目录树批次">
                <Select
                  value={selectedImportId}
                  onChange={setSelectedImportId}
                  options={imports.map((item) => ({
                    value: item.id,
                    label: `#${item.id} ${item.source_filename}`,
                  }))}
                  showSearch
                  optionFilterProp="label"
                />
              </Form.Item>
              <Form.Item name="scope_path_prefix" label="扫描范围">
                <Input placeholder="根目录/待整理" />
              </Form.Item>
              <Form.Item name="included_extensions" label="后缀">
                <Input />
              </Form.Item>
              <Row gutter={8}>
                <Col span={12}>
                  <Form.Item name="candidate_threshold" label="入队阈值">
                    <InputNumber min={0.1} max={1} step={0.01} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="high_confidence_threshold" label="高概率阈值">
                    <InputNumber min={0.1} max={1} step={0.01} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="noise_words" label="临时噪音词">
                <Input.TextArea rows={4} placeholder="每行一个" />
              </Form.Item>
              <Form.Item name="regex_patterns" label="临时正则">
                <Input.TextArea rows={3} placeholder="每行一个" />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<ScanOutlined />} loading={scanRunning} block>
                启动本地扫描
              </Button>
            </Form>
            {scanJob && (
              <div style={{ marginTop: 16 }}>
                <Progress percent={progressPercent(scanJob)} status={scanJob.error ? 'exception' : scanJob.done ? 'success' : 'active'} />
                <Text type="secondary">{scanJob.stage} · {scanJob.current}/{scanJob.total}</Text>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} xl={12}>
          <Card
            title="候选组"
            className="soft-card"
            extra={<Button icon={<ReloadOutlined />} onClick={() => void loadGroups()}>刷新</Button>}
          >
            <Space wrap style={{ marginBottom: 12 }}>
              <Select style={{ width: 140 }} value={statusFilter} options={STATUS_OPTIONS} onChange={(value) => { setStatusFilter(value); setPage(1) }} />
              <Select style={{ width: 140 }} value={confidenceFilter} options={CONFIDENCE_OPTIONS} onChange={(value) => { setConfidenceFilter(value); setPage(1) }} />
            </Space>
            <Table
              rowKey="id"
              loading={loadingGroups}
              columns={groupColumns}
              dataSource={groups}
              pagination={false}
              size="middle"
              scroll={{ x: 760 }}
              onRow={(row) => ({
                onClick: () => void loadGroupDetail(row.id),
              })}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
              <TablePagination
                current={page}
                pageSize={pageSize}
                total={total}
                onChange={(nextPage, nextSize) => {
                  setPage(nextPage)
                  setPageSize(nextSize)
                }}
              />
            </div>
          </Card>
        </Col>

        <Col xs={24} xl={6}>
          <Card title="详情与审批" className="soft-card">
            {!selectedGroup ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择候选组" />
            ) : (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Text strong ellipsis={{ tooltip: selectedGroup.representative_name }}>
                    {selectedGroup.representative_name}
                  </Text>
                  <Space wrap>
                    {confidenceTag(selectedGroup.confidence_level)}
                    {statusTag(selectedGroup.status)}
                    <Tag>{selectedGroup.score_max.toFixed(2)}</Tag>
                  </Space>
                </Space>
                <Table
                  rowKey="id"
                  size="small"
                  loading={loadingDetail}
                  columns={candidateColumns}
                  dataSource={candidates}
                  pagination={false}
                  scroll={{ x: 620 }}
                />
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Text type="secondary">审批备注</Text>
                  <Input.TextArea rows={2} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />
                </Space>
                <Space wrap>
                  <Button icon={<SaveOutlined />} onClick={() => void saveReview()}>
                    保存审批
                  </Button>
                  <Button icon={<FileSearchOutlined />} loading={confirmRunning} onClick={() => void handleConfirmRemote()}>
                    远端确认
                  </Button>
                  <Button icon={<CloudDownloadOutlined />} onClick={() => void handleCreatePlan()}>
                    生成删除计划
                  </Button>
                </Space>
                {confirmJob && (
                  <Progress size="small" percent={progressPercent(confirmJob)} status={confirmJob.error ? 'exception' : confirmJob.done ? 'success' : 'active'} />
                )}
              </Space>
            )}

            <Divider />
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              <Text strong>删除计划</Text>
              {!latestPlan ? (
                <Text type="secondary">暂无计划</Text>
              ) : (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag>#{latestPlan.id}</Tag>
                    {statusTag(latestPlan.status)}
                    <Tag>{latestPlan.total_items} 项</Tag>
                  </Space>
                  <Text ellipsis={{ tooltip: latestPlan.name }}>{latestPlan.name}</Text>
                  <Popconfirm
                    title="执行删除计划"
                    description="确认后会按计划逐个调用 115 删除接口。"
                    onConfirm={() => void handleExecutePlan(latestPlan.id)}
                  >
                    <Button danger icon={<DeleteOutlined />} loading={deleteRunning} disabled={latestPlan.status === 'completed'}>
                      二次确认并执行
                    </Button>
                  </Popconfirm>
                  {deleteJob && (
                    <Progress size="small" percent={progressPercent(deleteJob)} status={deleteJob.error ? 'exception' : deleteJob.done ? 'success' : 'active'} />
                  )}
                </Space>
              )}
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}

function TablePagination(props: {
  current: number
  pageSize: number
  total: number
  onChange: (page: number, pageSize: number) => void
}) {
  return (
    <Space>
      <Button
        disabled={props.current <= 1}
        onClick={() => props.onChange(Math.max(1, props.current - 1), props.pageSize)}
      >
        上一页
      </Button>
      <Text>{props.current} / {Math.max(1, Math.ceil(props.total / props.pageSize))}</Text>
      <Button
        disabled={props.current >= Math.ceil(props.total / props.pageSize)}
        onClick={() => props.onChange(props.current + 1, props.pageSize)}
      >
        下一页
      </Button>
    </Space>
  )
}
