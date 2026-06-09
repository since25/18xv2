import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Table, Tag, Button, Space, Typography, Card, Input, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { api } from '@/api/client'
import type { PlanDetail, PlanItem } from '@/api/types'

const { Title } = Typography

const CONFLICT_COLOR: Record<string, string> = {
  none: 'green',
  noop: 'default',
  duplicate_target: 'red',
  invalid_target: 'red',
}

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [plan, setPlan] = useState<PlanDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!id) return
      setLoading(true)
      api.get<PlanDetail>(`/plans/${id}`)
        .then(setPlan)
        .catch((e: Error) => message.error(e.message))
        .finally(() => setLoading(false))
    }, 0)

    return () => window.clearTimeout(timer)
  }, [id])

  const items = plan?.items.filter((item) =>
    !q || item.source_path.includes(q) || item.suggested_target_path.includes(q)
  ) ?? []

  const columns: ColumnsType<PlanItem> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '冲突',
      dataIndex: 'conflict_status',
      width: 130,
      render: (v) => <Tag color={CONFLICT_COLOR[v] ?? 'orange'}>{v}</Tag>,
    },
    { title: '动作', dataIndex: 'action_type', width: 70 },
    { title: '来源路径', dataIndex: 'source_path', ellipsis: true },
    { title: '目标路径', dataIndex: 'suggested_target_path', ellipsis: true },
    { title: '原因', dataIndex: 'reason', ellipsis: true, width: 200 },
    { title: '置信度', dataIndex: 'confidence', width: 80, render: (v) => v?.toFixed(2) },
  ]

  if (!plan && !loading) return <div>计划不存在。</div>

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Button onClick={() => navigate('/plans')}>← 返回</Button>
        <Title level={4} style={{ margin: 0 }}>计划 #{id} 详情</Title>
        {plan && <Tag>{plan.strategy_version}</Tag>}
        {plan && <Tag color={plan.dry_run ? 'gold' : 'green'}>{plan.dry_run ? 'dry' : 'real'}</Tag>}
      </Space>
      {plan && (
        <Card style={{ marginBottom: 12 }}>
          <Space wrap>
            <span>总项数：{plan.items.length}</span>
            <span>冲突项：{plan.items.filter((i: PlanItem) => i.conflict_status !== 'none' && i.conflict_status !== 'noop').length}</span>
            <span>可执行：{plan.items.filter((i: PlanItem) => i.conflict_status === 'none').length}</span>
            <span>noop：{plan.items.filter((i: PlanItem) => i.conflict_status === 'noop').length}</span>
          </Space>
        </Card>
      )}
      <Card>
        <Input
          placeholder="搜索路径"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ marginBottom: 12, width: 300 }}
        />
        <Table
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          size="small"
          pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
          rowClassName={(r) => (r.conflict_status !== 'none' && r.conflict_status !== 'noop') ? 'row-conflict' : ''}
        />
      </Card>
      <style>{`.row-conflict td { background: #fff1f0 !important; }`}</style>
    </div>
  )
}
