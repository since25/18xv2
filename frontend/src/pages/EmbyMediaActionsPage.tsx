import { useEffect, useState } from 'react'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Card, Checkbox, Descriptions, Input, Popconfirm, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  applyEmbyMetadataCandidate,
  confirmEmbyDeletePlan,
  createEmbyDeletePlanForScope,
  deleteEmbyDeletePlan,
  getEmbyDeletePlan,
  getEmbyMetadataCandidate,
  listEmbyDeletePlans,
  listEmbyMetadataCandidates,
  type EmbyDeleteScope,
  type EmbyDeletePlan,
  type EmbyDeletePlanItem,
  type EmbyMetadataCandidate,
  type EmbyMetadataTargetList,
} from '@/api/embyMediaActions'
import PageScaffold from '@/layout/PageScaffold'
import { formatDateTime } from '@/utils/format'

const { Text } = Typography
const DELETE_SCOPE_OPTIONS: Array<{ label: string; value: EmbyDeleteScope }> = [
  { label: '电影', value: 'movie' },
  { label: '单集', value: 'episode' },
  { label: '整季', value: 'season' },
  { label: '整剧', value: 'series' },
]
const METADATA_TARGET_TABS: Array<{ label: string; value: EmbyMetadataTargetList }> = [
  { label: '黑名单候选', value: 'emby_blacklist' },
  { label: '白名单候选', value: 'emby_whitelist' },
]

function parseId(value: string) {
  const trimmed = value.trim()
  if (!/^[1-9]\d*$/.test(trimmed)) {
    return null
  }
  return Number(trimmed)
}

function candidateTargetLabel(value: string) {
  return value === 'emby_whitelist' ? '白名单' : '黑名单'
}

function statusColor(value: string) {
  if (value === 'draft' || value === 'pending') return 'blue'
  if (value === 'applied' || value === 'completed' || value === 'deleted') return 'green'
  if (value === 'blocked' || value === 'failed') return 'red'
  if (value === 'running') return 'gold'
  return 'default'
}

