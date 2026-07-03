import { useState } from 'react'
import { Button, Card, Checkbox, Descriptions, Input, Popconfirm, Select, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  applyEmbyMetadataCandidate,
  confirmEmbyDeletePlan,
  createEmbyDeletePlanForScope,
  getEmbyDeletePlan,
  getEmbyMetadataCandidate,
  type EmbyDeleteScope,
  type EmbyDeletePlan,
  type EmbyDeletePlanItem,
  type EmbyMetadataCandidate,
} from '@/api/embyMediaActions'
import PageScaffold from '@/layout/PageScaffold'

const { Text } = Typography
const DELETE_SCOPE_OPTIONS: Array<{ label: string; value: EmbyDeleteScope }> = [
  { label: '电影', value: 'movie' },
  { label: '单集', value: 'episode' },
  { label: '整季', value: 'season' },
  { label: '整剧', value: 'series' },
]

function parseId(value: string) {
  const trimmed = value.trim()
  if (!/^[1-9]\d*$/.test(trimmed)) {
    return null
  }
  return Number(trimmed)
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
  const [planLoading, setPlanLoading] = useState(false)
  const [scopeLoading, setScopeLoading] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [applyLoading, setApplyLoading] = useState(false)
  const [messageApi, holder] = message.useMessage()

  const columns: ColumnsType<EmbyDeletePlanItem> = [
    { title: '分组', dataIndex: 'group', width: 130 },
    { title: '名称', dataIndex: 'display_name' },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '路径', dataIndex: 'target_path', ellipsis: true },
    { title: '阻止原因', dataIndex: 'blocked_reason', width: 180 },
  ]

  const loadPlan = async () => {
    const id = parseId(planId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Plan ID')
      return
    }
    setPlanLoading(true)
    try {
      const nextPlan = await getEmbyDeletePlan(id)
      setPlan(nextPlan)
      setSelectedScope(nextPlan.scope as EmbyDeleteScope)
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载删除计划失败')
    } finally {
      setPlanLoading(false)
    }
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

  const loadCandidate = async () => {
    const id = parseId(candidateId)
    if (id == null) {
      void messageApi.warning('请输入有效的 Candidate ID')
      return
    }
    setCandidateLoading(true)
    try {
      const nextCandidate = await getEmbyMetadataCandidate(id)
      setCandidate(nextCandidate)
      setSelectedActors(nextCandidate.snapshot_actors.map((actor) => actor.name))
      setManualActors('')
      setNote('')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载名单候选失败')
    } finally {
      setCandidateLoading(false)
    }
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
      setCandidate(await applyEmbyMetadataCandidate(candidate.id, actors, note || null))
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
          </Space.Compact>
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
              <Table rowKey="id" size="small" columns={columns} dataSource={plan.items} pagination={false} />
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

        <Card title="演员名单候选" className="soft-card">
          <Space.Compact>
            <Input placeholder="Candidate ID" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} />
            <Button onClick={loadCandidate} loading={candidateLoading}>加载</Button>
          </Space.Compact>
          {candidate && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="标题">{candidate.snapshot_title || '-'}</Descriptions.Item>
                <Descriptions.Item label="目标名单">{candidate.target_list}</Descriptions.Item>
                <Descriptions.Item label="状态">{candidate.status}</Descriptions.Item>
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
