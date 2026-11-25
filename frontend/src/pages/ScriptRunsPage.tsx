import { useEffect, useState } from 'react'
import { Alert, Input, Space, Table, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getScriptRunSummary,
  listScriptRunItems,
  listScriptRuns,
  stopScriptRun,
  type ScriptRun,
  type ScriptRunDay,
  type ScriptRunItem,
  type ScriptRunItemKind,
  type ScriptRunStatus,
  type ScriptRunSummary,
} from '@/api/scriptRuns'
import { listScriptJobs, startScriptJobRun, type ScriptJob } from '@/api/scriptJobs'
import PageScaffold from '@/layout/PageScaffold'
import SurfacePanel from '@/layout/SurfacePanel'
import TimeText from '@/components/TimeText'
import { useApiQuery } from '@/hooks/useApiQuery'
import JobCards from './scriptCenter/JobCards'
import JobSettingsDrawer from './scriptCenter/JobSettingsDrawer'
import RunLogPanel from './scriptCenter/RunLogPanel'
import { KIND_LABELS, RUN_STATUS, TODAY_STATUS, describeRun, fullCounts, scriptLabel } from './scriptCenter/labels'

const { Text } = Typography
const PAGE_SIZE = 50
// 有任务在跑时，卡片和运行记录每 5 秒刷新一次
const ACTIVE_REFRESH_MS = 5000
const TRIGGER_LABELS: Record<string, string | null> = { manual: '手动', scheduled: null, report: null }

