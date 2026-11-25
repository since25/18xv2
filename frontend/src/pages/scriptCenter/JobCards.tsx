import { useState } from 'react'
import { Button, Card, Modal, Space, Tag, Typography } from 'antd'

import type { ScriptJob } from '@/api/scriptJobs'
import type { ScriptRun } from '@/api/scriptRuns'
import { RUN_STATUS, describeRun } from './labels'

const { Text } = Typography

interface JobCardsProps {
  jobs: ScriptJob[]
  onRun: (job: ScriptJob, dryRun: boolean) => void
  onStop: (runId: number) => void
  onSettings: (job: ScriptJob) => void
  onShowLog: (run: ScriptRun) => void
}

interface PendingAction {
  title: string
  content?: string
  onOk: () => void
}

function scheduleText(job: ScriptJob) {
  if (job.executor !== '18x') return '由 Unraid 运行'
  if (!job.enabled) return '已停用'
  return `每天 ${job.run_time}`
}

function runningText(run: ScriptRun) {
  if (run.status === 'queued') return '排队中'
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(run.started_at).getTime()) / 60000))
  return `运行中 ${minutes} 分钟`
}

/** 每个脚本一张卡片：怎么调度、上次结果、正在跑的情况，以及运行/演练/停止/设置 */
export default function JobCards({ jobs, onRun, onStop, onSettings, onShowLog }: JobCardsProps) {
  const [pending, setPending] = useState<PendingAction | null>(null)

  const confirmRun = (job: ScriptJob, dryRun: boolean) => {
    if (dryRun) {
      setPending({ title: `演练运行「${job.label}」？不会提交或改动任何文件。`, onOk: () => onRun(job, true) })
      return
    }
    setPending({
      title: `立即真实运行「${job.label}」？`,
      content: job.job_name === 'DEL_SOMETHING' ? '会真实删除文件，删除后无法恢复。' : undefined,
      onOk: () => onRun(job, false),
    })
  }

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        {jobs.map((job) => {
          const active = job.active_run ?? null
          const latest = job.latest_run ?? null
          return (
            <Card key={job.job_name} size="small" title={job.label} data-testid={`job-card-${job.job_name}`}
              extra={<Tag>{scheduleText(job)}</Tag>}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {active ? (
                  <Tag color={RUN_STATUS[active.status].color}>{runningText(active)}</Tag>
                ) : latest ? (
                  <Space direction="vertical" size={0}>
                    <span>
                      上次：<Tag color={RUN_STATUS[latest.status].color}>{RUN_STATUS[latest.status].label}</Tag>
                      {latest.dry_run && <Tag>演练</Tag>}
                    </span>
                    <Text type="secondary">{describeRun(latest)}</Text>
                  </Space>
                ) : (
                  <Text type="secondary">还没有运行记录</Text>
                )}
                <Space wrap>
                  {active ? (
                    <>
                      <Button size="small" onClick={() => onShowLog(active)}>看日志</Button>
                      <Button size="small" danger
                        onClick={() => setPending({ title: '停止这次运行？', onOk: () => onStop(active.id) })}>
                        停止
                      </Button>
                    </>
                  ) : (
                    <>
                      {job.executor === '18x' && (
                        <Button size="small" type="primary" onClick={() => confirmRun(job, false)}>立即运行</Button>
                      )}
                      <Button size="small" onClick={() => confirmRun(job, true)}>演练</Button>
                    </>
                  )}
                  <Button size="small" onClick={() => onSettings(job)}>设置</Button>
                </Space>
              </Space>
            </Card>
          )
        })}
      </div>
      <Modal
        open={pending !== null}
        title={pending?.title}
        okText="确定"
        cancelText="取消"
        onOk={() => {
          pending?.onOk()
          setPending(null)
        }}
        onCancel={() => setPending(null)}
      >
        {pending?.content && <Text type="danger">{pending.content}</Text>}
      </Modal>
    </>
  )
}
