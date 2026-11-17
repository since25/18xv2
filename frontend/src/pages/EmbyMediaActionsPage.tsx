import { useState } from 'react'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Card, Checkbox, Descriptions, Input, Popconfirm, Select, Space, Table, Tabs, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  applyEmbyMetadataCandidate,
  confirmEmbyDeletePlan,
  createEmbyDeletePlanForScope,
  deleteEmbyDeletePlan,
  deleteEmbyMetadataCandidate,
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
import DataToolbar from '@/layout/DataToolbar'
import StatusTag from '@/components/StatusTag'
import TimeText from '@/components/TimeText'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'

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

export default function EmbyMediaActionsPage() {
  const [planId, setPlanId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [plan, setPlan] = useState<EmbyDeletePlan | null>(null)
  const [candidate, setCandidate] = useState<EmbyMetadataCandidate | null>(null)
  const [selectedScope, setSelectedScope] = useState<EmbyDeleteScope>('episode')
  const [selectedActors, setSelectedActors] = useState<string[]>([])
  const [manualActors, setManualActors] = useState('')
  const [note, setNote] = useState('')
  const [deletingPlanId, setDeletingPlanId] = useState<number | null>(null)
  const [deletingCandidateId, setDeletingCandidateId] = useState<number | null>(null)
  const [messageApi, holder] = message.useMessage()

  // 出错提示走本页的 messageApi；401 交给全局登录过期处理
  const showError = (error: unknown, fallback: string) => {
    if ((error as { status?: number } | null)?.status === 401) return
    void messageApi.error(error instanceof Error ? error.message : fallback)
  }

  // 读取出错时提示后继续抛出，交给取数工具保留旧数据
  const failWith = (fallback: string) => (error: unknown): never => {
    showError(error, fallback)
    throw error
  }

  const recentQuery = useApiQuery(
    () => listEmbyDeletePlans().catch(failWith('加载最近删除计划失败')),
    [],
    { silent: true, initialData: [] as EmbyDeletePlan[] },
  )
  const { data: recentPlans, loading: recentLoading, reload: loadRecentPlans, setData: setRecentPlans } = recentQuery

  // 黑名单、白名单候选各自加载，各自显示加载状态
  const blacklistQuery = useApiQuery(
    () => listEmbyMetadataCandidates('emby_blacklist')
      .catch(failWith(`加载${candidateTargetLabel('emby_blacklist')}候选失败`)),
    [],
    { silent: true, initialData: [] as EmbyMetadataCandidate[] },
  )
  const whitelistQuery = useApiQuery(
    () => listEmbyMetadataCandidates('emby_whitelist')
      .catch(failWith(`加载${candidateTargetLabel('emby_whitelist')}候选失败`)),
    [],
    { silent: true, initialData: [] as EmbyMetadataCandidate[] },
  )
  const candidateQueries = { emby_blacklist: blacklistQuery, emby_whitelist: whitelistQuery }
  const candidateLists: Record<EmbyMetadataTargetList, EmbyMetadataCandidate[]> = {
    emby_blacklist: blacklistQuery.data,
    emby_whitelist: whitelistQuery.data,
  }
  const candidateListLoading: Record<EmbyMetadataTargetList, boolean> = {
    emby_blacklist: blacklistQuery.loading,
    emby_whitelist: whitelistQuery.loading,
  }

  const columns: ColumnsType<EmbyDeletePlanItem> = [
    { title: '分组', dataIndex: 'group', width: 130 },
    { title: '名称', dataIndex: 'display_name' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (value: string) => <StatusTag domain="workflow" value={value} />,
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
      render: (value: string) => <StatusTag domain="workflow" value={value} />,
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
      render: (value: string) => <StatusTag domain="workflow" value={value} />,
    },
    { title: 'Item ID', dataIndex: 'emby_item_id', width: 130, ellipsis: true },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 160,
      render: (value: string) => <TimeText value={value} />,
    },
    {
      title: '操作',
      width: 130,
      render: (_, item) => (
        <Space size={4}>
          <Button size="small" onClick={() => void loadCandidateById(item.id)}>
            加载
          </Button>
          <Popconfirm
            title={`清除候选 #${item.id}？`}
            description="只删除候选记录，不会撤销已写入的名单。"
            okText="清除"
            cancelText="取消"
            onConfirm={() => void removeCandidate(item)}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingCandidateId === item.id}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const loadCandidateLists = async () => {
    await Promise.all(METADATA_TARGET_TABS.map((item) => candidateQueries[item.value].reload()))
  }

  // 以下操作的出错提示文字各不相同，统一设为 silent 后自行提示
  const deletePlanAction = useApiAction(deleteEmbyDeletePlan, { silent: true })

  const removePlan = async (item: EmbyDeletePlan) => {
    setDeletingPlanId(item.id)
    const result = await deletePlanAction.run(item.id)
    setDeletingPlanId(null)
    if (!result.ok) {
      showError(result.error, '清除删除计划失败')
      return
    }
    setRecentPlans((plans = []) => plans.filter((planItem) => planItem.id !== item.id))
    if (plan?.id === item.id) {
      setPlan(null)
      setPlanId('')
    }
    void messageApi.success(`已清除计划 #${item.id}`)
  }

  const planAction = useApiAction(getEmbyDeletePlan, { silent: true })
  const planLoading = planAction.loading

  const loadPlanById = async (id: number) => {
    const result = await planAction.run(id)
    if (!result.ok) {
      showError(result.error, '加载删除计划失败')
      return
    }
    const nextPlan = result.data
    setPlan(nextPlan)
    setPlanId(String(nextPlan.id))
    setSelectedScope(nextPlan.scope as EmbyDeleteScope)
  }

  const loadPlan = async () => {
    const id = parseId(planId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Plan ID')
      return
    }
    await loadPlanById(id)
  }

  // 执行后重新读取计划；两步任一出错都按“执行删除计划失败”提示
  const confirmAction = useApiAction(async (id: number) => {
    await confirmEmbyDeletePlan(id)
    return getEmbyDeletePlan(id)
  }, { silent: true })
  const confirmLoading = confirmAction.loading

  const confirmPlan = async () => {
    if (!plan) return
    const result = await confirmAction.run(plan.id)
    if (!result.ok) {
      showError(result.error, '执行删除计划失败')
      return
    }
    setPlan(result.data)
    void messageApi.success('删除计划已执行')
  }

  const scopeAction = useApiAction(createEmbyDeletePlanForScope, { silent: true })
  const scopeLoading = scopeAction.loading

  const createScopedPlan = async () => {
    if (!plan) return
    const result = await scopeAction.run(plan.id, selectedScope)
    if (!result.ok) {
      showError(result.error, '生成范围删除计划失败')
      return
    }
    const nextPlan = result.data
    setPlan(nextPlan)
    setPlanId(String(nextPlan.id))
    void messageApi.success('已生成新的范围删除计划')
  }

  const candidateAction = useApiAction(getEmbyMetadataCandidate, { silent: true })
  const candidateLoading = candidateAction.loading

  const loadCandidateById = async (id: number) => {
    const result = await candidateAction.run(id)
    if (!result.ok) {
      showError(result.error, '加载名单候选失败')
      return
    }
    const nextCandidate = result.data
    setCandidate(nextCandidate)
    setCandidateId(String(nextCandidate.id))
    setSelectedActors(nextCandidate.snapshot_actors.map((actor) => actor.name))
    setManualActors('')
    setNote('')
  }

  const deleteCandidateAction = useApiAction(deleteEmbyMetadataCandidate, { silent: true })

  const removeCandidate = async (item: EmbyMetadataCandidate) => {
    setDeletingCandidateId(item.id)
    const result = await deleteCandidateAction.run(item.id)
    setDeletingCandidateId(null)
    if (!result.ok) {
      showError(result.error, '清除名单候选失败')
      return
    }
    for (const query of [blacklistQuery, whitelistQuery]) {
      query.setData((previous = []) => previous.filter((candidateItem) => candidateItem.id !== item.id))
    }
    if (candidate?.id === item.id) {
      setCandidate(null)
      setCandidateId('')
      setSelectedActors([])
      setManualActors('')
      setNote('')
    }
    void messageApi.success(`已清除候选 #${item.id}`)
  }

  const loadCandidate = async () => {
    const id = parseId(candidateId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Candidate ID')
      return
    }
    await loadCandidateById(id)
  }

  const applyAction = useApiAction(applyEmbyMetadataCandidate, { silent: true })
  const applyLoading = applyAction.loading

  const applyCandidate = async () => {
    if (!candidate) return
    const actors = candidate.snapshot_actors.length
      ? selectedActors
      : manualActors.split('\n').map((item) => item.trim()).filter(Boolean)
    if (!actors.length) {
      void messageApi.warning('请选择或输入至少一个演员')
      return
    }
    const result = await applyAction.run(candidate.id, actors, note || null)
    if (!result.ok) {
      showError(result.error, '写入演员名单失败')
      return
    }
    const nextCandidate = result.data
    setCandidate(nextCandidate)
    candidateQueries[nextCandidate.target_list as EmbyMetadataTargetList].setData((previous = []) => previous.map((item) =>
      item.id === nextCandidate.id ? nextCandidate : item,
    ))
    void messageApi.success('演员名单已写入')
  }

  return (
    <PageScaffold title="Emby 媒体动作" description="审核 IINA 提交的删除计划和演员名单候选。">
      {holder}
      <div className="emby-media-actions-grid">
        <Card title="删除计划" className="soft-card">
          <DataToolbar left={<Space.Compact>
            <Input placeholder="Plan ID" value={planId} onChange={(event) => setPlanId(event.target.value)} />
            <Button onClick={loadPlan} loading={planLoading}>加载</Button>
            <Button icon={<ReloadOutlined />} onClick={() => void loadRecentPlans()} loading={recentLoading}>
              刷新最近
            </Button>
          </Space.Compact>} />
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
          <DataToolbar left={<Space.Compact>
            <Input placeholder="Candidate ID" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} />
            <Button onClick={loadCandidate} loading={candidateLoading}>加载</Button>
          </Space.Compact>} />
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
                <Descriptions.Item label="状态"><StatusTag domain="workflow" value={candidate.status} /></Descriptions.Item>
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
                <Popconfirm
                  title={`清除候选 #${candidate.id}？`}
                  description="只删除候选记录，不会撤销已写入的名单。"
                  okText="清除"
                  cancelText="取消"
                  onConfirm={() => void removeCandidate(candidate)}
                >
                  <Button danger icon={<DeleteOutlined />} loading={deletingCandidateId === candidate.id}>
                    清除候选
                  </Button>
                </Popconfirm>
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