function DayBars({ title, days, valueOf }: { title: string; days: ScriptRunDay[]; valueOf: (day: ScriptRunDay) => number }) {
  const max = Math.max(1, ...days.map(valueOf))
  return (
    <div>
      <Text strong>{title}</Text>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        {days.map((day) => {
          const value = valueOf(day)
          const date = day.date.slice(5).replace('-', '/')
          return (
            <Tooltip key={day.date} title={day.has_run ? `${date} ${title} ${value}` : `${date} 没有运行记录`}>
              <div style={{ flex: 1, minWidth: 0, textAlign: 'center' }} data-testid={`bar-${title}-${day.date}`}>
                <div style={{ height: 110, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
                  <Text className="numeric-text" type={day.has_run ? undefined : 'secondary'} style={{ fontSize: 12 }}>
                    {day.has_run ? value : '无记录'}
                  </Text>
                  {day.has_run && (
                    <div
                      style={{
                        // 为 0 时保留一条细线，和“无记录”区分开
                        height: value === 0 ? 2 : `${Math.max(4, (value / max) * 88)}px`,
                        background: 'var(--app-brand)',
                        borderRadius: value === 0 ? 0 : '4px 4px 0 0',
                      }}
                    />
                  )}
                </div>
                <div style={{ borderTop: '1px solid var(--app-border-strong)', paddingTop: 4 }}>
                  <Text type="secondary" className="numeric-text" style={{ fontSize: 12 }}>{date}</Text>
                </div>
              </div>
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}

function RunItems({ run }: { run: ScriptRun }) {
  const [kind, setKind] = useState<ScriptRunItemKind | undefined>(undefined)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [kindCounts, setKindCounts] = useState<Partial<Record<ScriptRunItemKind, number>> | null>(null)

  const available = KIND_LABELS.filter(([key]) => (kindCounts?.[key] ?? 0) > 0)
  // 第一次请求拿到各类数量后，默认选中第一个有内容的类别
  const activeKind = kind ?? available[0]?.[0]

  // 名单：出错不弹提示，错误文字显示在提示条里。
  // 各类数量是整次运行的统计（与类别、搜索无关），取到后记下来决定默认类别
  const itemsQuery = useApiQuery(
    () => listScriptRunItems(run.id, { kind: activeKind, q: q || undefined, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      .then((res) => {
        setKindCounts(res.kind_counts)
        return { total: res.total, items: res.items }
      }),
    [run.id, activeKind, q, page],
    { silent: true, initialData: { total: 0, items: [] as ScriptRunItem[] } },
  )
  const data = itemsQuery.data
  const loading = itemsQuery.loading
  const error = itemsQuery.error ? itemsQuery.error.message : null

  if (error) return <Alert type="error" showIcon message={`名单加载失败：${error}`} />
  if (kindCounts && available.length === 0) return <Text type="secondary">这次运行没有名单</Text>

  const isMove = activeKind === 'moved_new' || activeKind === 'moved_rescan'
  const isPost = run.script_name === 'sehuatang'
  const columns: ColumnsType<ScriptRunItem> = isPost
    ? [
        {
          title: '帖子',
          dataIndex: 'path',
          render: (value: string | null, item) =>
            item.target_path ? <a href={item.target_path} target="_blank" rel="noreferrer">{value ?? item.target_path}</a> : value ?? '-',
        },
        { title: '命中词 / 说明', key: 'reason', width: 240, render: (_, item) => item.keyword ?? item.message ?? '-' },
      ]
    : isMove
    ? [
        { title: '来源', dataIndex: 'path', render: (value: string | null) => value ?? '-' },
        { title: '目标', dataIndex: 'target_path', render: (value: string | null) => value ?? '-' },
        { title: '关键词', dataIndex: 'keyword', width: 180, render: (value: string | null) => value ?? '-' },
      ]
    : [{ title: '内容', key: 'content', render: (_, item) => item.path ?? item.message ?? '-' }]

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {run.items_truncated && <Alert type="warning" showIcon message="这次运行的名单超过上限，只保存了一部分，上面的数量仍然准确" />}
      <Tabs
        size="small"
        activeKey={activeKind}
        onChange={(key) => {
          setKind(key as ScriptRunItemKind)
          setPage(1)
        }}
        items={available.map(([key, label]) => ({ key, label: `${label} ${kindCounts?.[key] ?? 0}` }))}
      />
      <Input.Search
        allowClear
        placeholder={isPost ? '在当前类别里搜索标题' : '在当前类别里搜索路径'}
        style={{ maxWidth: 360 }}
        onSearch={(value) => {
          setQ(value.trim())
          setPage(1)
        }}
      />
      <Table<ScriptRunItem>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: data.total,
          showSizeChanger: false,
          onChange: (next) => {
            setPage(next)
          },
        }}
      />
    </Space>
  )
}

function RunDetail({ run }: { run: ScriptRun }) {
  if (!run.has_log) return <RunItems run={run} />
  return (
    <Tabs
      size="small"
      items={[
        { key: 'items', label: '名单', children: <RunItems run={run} /> },
        { key: 'log', label: '日志', children: <RunLogPanel key={run.id} runId={run.id} /> },
      ]}
    />
  )
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err)
}

export default function ScriptRunsPage() {
  const [page, setPage] = useState(1)
  const [settingsJob, setSettingsJob] = useState<ScriptJob | null>(null)
  const [logRun, setLogRun] = useState<ScriptRun | null>(null)

  const jobsQuery = useApiQuery(() => listScriptJobs().then((res) => res.items), [], {
    silent: true,
    initialData: [] as ScriptJob[],
  })
  const jobs = jobsQuery.data
  const jobsError = jobsQuery.error ? jobsQuery.error.message : null

  // 统计与运行记录：出错都不弹提示，错误文字显示在各自的提示条里
  const summaryQuery = useApiQuery(() => getScriptRunSummary() as Promise<ScriptRunSummary | null>, [], {
    silent: true,
    initialData: null,
  })
  const summary = summaryQuery.data
  const summaryError = summaryQuery.error ? summaryQuery.error.message : null

  const runsQuery = useApiQuery(
    () => listScriptRuns({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
    [page],
    { silent: true, initialData: { total: 0, items: [] as ScriptRun[] } },
  )
  const runs = runsQuery.data
  const runsError = runsQuery.error ? runsQuery.error.message : null
  const runsLoading = runsQuery.loading

  const reloadAll = () => {
    void jobsQuery.reload({ silent: true })
    void runsQuery.reload({ silent: true })
    void summaryQuery.reload({ silent: true })
  }

  const hasActive = jobs.some((job) => job.active_run)
  useEffect(() => {
    if (!hasActive) return undefined
    const timer = setInterval(() => {
      void jobsQuery.reload({ silent: true })
      void runsQuery.reload({ silent: true })
    }, ACTIVE_REFRESH_MS)
    return () => clearInterval(timer)
    // reload 引用稳定；只在“是否有任务在跑”变化时重设定时器
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasActive])

  const handleRun = async (job: ScriptJob, dryRun: boolean) => {
    try {
      await startScriptJobRun(job.job_name, dryRun)
      message.success(dryRun ? '已开始演练' : '已开始运行')
    } catch (err) {
      message.error(errorText(err))
    }
    reloadAll()
  }

  const handleStop = async (runId: number) => {
    try {
      await stopScriptRun(runId)
      message.success('已发送停止请求')
    } catch (err) {
      message.error(errorText(err))
    }
    reloadAll()
  }

  const alertJob = jobs.find((job) => job.job_name === 'sehuatang' && job.alert)

  const columns: ColumnsType<ScriptRun> = [
    { title: '时间', dataIndex: 'started_at', width: 180, render: (value: string) => <TimeText value={value} /> },
    {
      title: '脚本',
      dataIndex: 'script_name',
      width: 150,
      render: (value: string, run) => (
        <Space size={4} wrap>
          <span>{scriptLabel(value)}</span>
          {run.dry_run && <Tag>演练</Tag>}
          {TRIGGER_LABELS[run.trigger] && <Tag>{TRIGGER_LABELS[run.trigger]}</Tag>}
        </Space>
      ),
    },
    {
      title: '结果',
      key: 'result',
      render: (_, run) => (
        <Space direction="vertical" size={0}>
          <span>{run.status === 'running' || run.status === 'queued' ? '进行中' : describeRun(run)}</span>
          {run.error_reason && <Text type="danger">{run.error_reason}</Text>}
          {run.exit_code !== null && run.exit_code !== 0 && run.trigger === 'report' && (
            <Text type="danger">脚本中途退出，退出码 {run.exit_code}</Text>
          )}
          {fullCounts(run.counts).unparsed_lines > 0 && (
            <Text type="warning">有 {fullCounts(run.counts).unparsed_lines} 行输出没能识别，统计可能不准，脚本输出格式可能变了</Text>
          )}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (value: ScriptRunStatus) => <Tag color={RUN_STATUS[value].color}>{RUN_STATUS[value].label}</Tag>,
    },
  ]

  return (
    <PageScaffold title="脚本中心" description="定时脚本的运行、设置和每次运行的结果">
      {alertJob && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${alertJob.label}：${alertJob.alert}`}
          description="到设置里更换站点 cookie 后，可以先演练一次确认恢复。"
        />
      )}
      {jobsError && <Alert type="error" showIcon message={`脚本加载失败：${jobsError}`} style={{ marginBottom: 16 }} />}

      <SurfacePanel title="脚本" style={{ marginBottom: 16 }}>
        <JobCards
          jobs={jobs}
          onRun={handleRun}
          onStop={handleStop}
          onSettings={setSettingsJob}
          onShowLog={setLogRun}
        />
      </SurfacePanel>

      {logRun && (
        <SurfacePanel title={`实时日志：${scriptLabel(logRun.script_name)}`} style={{ marginBottom: 16 }}>
          <RunLogPanel key={logRun.id} runId={logRun.id} />
        </SurfacePanel>
      )}

      {summaryError && <Alert type="error" showIcon message={`统计加载失败：${summaryError}`} style={{ marginBottom: 16 }} />}

      {summary && (
        <SurfacePanel title="最近 7 天" style={{ marginBottom: 16 }}>
          <Space wrap size={[16, 8]} style={{ marginBottom: 16 }}>
            {summary.scripts.map((script) => (
              <span key={script.script_name}>
                <Text>{scriptLabel(script.script_name)}（{script.expected_time}）</Text>{' '}
                <Tag color={TODAY_STATUS[script.today_status].color}>{TODAY_STATUS[script.today_status].label}</Tag>
              </span>
            ))}
          </Space>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
            <DayBars title="清理数量" days={summary.days} valueOf={(day) => day.cleaned} />
            <DayBars title="新命中" days={summary.days} valueOf={(day) => day.moved_new} />
          </div>
        </SurfacePanel>
      )}

      <SurfacePanel title="运行记录">
        {runsError && <Alert type="error" showIcon message={`运行记录加载失败：${runsError}`} style={{ marginBottom: 16 }} />}
        <Table<ScriptRun>
          rowKey="id"
          size="small"
          loading={runsLoading}
          columns={columns}
          dataSource={runs.items}
          locale={{ emptyText: '还没有收到脚本回报' }}
          expandable={{ expandedRowRender: (run) => <RunDetail run={run} />, expandRowByClick: true }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: runs.total,
            showSizeChanger: false,
            onChange: (next) => {
              setPage(next)
            },
          }}
        />
      </SurfacePanel>

      <JobSettingsDrawer
        key={settingsJob?.job_name ?? 'none'}
        job={settingsJob}
        open={settingsJob !== null}
        onClose={() => setSettingsJob(null)}
        onSaved={() => {
          setSettingsJob(null)
          reloadAll()
        }}
      />
    </PageScaffold>
  )
}
