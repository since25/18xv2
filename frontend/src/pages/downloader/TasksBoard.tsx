import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, DatePicker, Input, Progress, Select, Segmented, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { type Dayjs } from 'dayjs'
import { SearchOutlined } from '@ant-design/icons'
import {
  cancelDownloaderTask,
  getDownloaderSummary,
  listDownloaderChannels,
  listDownloaderKeywords,
  listTasks,
  retryDownloaderTask,
  type DownloaderSummary,
  type TaskRow,
} from '@/api/downloader'
import EmptyState from '@/components/EmptyState'
import StatusTag from '@/components/StatusTag'
import TimeText from '@/components/TimeText'
import DataToolbar from '@/layout/DataToolbar'
import MetricStrip from '@/layout/MetricStrip'
import { formatBytes, formatDuration } from '@/utils/format'
import { useSearchParams } from 'react-router-dom'

type TasksBoardProps = {
  onActiveCountChange: (n: number) => void
  onOpenTask: (taskId: string) => void
}

type RangeValue = 'all' | 'today' | '7d' | '30d' | 'custom'

const ACTIVE = new Set(['pending', 'queued', 'running', 'downloading', 'paused'])

function localShanghaiMidnight(daysAgo = 0) {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const year = Number(parts.find((part) => part.type === 'year')?.value)
  const month = Number(parts.find((part) => part.type === 'month')?.value)
  const day = Number(parts.find((part) => part.type === 'day')?.value)
  const date = new Date(Date.UTC(year, month - 1, day - daysAgo, 0, 0, 0))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}T00:00:00+08:00`
}

function rangeSince(value: RangeValue) {
  if (value === 'today') return localShanghaiMidnight()
  if (value === '7d') return localShanghaiMidnight(7)
  if (value === '30d') return localShanghaiMidnight(30)
  return undefined
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function TasksBoard({ onActiveCountChange, onOpenTask }: TasksBoardProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<DownloaderSummary>({ today_count: 0, today_bytes: 0, week_count: 0, week_bytes: 0, active_count: 0, week_failed_files: 0 })
  const [channels, setChannels] = useState<string[]>([])
  const [keywords, setKeywords] = useState<Array<{ id: number; canonical_name: string }>>([])
  const [customRange, setCustomRange] = useState<[Dayjs | null, Dayjs | null]>([null, null])
  const [loading, setLoading] = useState(false)

  const statusParam = searchParams.get('status') ?? ''
  const status = useMemo(() => statusParam.split(',').filter(Boolean), [statusParam])
  const range = (searchParams.get('range') as RangeValue | null) ?? 'all'
  const channel = searchParams.get('channel') ?? undefined
  const keywordEntryId = searchParams.get('kw') ? Number(searchParams.get('kw')) : undefined
  const search = searchParams.get('q') ?? ''
  const page = Number(searchParams.get('page') ?? '1') || 1

  const updateParam = useCallback((key: string, value: string | undefined) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.set('page', '1')
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  const filters = useMemo(() => ({
    status: status.length ? status : undefined,
    since: range === 'custom' ? customRange[0]?.startOf('day').format('YYYY-MM-DDT00:00:00+08:00') : rangeSince(range),
    until: range === 'custom' ? customRange[1]?.endOf('day').format('YYYY-MM-DDT23:59:59+08:00') : undefined,
    channel,
    keywordEntryId: Number.isFinite(keywordEntryId) ? keywordEntryId : undefined,
    search: search || undefined,
    page,
  }), [channel, customRange, keywordEntryId, page, range, search, status])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [taskPayload, summaryPayload] = await Promise.all([listTasks(filters), getDownloaderSummary()])
      setTasks(taskPayload.items ?? [])
      setTotal(taskPayload.total ?? 0)
      setSummary(summaryPayload)
      onActiveCountChange(summaryPayload.active_count ?? 0)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }, [filters, onActiveCountChange])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    let cancelled = false
    void Promise.all([listDownloaderChannels(), listDownloaderKeywords()]).then(([nextChannels, nextKeywords]) => {
      if (!cancelled) {
        setChannels(nextChannels)
        setKeywords(nextKeywords)
      }
    }).catch((error) => message.error(errorText(error)))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!summary.active_count) return undefined
    let timer: number | null = null
    const refresh = () => {
      if (document.visibilityState !== 'hidden') void load()
    }
    timer = window.setInterval(refresh, 5000)
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden' && timer !== null) {
        window.clearInterval(timer)
        timer = null
      } else if (document.visibilityState !== 'hidden' && timer === null) {
        void load()
        timer = window.setInterval(refresh, 5000)
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      if (timer !== null) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [load, summary.active_count])

  async function cancel(taskId: string) {
    try { await cancelDownloaderTask(taskId); await load() } catch (error) { message.error(errorText(error)) }
  }

  async function retry(taskId: string) {
    try { await retryDownloaderTask(taskId); await load() } catch (error) { message.error(errorText(error)) }
  }

  const activeTasks = tasks.filter((task) => ACTIVE.has(task.status))
  const columns: ColumnsType<TaskRow> = [
    {
      title: '任务与频道',
      key: 'title',
      render: (_, task) => <div><Typography.Text strong>{task.title || task.remote_task_id}</Typography.Text><div className="downloader-secondary-line">{task.channel_title || '未标注频道'}</div></div>,
    },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value) => <StatusTag domain="task" value={value} /> },
    {
      title: '文件进度',
      key: 'progress',
      render: (_, task) => <div className="task-progress-cell"><Progress percent={task.total_count ? Math.round((task.success_count / task.total_count) * 100) : 0} size="small" /><span>{task.success_count}/{task.total_count} 成功 · 失败 {task.failed_count}</span></div>,
    },
    {
      title: '传输量',
      key: 'bytes',
      width: 150,
      onHeaderCell: () => ({ className: 'downloader-nowrap-column' }),
      onCell: () => ({ className: 'downloader-nowrap-column' }),
      render: (_, task) => <span className="numeric-text">{formatBytes(task.downloaded_bytes)} / {formatBytes(task.total_bytes)}</span>,
    },
    {
      title: '启动与耗时',
      key: 'created-duration',
      width: 150,
      onHeaderCell: () => ({ className: 'downloader-nowrap-column' }),
      onCell: () => ({ className: 'downloader-nowrap-column' }),
      render: (_, task) => <div className="downloader-composite-cell"><TimeText value={task.remote_created_at} relative /><span className="downloader-secondary-line">耗时 <span className="downloader-duration-value">{formatDuration(task.duration_seconds)}</span></span></div>,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, task) => <Space onClick={(event) => event.stopPropagation()}><Button size="small" disabled={!task.failed_count} onClick={() => void retry(task.remote_task_id)}>重试失败项</Button><Button aria-label="取消" size="small" disabled={!ACTIVE.has(task.status)} onClick={() => void cancel(task.remote_task_id)}>取消</Button></Space>,
    },
  ]

  return (
    <section className="downloader-tasks-board" data-testid="tasks-board">
      {activeTasks.length ? <Card className="downloader-active-strip" size="small">
        {activeTasks.map((task) => <div className="downloader-active-task" key={task.remote_task_id}><strong>{task.title || task.remote_task_id}</strong><span>{formatBytes(task.download_speed_bytes)}/s</span><Progress percent={task.total_count ? Math.round((task.success_count / task.total_count) * 100) : 0} size="small" /><span>{task.total_count - task.success_count - task.failed_count} 个文件活跃</span></div>)}
      </Card> : null}
      <MetricStrip items={[{ key: 'today', label: '今日', value: `${summary.today_count} 个 · ${formatBytes(summary.today_bytes)}` }, { key: 'week', label: '近 7 天', value: `${summary.week_count} 个 · ${formatBytes(summary.week_bytes)}` }, { key: 'active', label: '进行中', value: summary.active_count }, { key: 'failed', label: '近 7 天失败文件', value: summary.week_failed_files }]} />
      <DataToolbar left={<Segmented value={status[0] ?? 'all'} onChange={(value) => updateParam('status', value === 'all' ? undefined : String(value))} options={[{ label: '全部', value: 'all' }, { label: '活跃中', value: 'active' }, { label: '已完成', value: 'completed' }, { label: '部分完成', value: 'completed_with_errors' }, { label: '失败', value: 'failed' }, { label: '已取消', value: 'cancelled' }]} />} right={<Space wrap><Select aria-label="时间范围" value={range} onChange={(value) => updateParam('range', value === 'all' ? undefined : value)} options={[{ label: '全部时间', value: 'all' }, { label: '今天', value: 'today' }, { label: '近 7 天', value: '7d' }, { label: '近 30 天', value: '30d' }, { label: '自定义', value: 'custom' }]} /><Select allowClear aria-label="频道" placeholder="频道" value={channel} onChange={(value) => updateParam('channel', value)} options={channels.map((value) => ({ label: value, value }))} /><Select allowClear aria-label="关键词" placeholder="关键词" value={keywordEntryId} onChange={(value) => updateParam('kw', value ? String(value) : undefined)} options={keywords.map((value) => ({ label: value.canonical_name, value: value.id }))} /><Input aria-label="标题搜索" prefix={<SearchOutlined />} placeholder="搜索任务标题" value={search} onChange={(event) => updateParam('q', event.target.value || undefined)} /></Space>} />
      {range === 'custom' ? <DatePicker.RangePicker value={customRange} onChange={(value) => setCustomRange(value as [Dayjs | null, Dayjs | null])} /> : null}
      <Table<TaskRow>
        className="downloader-task-table"
        rowKey="remote_task_id"
        loading={loading}
        columns={columns}
        dataSource={tasks}
        pagination={{ current: page, pageSize: 20, total, hideOnSinglePage: true, onChange: (nextPage) => updateParam('page', String(nextPage)) }}
        onRow={(task) => ({ onClick: () => onOpenTask(task.remote_task_id), tabIndex: 0, onKeyDown: (event) => { if (event.key === 'Enter') onOpenTask(task.remote_task_id) } })}
        locale={{ emptyText: <EmptyState title="暂无下载任务" description="同步任务后，这里会显示下载进度和历史。" /> }}
      />
    </section>
  )
}
