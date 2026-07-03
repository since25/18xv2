import { useState } from 'react'
import { Button, Card, Descriptions, Form, Input, Popconfirm, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  applyEmbyMetadataCandidate,
  confirmEmbyDeletePlan,
  getEmbyDeletePlan,
  getEmbyMetadataCandidate,
  type EmbyDeletePlan,
  type EmbyDeletePlanItem,
  type EmbyMetadataCandidate,
} from '@/api/embyMediaActions'
import PageScaffold from '@/layout/PageScaffold'

const { Text } = Typography

export default function EmbyMediaActionsPage() {
  const [planId, setPlanId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [plan, setPlan] = useState<EmbyDeletePlan | null>(null)
  const [candidate, setCandidate] = useState<EmbyMetadataCandidate | null>(null)
  const [loading, setLoading] = useState(false)
  const [messageApi, holder] = message.useMessage()

  const columns: ColumnsType<EmbyDeletePlanItem> = [
    { title: '分组', dataIndex: 'group', width: 130 },
    { title: '名称', dataIndex: 'display_name' },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '路径', dataIndex: 'target_path', ellipsis: true },
    { title: '阻止原因', dataIndex: 'blocked_reason', width: 180 },
  ]

  const loadPlan = async () => {
    setLoading(true)
    try {
      setPlan(await getEmbyDeletePlan(Number(planId)))
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载删除计划失败')
    } finally {
      setLoading(false)
    }
  }

  const confirmPlan = async () => {
    if (!plan) return
    setLoading(true)
    try {
      await confirmEmbyDeletePlan(plan.id)
      setPlan(await getEmbyDeletePlan(plan.id))
      void messageApi.success('删除计划已执行')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '执行删除计划失败')
    } finally {
      setLoading(false)
    }
  }

  const loadCandidate = async () => {
    setLoading(true)
    try {
      setCandidate(await getEmbyMetadataCandidate(Number(candidateId)))
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载名单候选失败')
    } finally {
      setLoading(false)
    }
  }

  const applyCandidate = async (values: { actors: string; note?: string }) => {
    if (!candidate) return
    const actors = values.actors.split('\n').map((item) => item.trim()).filter(Boolean)
    setLoading(true)
    try {
      setCandidate(await applyEmbyMetadataCandidate(candidate.id, actors, values.note || null))
      void messageApi.success('演员名单已写入')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '写入演员名单失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageScaffold title="Emby 媒体动作" description="审核 IINA 提交的删除计划和演员名单候选。">
      {holder}
      <div className="emby-media-actions-grid">
        <Card title="删除计划" className="soft-card">
          <Space.Compact>
            <Input placeholder="Plan ID" value={planId} onChange={(event) => setPlanId(event.target.value)} />
            <Button onClick={loadPlan} loading={loading}>加载</Button>
          </Space.Compact>
          {plan && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="标题">{plan.summary}</Descriptions.Item>
                <Descriptions.Item label="状态">{plan.status}</Descriptions.Item>
                <Descriptions.Item label="总数">{plan.total_items}</Descriptions.Item>
                <Descriptions.Item label="阻止">{plan.blocked_count}</Descriptions.Item>
              </Descriptions>
              <Table rowKey="id" size="small" columns={columns} dataSource={plan.items} pagination={false} />
              <Popconfirm
                title="确认执行删除计划"
                description="这会删除本地 STRM/整理产物，并通过 115 OpenAPI 删除网盘原文件。"
                okText="确认删除"
                cancelText="取消"
                onConfirm={confirmPlan}
                disabled={plan.status !== 'draft'}
              >
                <Button danger type="primary" disabled={plan.status !== 'draft'} loading={loading}>
                  确认执行删除
                </Button>
              </Popconfirm>
            </Space>
          )}
        </Card>

        <Card title="演员名单候选" className="soft-card">
          <Space.Compact>
            <Input placeholder="Candidate ID" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} />
            <Button onClick={loadCandidate} loading={loading}>加载</Button>
          </Space.Compact>
          {candidate && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="目标名单">{candidate.target_list}</Descriptions.Item>
                <Descriptions.Item label="状态">{candidate.status}</Descriptions.Item>
                <Descriptions.Item label="Item ID">{candidate.emby_item_id}</Descriptions.Item>
              </Descriptions>
              <Form layout="vertical" onFinish={applyCandidate}>
                <Form.Item name="actors" label="演员，每行一个" rules={[{ required: true, message: '请输入至少一个演员' }]}>
                  <Input.TextArea rows={5} />
                </Form.Item>
                <Form.Item name="note" label="备注">
                  <Input />
                </Form.Item>
                <Button type="primary" htmlType="submit" disabled={candidate.status === 'applied'} loading={loading}>
                  写入名单
                </Button>
              </Form>
              <Text type="secondary">完整 NFO 快照已保存在后端，后续页面可以继续展示演员明细。</Text>
            </Space>
          )}
        </Card>
      </div>
    </PageScaffold>
  )
}
