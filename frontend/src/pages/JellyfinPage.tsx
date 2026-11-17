import { useEffect, useRef, useState } from 'react'
import { ReloadOutlined, ScanOutlined, SyncOutlined } from '@ant-design/icons'
import { Alert, Button, Descriptions, Select, Space, Table, Tooltip, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getJellyfinJob,
  getJellyfinStatus,
  listJellyfinConflicts,
  listJellyfinUnmatched,
  startJellyfinScan,
  startJellyfinSync,
  type JellyfinConflictItem,
  type JellyfinJob,
  type JellyfinMediaSource,
  type JellyfinStatus,
  type JellyfinUnmatchedItem,
  type JellyfinUnmatchedState,
} from '@/api/jellyfin'
import PageScaffold from '@/layout/PageScaffold'
import SurfacePanel from '@/layout/SurfacePanel'
import TimeText from '@/components/TimeText'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'

const { Text } = Typography
const POLL_INTERVAL_MS = 3000
const PAGE_SIZE = 50

const SOURCE_LABELS: Record<JellyfinMediaSource, string> = {
  local: '本地已整理',
  strm_115: '115 STRM',
}
const STATE_LABELS: Record<string, string> = {
  unmatched: '未匹配',
  nfo_error: 'NFO 解析失败',
}
// 任务结果摘要里的字段 → 中文名，未列出的字段原样显示
const SUMMARY_LABELS: Record<string, string> = {
  local_files: '本地文件',
  strm_files: 'STRM 文件',
  matched: '已匹配',
  unmatched: '未匹配',
  nfo_error: 'NFO 错误',
  deactivated: '标记失效',
  collections_created: '新建合集',
  collections_renamed: '改名合集',
  collections_deleted: '删除合集',
  items_added: '加入条目',
  items_removed: '移出条目',
  pending_items: '待 Jellyfin 扫描',
  conflicts: '冲突',
  errors: '出错',
}

type JobKind = 'scan' | 'sync'

function JobSummary({ job }: { job: JellyfinJob | null }) {
  if (!job) return <Text type="secondary">尚未运行</Text>
  if (!job.done) return <Text>运行中{job.stage ? `：${job.stage}` : ''}</Text>
  if (job.error) return <Text type="danger">失败：{job.error}</Text>
  const entries = Object.entries(job.summary ?? {})
  return (
    <Space direction="vertical" size={2}>
      <Text type="secondary">
        完成于 <TimeText value={job.finished_at} />
      </Text>
      {entries.length > 0 && (
        <Text>{entries.map(([key, value]) => `${SUMMARY_LABELS[key] ?? key} ${value ?? '-'}`).join(' · ')}</Text>
      )}
    </Space>
  )
}