export default function EmbyMediaActionsPage() {
  const [planId, setPlanId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [plan, setPlan] = useState<EmbyDeletePlan | null>(null)
  const [recentPlans, setRecentPlans] = useState<EmbyDeletePlan[]>([])
  const [candidateLists, setCandidateLists] = useState<Record<EmbyMetadataTargetList, EmbyMetadataCandidate[]>>({
    emby_blacklist: [],
    emby_whitelist: [],
  })
  const [candidate, setCandidate] = useState<EmbyMetadataCandidate | null>(null)
  const [selectedScope, setSelectedScope] = useState<EmbyDeleteScope>('episode')
  const [selectedActors, setSelectedActors] = useState<string[]>([])
  const [manualActors, setManualActors] = useState('')
  const [note, setNote] = useState('')
  const [planLoading, setPlanLoading] = useState(false)
  const [recentLoading, setRecentLoading] = useState(false)
  const [deletingPlanId, setDeletingPlanId] = useState<number | null>(null)
  const [scopeLoading, setScopeLoading] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [candidateListLoading, setCandidateListLoading] = useState<Record<EmbyMetadataTargetList, boolean>>({
    emby_blacklist: false,
    emby_whitelist: false,
  })
  const [applyLoading, setApplyLoading] = useState(false)
  const [messageApi, holder] = message.useMessage()

  const columns: ColumnsType<EmbyDeletePlanItem> = [
    { title: '分组', dataIndex: 'group', width: 130 },
    { title: '名称', dataIndex: 'display_name' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: '路径', dataIndex: 'target_path', ellipsis: true },
    { title: '115 ID', dataIndex: 'remote_file_id', width: 140, ellipsis: true },
    { title: '阻止原因', dataIndex: 'blocked_reason', width: 180 },
  ]

  const recentColumns: ColumnsType<EmbyDeletePlan> = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: '标题', dataIndex: 'summary' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: '范围', dataIndex: 'scope', width: 88 },
    { title: '条目', dataIndex: 'total_items', width: 80 },
    { title: '阻止', dataIndex: 'blocked_count', width: 80 },
    {
      title: '操作',
      width: 150,
      render: (_, item) => (
        <Space size={4}>
          <Button size="small" onClick={() => void loadPlanById(item.id)}>
            加载
          </Button>
          <Popconfirm
            title={`清除计划 #${item.id}？`}
            description="只删除计划记录，不会删除媒体文件。"
            okText="清除"
            cancelText="取消"
            onConfirm={() => void removePlan(item)}
            disabled={item.status === 'running'}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingPlanId === item.id}
              disabled={item.status === 'running'}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const candidateColumns: ColumnsType<EmbyMetadataCandidate> = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: '标题', dataIndex: 'snapshot_title', ellipsis: true, render: (value: string | null) => value || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: 'Item ID', dataIndex: 'emby_item_id', width: 130, ellipsis: true },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 160,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      width: 80,
      render: (_, item) => (
        <Button size="small" onClick={() => void loadCandidateById(item.id)}>
          加载
        </Button>
      ),
    },
  ]

  const loadRecentPlans = async () => {
    setRecentLoading(true)
    try {
      setRecentPlans(await listEmbyDeletePlans())
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载最近删除计划失败')
    } finally {
      setRecentLoading(false)
    }
  }

  const loadCandidateList = async (targetList: EmbyMetadataTargetList) => {
    setCandidateListLoading((previous) => ({ ...previous, [targetList]: true }))
    try {
      const candidates = await listEmbyMetadataCandidates(targetList)
      setCandidateLists((previous) => ({ ...previous, [targetList]: candidates }))
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : `加载${candidateTargetLabel(targetList)}候选失败`)
    } finally {
      setCandidateListLoading((previous) => ({ ...previous, [targetList]: false }))
    }
  }

  const loadCandidateLists = async () => {
    await Promise.all(METADATA_TARGET_TABS.map((item) => loadCandidateList(item.value)))
  }

  useEffect(() => {
    void loadRecentPlans()
    void loadCandidateLists()
  }, [])

  const removePlan = async (item: EmbyDeletePlan) => {
    setDeletingPlanId(item.id)
    try {
      await deleteEmbyDeletePlan(item.id)
      setRecentPlans((plans) => plans.filter((planItem) => planItem.id !== item.id))
      if (plan?.id === item.id) {
        setPlan(null)
        setPlanId('')
      }
      void messageApi.success(`已清除计划 #${item.id}`)
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '清除删除计划失败')
    } finally {
      setDeletingPlanId(null)
    }
  }

  const loadPlanById = async (id: number) => {
    setPlanLoading(true)
    try {
      const nextPlan = await getEmbyDeletePlan(id)
      setPlan(nextPlan)
      setPlanId(String(nextPlan.id))
      setSelectedScope(nextPlan.scope as EmbyDeleteScope)
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载删除计划失败')
    } finally {
      setPlanLoading(false)
    }
  }

  const loadPlan = async () => {
    const id = parseId(planId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Plan ID')
      return
    }
    await loadPlanById(id)
  }

  const confirmPlan = async () => {
    if (!plan) return
    setConfirmLoading(true)
    try {
      await confirmEmbyDeletePlan(plan.id)
      setPlan(await getEmbyDeletePlan(plan.id))
      void messageApi.success('删除计划已执行')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '执行删除计划失败')
    } finally {
      setConfirmLoading(false)
    }
  }

  const createScopedPlan = async () => {
    if (!plan) return
    setScopeLoading(true)
    try {
      const nextPlan = await createEmbyDeletePlanForScope(plan.id, selectedScope)
      setPlan(nextPlan)
      setPlanId(String(nextPlan.id))
      void messageApi.success('已生成新的范围删除计划')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '生成范围删除计划失败')
    } finally {
      setScopeLoading(false)
    }
  }

  const loadCandidateById = async (id: number) => {
    setCandidateLoading(true)
    try {
      const nextCandidate = await getEmbyMetadataCandidate(id)
      setCandidate(nextCandidate)
      setCandidateId(String(nextCandidate.id))
      setSelectedActors(nextCandidate.snapshot_actors.map((actor) => actor.name))
      setManualActors('')
      setNote('')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载名单候选失败')
    } finally {
      setCandidateLoading(false)
    }
  }

  const loadCandidate = async () => {
    const id = parseId(candidateId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Candidate ID')
      return
    }
    await loadCandidateById(id)
  }

  const applyCandidate = async () => {
    if (!candidate) return
    const actors = candidate.snapshot_actors.length
      ? selectedActors
      : manualActors.split('\n').map((item) => item.trim()).filter(Boolean)
    if (!actors.length) {
      void messageApi.warning('请选择或输入至少一个演员')
      return
    }
    setApplyLoading(true)
    try {
      const nextCandidate = await applyEmbyMetadataCandidate(candidate.id, actors, note || null)
      setCandidate(nextCandidate)
      setCandidateLists((previous) => ({
        ...previous,
        [nextCandidate.target_list as EmbyMetadataTargetList]: previous[nextCandidate.target_list as EmbyMetadataTargetList].map((item) =>
          item.id === nextCandidate.id ? nextCandidate : item,
        ),
      }))
      void messageApi.success('演员名单已写入')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '写入演员名单失败')
    } finally {
      setApplyLoading(false)
    }
  }

  return (
    <PageScaffold title="Emby 媒体动作" description="审核 IINA 提交的删除计划和演员名单候选。">
      {holder}
      <div className="emby-media-actions-grid">
        <Card title="删除计划" className="soft-card">
          <Space.Compact>
            <Input placeholder="Plan ID" value={planId} onChange={(event) => setPlanId(event.target.value)} />
            <Button onClick={loadPlan} loading={planLoading}>加载</Button>
            <Button icon={<ReloadOutlined />} onClick={() => void loadRecentPlans()} loading={recentLoading}>
              刷新最近
            </Button>
          </Space.Compact>
          <Table
            rowKey="id"
            size="small"
            columns={recentColumns}
            dataSource={recentPlans}
            loading={recentLoading}
            pagination={false}
            scroll={{ x: 680 }}
            className="emby-media-actions-section"
          />
          {plan && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="标题">{plan.summary}</Descriptions.Item>
                <Descriptions.Item label="状态">{plan.status}</Descriptions.Item>
                <Descriptions.Item label="范围">{plan.scope}</Descriptions.Item>
                <Descriptions.Item label="Item ID">{plan.emby_item_id}</Descriptions.Item>
                <Descriptions.Item label="总数">{plan.total_items}</Descriptions.Item>
                <Descriptions.Item label="阻止">{plan.blocked_count}</Descriptions.Item>
              </Descriptions>
              <Space wrap>
                <Select<EmbyDeleteScope>
                  style={{ width: 120 }}
                  value={selectedScope}
                  options={DELETE_SCOPE_OPTIONS}
                  onChange={setSelectedScope}
                />
                <Button
                  onClick={createScopedPlan}
                  loading={scopeLoading}
                  disabled={plan.status !== 'draft' || selectedScope === plan.scope}
                >
                  生成范围计划
                </Button>
                <Text type="secondary">生成新 draft，不会执行删除。</Text>
              </Space>
              <Table rowKey="id" size="small" columns={columns} dataSource={plan.items} pagination={false} scroll={{ x: 900 }} />
              <Popconfirm
                title="确认执行删除计划"
                description="这会删除本地 STRM/整理产物，并通过 115 OpenAPI 删除网盘原文件。"
                okText="确认删除"
                cancelText="取消"
                onConfirm={confirmPlan}
                disabled={plan.status !== 'draft'}
              >
                <Button danger type="primary" disabled={plan.status !== 'draft'} loading={confirmLoading}>
                  确认执行删除
                </Button>
              </Popconfirm>
            </Space>
          )}
        </Card>

        <Card
          title="演员名单候选"
          className="soft-card"
          extra={
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={candidateListLoading.emby_blacklist || candidateListLoading.emby_whitelist}
              onClick={() => void loadCandidateLists()}
            >
              刷新
            </Button>
          }
        >
          <Space.Compact>
            <Input placeholder="Candidate ID" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} />
            <Button onClick={loadCandidate} loading={candidateLoading}>加载</Button>
          </Space.Compact>
          <Tabs
            className="emby-media-actions-section"
            items={METADATA_TARGET_TABS.map((item) => ({
              key: item.value,
              label: item.label,
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  columns={candidateColumns}
                  dataSource={candidateLists[item.value]}
                  loading={candidateListLoading[item.value]}
                  pagination={false}
                  scroll={{ x: 660 }}
                />
              ),
            }))}
          />
          {candidate && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="标题">{candidate.snapshot_title || '-'}</Descriptions.Item>
                <Descriptions.Item label="目标名单">{candidateTargetLabel(candidate.target_list)}</Descriptions.Item>
                <Descriptions.Item label="状态"><Tag color={statusColor(candidate.status)}>{candidate.status}</Tag></Descriptions.Item>
                <Descriptions.Item label="Item ID">{candidate.emby_item_id}</Descriptions.Item>
                <Descriptions.Item label="NFO">{candidate.snapshot_nfo_path || '-'}</Descriptions.Item>
              </Descriptions>
              {candidate.snapshot_actors.length ? (
                <Checkbox.Group
                  className="emby-actor-checkboxes"
                  value={selectedActors}
                  onChange={(values) => setSelectedActors(values.map(String))}
                >
                  {candidate.snapshot_actors.map((actor) => (
                    <Checkbox key={actor.name} value={actor.name} className="emby-actor-checkbox">
                      <span>{actor.name}</span>
                      {actor.role ? <Text type="secondary"> {actor.role}</Text> : null}
                    </Checkbox>
                  ))}
                </Checkbox.Group>
              ) : (
                <Space direction="vertical" className="emby-media-actions-section" size={6}>
                  <Text>演员，每行一个</Text>
                  <Input.TextArea rows={5} value={manualActors} onChange={(event) => setManualActors(event.target.value)} />
                </Space>
              )}
              <Space direction="vertical" className="emby-media-actions-section" size={6}>
                <Text>备注</Text>
                <Input value={note} onChange={(event) => setNote(event.target.value)} />
              </Space>
              <Space>
                <Button type="primary" onClick={applyCandidate} disabled={candidate.status === 'applied'} loading={applyLoading}>
                  写入名单
                </Button>
                {candidate.snapshot_actors.length ? (
                  <Button onClick={() => setSelectedActors(candidate.snapshot_actors.map((actor) => actor.name))}>全选</Button>
                ) : null}
                {candidate.snapshot_actors.length ? <Button onClick={() => setSelectedActors([])}>清空</Button> : null}
              </Space>
            </Space>
          )}
        </Card>
      </div>
    </PageScaffold>
  )
}
