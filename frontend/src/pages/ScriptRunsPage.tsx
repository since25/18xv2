import { useEffect, useState } from 'react'
import { Alert, Input, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getScriptRunSummary,
  listScriptRunItems,
  listScriptRuns,
  type ScriptRun,
  type ScriptRunDay,
  type ScriptRunItem,
  type ScriptRunItemKind,
  type ScriptRunStatus,
  type ScriptRunSummary,
  type ScriptTodayStatus,
} from '@/api/scriptRuns'
import PageScaffold from '@/layout/PageScaffold'
import SurfacePanel from '@/layout/SurfacePanel'
import TimeText from '@/components/TimeText'

const { Text } = Typography
const PAGE_SIZE = 50

const SCRIPT_LABELS: Record<string, string> = {
  DEL_SOMETHING: '整理脚本',
  MOVE_SSD_CACHE_TO_DISK2: '搬运脚本',
}
const RUN_STATUS: Record<ScriptRunStatus, { label: string; color: string }> = {
  success: { label: '正常', color: 'success' },
  warning: { label: '有警告', color: 'warning' },
  failed: { label: '失败', color: 'error' },
}
const TODAY_STATUS: Record<ScriptTodayStatus, { label: string; color: string }> = {
  ...RUN_STATUS,
  pending: { label: '今天还没到运行时间', color: 'default' },
  missing: { label: '今天没有运行记录', color: 'error' },
}
// 页签顺序：先看结果，再看问题
const KIND_LABELS: Array<[ScriptRunItemKind, string]> = [
  ['deleted_file', '清理-文件'],
  ['deleted_dir', '清理-目录'],
  ['moved_new', '新命中'],
  ['moved_rescan', '重新归位'],
  ['empty_dir', '空文件夹'],
  ['error', '报错'],
  ['warning', '警告'],
  ['ambiguous', '词条歧义'],
  ['skipped', '跳过'],
]

function scriptLabel(name: string) {
  return SCRIPT_LABELS[name] ?? name
}

/** 一次运行的一句话结果 */
function describeRun(run: ScriptRun) {
  const c = run.counts
  if (run.script_name === 'DEL_SOMETHING') {
    const parts = [
      `清理 ${c.deleted_dirs + c.deleted_files}（目录 ${c.deleted_dirs}，文件 ${c.deleted_files}）`,
      `新命中 ${c.moved_new}`,
    ]
    if (c.moved_rescan > 0) parts.push(`重新归位 ${c.moved_rescan}`)
    if (c.empty_dirs > 0) parts.push(`空文件夹 ${c.empty_dirs}`)
    if (c.errors > 0) parts.push(`报错 ${c.errors}`)
    if (c.warnings > 0) parts.push(`警告 ${c.warnings}`)
    return parts.join('，')
  }
  return `移动 ${c.moved}，删除重复 ${c.duplicates_removed}，跳过 ${c.skipped}，失败 ${c.failed}`
}

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
  const [data, setData] = useState<{ total: number; items: ScriptRunItem[] }>({ total: 0, items: [] })
  const [kindCounts, setKindCounts] = useState<Partial<Record<ScriptRunItemKind, number>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const available = KIND_LABELS.filter(([key]) => (kindCounts?.[key] ?? 0) > 0)
  // 第一次请求拿到各类数量后，默认选中第一个有内容的类别
  const activeKind = kind ?? available[0]?.[0]

  useEffect(() => {
    let cancelled = false
    listScriptRunItems(run.id, { kind: activeKind, q: q || undefined, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      .then((res) => {
        if (cancelled) return
        setData(res)
        setKindCounts(res.kind_counts)
        setError(null)
      })
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [run.id, activeKind, q, page])

  if (error) return <Alert type="error" showIcon message={`名单加载失败：${error}`} />
  if (kindCounts && available.length === 0) return <Text type="secondary">这次运行没有名单</Text>

  const isMove = activeKind === 'moved_new' || activeKind === 'moved_rescan'
  const columns: ColumnsType<ScriptRunItem> = isMove
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
          setLoading(true)
          setKind(key as ScriptRunItemKind)
          setPage(1)
        }}
        items={available.map(([key, label]) => ({ key, label: `${label} ${kindCounts?.[key] ?? 0}` }))}
      />
      <Input.Search
        allowClear
        placeholder="在当前类别里搜索路径"
        style={{ maxWidth: 360 }}
        onSearch={(value) => {
          setLoading(true)
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
            setLoading(true)
            setPage(next)
          },
        }}
      />
    </Space>
  )
}

export default function ScriptRunsPage() {
  const [summary, setSummary] = useState<ScriptRunSummary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [runs, setRuns] = useState<{ total: number; items: ScriptRun[] }>({ total: 0, items: [] })
  const [runsError, setRunsError] = useState<string | null>(null)
  const [runsLoading, setRunsLoading] = useState(true)
  const [page, setPage] = useState(1)

  useEffect(() => {
    let cancelled = false
    getScriptRunSummary()
      .then((res) => {
        if (cancelled) return
        setSummary(res)
        setSummaryError(null)
      })
      .catch((err: unknown) => !cancelled && setSummaryError(err instanceof Error ? err.message : '加载失败'))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    listScriptRuns({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      .then((res) => {
        if (cancelled) return
        setRuns(res)
        setRunsError(null)
      })
      .catch((err: unknown) => !cancelled && setRunsError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => !cancelled && setRunsLoading(false))
    return () => {
      cancelled = true
    }
  }, [page])

  const columns: ColumnsType<ScriptRun> = [
    { title: '时间', dataIndex: 'started_at', width: 180, render: (value: string) => <TimeText value={value} /> },
    { title: '脚本', dataIndex: 'script_name', width: 100, render: scriptLabel },
    {
      title: '结果',
      key: 'result',
      render: (_, run) => (
        <Space direction="vertical" size={0}>
          <span>{describeRun(run)}</span>
          {run.exit_code !== 0 && <Text type="danger">脚本中途退出，退出码 {run.exit_code}</Text>}
          {run.counts.unparsed_lines > 0 && (
            <Text type="warning">有 {run.counts.unparsed_lines} 行输出没能识别，统计可能不准，脚本输出格式可能变了</Text>
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
    <PageScaffold title="脚本日报" description="Unraid 上两个定时脚本每次运行的结果">
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
          expandable={{ expandedRowRender: (run) => <RunItems run={run} />, expandRowByClick: true }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: runs.total,
            showSizeChanger: false,
            onChange: (next) => {
              setRunsLoading(true)
              setPage(next)
            },
          }}
        />
      </SurfacePanel>
    </PageScaffold>
  )
}