export default function JellyfinPage() {
  const [runningJobs, setRunningJobs] = useState<Partial<Record<JobKind, string>>>({})
  const [source, setSource] = useState<JellyfinMediaSource | undefined>(undefined)
  const [state, setState] = useState<JellyfinUnmatchedState | undefined>(undefined)
  const [page, setPage] = useState(1)
  // 任务完成后递增，用来触发未匹配列表和冲突列表重新加载
  const [reloadToken, setReloadToken] = useState(0)
  const timers = useRef<Partial<Record<JobKind, ReturnType<typeof setInterval>>>>({})

  // 状态：出错不弹提示，错误文字显示在页面提示条里
  const statusQuery = useApiQuery(() => getJellyfinStatus() as Promise<JellyfinStatus | null>, [], {
    silent: true,
    initialData: null,
  })
  const status = statusQuery.data
  const loadError = statusQuery.error ? statusQuery.error.message : null
  const reloadStatus = statusQuery.reload
  const loadStatus = () => {
    void reloadStatus({ silent: true })
  }

  // 冲突列表：出错时静默清空
  const { data: conflicts } = useApiQuery(
    () => listJellyfinConflicts()
      .then((res) => res.items)
      .catch(() => [] as JellyfinConflictItem[]),
    [reloadToken],
    { initialData: [] as JellyfinConflictItem[] },
  )

  // 未匹配列表：出错时静默清空；筛选、翻页或任务完成时重新加载
  const { data: unmatched, loading: unmatchedLoading } = useApiQuery(
    () => listJellyfinUnmatched({ source, state, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      .catch(() => ({ total: 0, items: [] as JellyfinUnmatchedItem[] })),
    [source, state, page, reloadToken],
    { initialData: { total: 0, items: [] as JellyfinUnmatchedItem[] } },
  )

  // 筛选或翻页：依赖变化后自动进入加载状态并重新拉取
  const changeUnmatchedQuery = (update: () => void) => {
    update()
  }

  // 离开页面时停止所有轮询
  useEffect(() => {
    const current = timers.current
    return () => {
      Object.values(current).forEach((timer) => timer && clearInterval(timer))
    }
  }, [])

  const stopPolling = (kind: JobKind) => {
    const timer = timers.current[kind]
    if (timer) clearInterval(timer)
    delete timers.current[kind]
    setRunningJobs((prev) => {
      const next = { ...prev }
      delete next[kind]
      return next
    })
  }

  const pollJob = (kind: JobKind, jobId: string) => {
    timers.current[kind] = setInterval(async () => {
      try {
        const job = await getJellyfinJob(jobId)
        if (!job.done) return
        stopPolling(kind)
        if (job.error) {
          message.error(`${kind === 'scan' ? '扫描' : '同步'}失败：${job.error}`)
        } else {
          message.success(kind === 'scan' ? '扫描完成' : '合集同步完成')
        }
        loadStatus()
        setReloadToken((token) => token + 1)
      } catch {
        stopPolling(kind)
      }
    }, POLL_INTERVAL_MS)
  }

  const startAction = useApiAction((kind: JobKind) => (kind === 'scan' ? startJellyfinScan() : startJellyfinSync()))

  const startJob = async (kind: JobKind) => {
    const result = await startAction.run(kind)
    if (!result.ok) return
    const res = result.data
    setRunningJobs((prev) => ({ ...prev, [kind]: res.job_id }))
    message.info(kind === 'scan' ? '已开始扫描' : '已开始同步合集')
    pollJob(kind, res.job_id)
  }

  const scanDisabledReason = status && !status.scan_enabled ? '未启用：需在 .env 中设置 JELLYFIN_ENABLED=true' : null
  const syncDisabledReason =
    status && !status.sync_enabled ? '未启用：需配置 JELLYFIN_ENABLED、JELLYFIN_BASE_URL 和 JELLYFIN_API_KEY' : null

  const columns: ColumnsType<JellyfinUnmatchedItem> = [
    { title: '来源', dataIndex: 'source', width: 120, render: (value: JellyfinMediaSource) => SOURCE_LABELS[value] ?? value },
    { title: '状态', dataIndex: 'match_state', width: 130, render: (value: string) => STATE_LABELS[value] ?? value },
    { title: '路径', dataIndex: 'path', render: (value: string) => <Text copyable>{value}</Text> },
    { title: '说明', dataIndex: 'match_note', width: 220, render: (value: string | null) => value ?? '-' },
  ]
  const conflictColumns: ColumnsType<JellyfinConflictItem> = [
    { title: '关键词', dataIndex: 'canonical_name_snapshot', render: (value: string | null) => value ?? '-' },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '原因', dataIndex: 'last_error', render: (value: string | null) => value ?? '-' },
  ]

  const counts = status?.counts
  const stats = counts
    ? [
        { key: 'active', label: '在库条目', value: counts.active_items },
        { key: 'matched', label: '已匹配', value: counts.matched },
        { key: 'unmatched', label: '未匹配', value: counts.unmatched },
        { key: 'nfo_error', label: 'NFO 错误', value: counts.nfo_error },
        { key: 'pending', label: '待 Jellyfin 扫描', value: counts.pending_resolve },
        { key: 'collections', label: '受管合集', value: status.collections.active },
      ]
    : undefined

  return (
    <PageScaffold
      title="Jellyfin"
      description="扫描本地已整理目录和 115 STRM，按白名单关键词在 Jellyfin 中维护合集。只读媒体目录，不写入任何文件。"
      stats={stats}
      actions={
        <Space>
          <Tooltip title={scanDisabledReason}>
            <Button
              icon={<ScanOutlined />}
              disabled={!status || !!scanDisabledReason}
              loading={!!runningJobs.scan}
              onClick={() => void startJob('scan')}
            >
              立即扫描
            </Button>
          </Tooltip>
          <Tooltip title={syncDisabledReason}>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              disabled={!status || !!syncDisabledReason}
              loading={!!runningJobs.sync}
              onClick={() => void startJob('sync')}
            >
              立即同步合集
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => loadStatus()}>
            刷新
          </Button>
        </Space>
      }
    >
      {loadError && <Alert type="error" showIcon message={`状态加载失败：${loadError}`} style={{ marginBottom: 16 }} />}

      <SurfacePanel title="运行状态" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="本地根目录">{status?.local_roots.join('，') || '未配置'}</Descriptions.Item>
          <Descriptions.Item label="STRM 根目录">{status?.strm_roots.join('，') || '未配置'}</Descriptions.Item>
          <Descriptions.Item label="最近扫描">
            <JobSummary job={status?.latest_scan ?? null} />
          </Descriptions.Item>
          <Descriptions.Item label="最近同步">
            <JobSummary job={status?.latest_sync ?? null} />
          </Descriptions.Item>
        </Descriptions>
      </SurfacePanel>

      <SurfacePanel
        title="未匹配条目"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="全部来源"
              style={{ width: 140 }}
              value={source}
              onChange={(value) =>
                changeUnmatchedQuery(() => {
                  setSource(value)
                  setPage(1)
                })
              }
              options={Object.entries(SOURCE_LABELS).map(([value, label]) => ({ value, label }))}
              aria-label="来源筛选"
            />
            <Select
              allowClear
              placeholder="全部状态"
              style={{ width: 150 }}
              value={state}
              onChange={(value) =>
                changeUnmatchedQuery(() => {
                  setState(value)
                  setPage(1)
                })
              }
              options={Object.entries(STATE_LABELS).map(([value, label]) => ({ value, label }))}
              aria-label="状态筛选"
            />
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Table
          rowKey="id"
          size="small"
          loading={unmatchedLoading}
          columns={columns}
          dataSource={unmatched.items}
          pagination={{ current: page, pageSize: PAGE_SIZE, total: unmatched.total, showSizeChanger: false, onChange: (next) => changeUnmatchedQuery(() => setPage(next)) }}
          locale={{ emptyText: '没有未匹配条目' }}
        />
      </SurfacePanel>

      <SurfacePanel title="冲突与出错的合集">
        <Table
          rowKey={(row) => `${row.keyword_entry_id ?? 'none'}-${row.canonical_name_snapshot ?? ''}`}
          size="small"
          columns={conflictColumns}
          dataSource={conflicts}
          pagination={false}
          locale={{ emptyText: '没有冲突' }}
        />
      </SurfacePanel>
    </PageScaffold>
  )
}
