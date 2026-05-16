import { useEffect, useState } from 'react'
import { Timeline, Tag, Select, Button, Typography, Card, message, Space, Spin } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import type { JobDetail, ExecutionLog, PlanSummaryPage, PlanSummary } from '@/api/types'

const { Title } = Typography

export default function ExecutorPage() {
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [planId, setPlanId] = useState<number | null>(null)
  const [job, setJob] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<PlanSummaryPage>('/plans/data?limit=100')
      .then((d: PlanSummaryPage) => setPlans(d.items ?? []))
      .catch(() => {})
  }, [])

  const loadJob = async (jid: number) => {
    setLoading(true)
    try {
      const data = await api.get<JobDetail>(`/jobs/${jid}`)
      setJob(data)
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectPlan = async (pid: number) => {
    setPlanId(pid)
    setJob(null)
    const plan = plans.find((p) => p.id === pid)
    if (plan?.latest_job_id) {
      await loadJob(plan.latest_job_id)
    }
  }

  const timelineItems = job?.logs.map((log: ExecutionLog) => ({
    dot: log.success
      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
      : log.api_status === 'skipped'
      ? <MinusCircleOutlined style={{ color: '#999' }} />
      : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
    color: log.success ? 'green' : log.api_status === 'skipped' ? 'gray' : 'red',
    children: (
      <div>
        <Space wrap>
          <Tag color={log.success ? 'green' : log.api_status === 'skipped' ? 'default' : 'red'}>{log.api_status}</Tag>
          <Tag>{log.action_type}</Tag>
        </Space>
        <div style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4 }}>
          <div style={{ color: '#555' }}>{log.before_path}</div>
          {log.api_status !== 'skipped' && (
            <div style={{ color: '#1677ff' }}>→ {log.after_path}</div>
          )}
          {log.error_message && <div style={{ color: '#ff4d4f' }}>{log.error_message}</div>}
        </div>
      </div>
    ),
  })) ?? []

  const selectedPlan = planId ? plans.find((p) => p.id === planId) : null

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Title level={4} style={{ margin: 0 }}>执行日志</Title>
        <Select
          placeholder="选择计划" style={{ width: 320 }}
          options={plans.map((p) => ({ value: p.id, label: `#${p.id} · ${p.strategy_version} · ${p.item_count}项` }))}
          onChange={handleSelectPlan}
          showSearch
          filterOption={(input, opt) => String(opt?.label).includes(input)}
        />
        {selectedPlan?.latest_job_id && (
          <Button onClick={() => loadJob(selectedPlan.latest_job_id!)}>刷新日志</Button>
        )}
      </Space>

      {job && (
        <Card style={{ marginBottom: 16 }}>
          <Space wrap>
            <span>job #{job.id}</span>
            <Tag color={job.status === 'completed' ? 'green' : 'blue'}>{job.status}</Tag>
            <Tag color={job.dry_run ? 'gold' : 'green'}>{job.dry_run ? 'dry-run' : '真实执行'}</Tag>
            {job.started_at && <span style={{ color: '#888', fontSize: 12 }}>开始: {job.started_at.replace('T', ' ').slice(0, 19)}</span>}
            <span>成功: {job.logs.filter((l: ExecutionLog) => l.success).length}</span>
            <span>跳过: {job.logs.filter((l: ExecutionLog) => l.api_status === 'skipped').length}</span>
            <span>失败: {job.logs.filter((l: ExecutionLog) => !l.success && l.api_status !== 'skipped').length}</span>
          </Space>
        </Card>
      )}

      <Card>
        {loading && <Spin />}
        {!loading && !job && <div style={{ color: '#888' }}>请选择计划查看其最近一次执行日志。</div>}
        {!loading && job && timelineItems.length === 0 && <div style={{ color: '#888' }}>该任务暂无执行日志。</div>}
        {!loading && job && timelineItems.length > 0 && (
          <Timeline items={timelineItems} />
        )}
      </Card>
    </div>
  )
}
