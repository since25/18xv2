import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Progress, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PauseCircleOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import PageScaffold from '@/layout/PageScaffold'
import {
  cancelDownloaderTask,
  controlDownloader,
  getDownloaderStatus,
  listDownloaderCandidates,
  listDownloaderTasks,
  retryDownloaderTask,
  selectDownloaderCandidate,
  submitDownloaderBatches,
  syncDownloaderPackages,
  syncDownloaderTasks,
  type DownloaderCandidate,
  type DownloaderStatus,
  type DownloaderTask,
} from '@/api/downloader'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function DownloaderPage() {
  const [status, setStatus] = useState<DownloaderStatus | null>(null)
  const [candidates, setCandidates] = useState<DownloaderCandidate[]>([])
  const [tasks, setTasks] = useState<DownloaderTask[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [statusPayload, candidatePayload, taskPayload] = await Promise.all([
        getDownloaderStatus(),
        listDownloaderCandidates({ search: search.trim() || undefined }),
        listDownloaderTasks(),
      ])
      setStatus(statusPayload)
      setCandidates(candidatePayload.items ?? [])
      setTasks(taskPayload.items ?? [])
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
    // 页面首次挂载只需读取一次；后续刷新由按钮和操作主动触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSelectionChange = async (keys: Array<string | number>) => {
    const next = keys.map(Number)
    const changed = [...new Set([...selected, ...next])].filter((id) => selected.includes(id) !== next.includes(id))
    try {
      await Promise.all(changed.map((id) => selectDownloaderCandidate(id, next.includes(id))))
      setSelected(next)
    } catch (error) {
      message.error(errorText(error))
    }
  }

  const doSync = async () => {
    setLoading(true)
    try {
      const result = await syncDownloaderPackages()
      await syncDownloaderTasks()
      message.success(`已同步 ${result.packages_seen} 个资源包，新增 ${result.candidates_created} 个候选`)
      setSelected([])
      await load()
    } catch (error) {
      message.error(errorText(error))
      setLoading(false)
    }
  }

  const submit = async () => {
    if (!selected.length) {
      message.warning('请先选择候选资源包')
      return
    }
    setLoading(true)
    try {
      const result = await submitDownloaderBatches(selected)
      message.success(`已提交 ${result.submitted} 个下载批次，跳过 ${result.skipped} 个`)
      setSelected([])
      await load()
    } catch (error) {
      message.error(errorText(error))
      setLoading(false)
    }
  }

  // Columns are stable; action handlers call the current page loader explicitly.
  const candidateColumns: ColumnsType<DownloaderCandidate> = useMemo(() => [
    { title: '资源包', dataIndex: 'title', key: 'title', render: (value, row) => <Space direction="vertical" size={0}><Typography.Text strong>{value}</Typography.Text><Typography.Text type="secondary">{row.channel_title || '未标注频道'} · #{row.remote_package_id}</Typography.Text></Space> },
    { title: '白名单命中', dataIndex: 'keyword', key: 'keyword', render: (value, row) => <Space><Tag color="blue">{value}</Tag><Typography.Text type="secondary">{row.matched_term}</Typography.Text></Space> },
    { title: '资源包状态', key: 'package', render: (_, row) => <Space><Tag color={row.boundary_status === 'stable' ? 'green' : 'orange'}>{row.boundary_status}</Tag><Tag>{row.current_download_status}</Tag></Space> },
    { title: '媒体', key: 'media', render: (_, row) => `${row.media_count} 个 / ${row.known_total_size || 0} bytes` },
  ], [])

  const taskColumns: ColumnsType<DownloaderTask> = useMemo(() => [
    { title: '任务', dataIndex: 'title', key: 'title', render: (value, row) => <Space direction="vertical" size={0}><Typography.Text>{value || row.remote_task_id}</Typography.Text><Typography.Text type="secondary">{row.remote_task_id}</Typography.Text></Space> },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value) => <Tag color={value === 'completed' ? 'green' : value === 'failed' ? 'red' : 'blue'}>{value}</Tag> },
    { title: '进度', key: 'progress', render: (_, row) => <Space direction="vertical" size={0} style={{ minWidth: 180 }}><Progress percent={row.total_count ? Math.round((row.success_count / row.total_count) * 100) : 0} size="small" /><Typography.Text type="secondary">{row.success_count}/{row.total_count} 成功，失败 {row.failed_count}</Typography.Text></Space> },
    { title: '操作', key: 'actions', render: (_, row) => <Space><Button size="small" onClick={() => void cancelDownloaderTask(row.remote_task_id).then(load).catch((error) => message.error(errorText(error)))}>取消</Button><Button size="small" onClick={() => void retryDownloaderTask(row.remote_task_id).then(load).catch((error) => message.error(errorText(error)))}>重试</Button></Space> },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [])

  return (
    <PageScaffold
      className="downloader-page"
      title="下载器资源包"
      description="用 18x 白名单和黑名单筛选 RN 下载器已扫描的资源包，确认后精确创建下载批次。"
      actions={<Space><Button icon={<PauseCircleOutlined />} onClick={() => void controlDownloader('pause').then(load).catch((error) => message.error(errorText(error)))}>暂停下载</Button><Button onClick={() => void controlDownloader('resume').then(load).catch((error) => message.error(errorText(error)))}>恢复下载</Button><Button type="primary" icon={<SyncOutlined />} loading={loading} onClick={() => void doSync()}>同步资源包</Button></Space>}
    >
      {status && !status.enabled ? <Alert type="warning" showIcon message="RN 下载器未启用" description="请配置 DOWNLOADER_ENABLED、DOWNLOADER_BASE_URL 和 DOWNLOADER_PASSWORD。" /> : null}
      {status && status.enabled && !status.remote_ready ? <Alert type="error" showIcon message="RN 下载器不可用" description={String(status.remote?.message || '请检查网络和登录密码。')} /> : null}
      <Card title={`待确认候选（${candidates.length}）`} style={{ marginTop: 16 }} extra={<Space><Input.Search placeholder="按资源包标题筛选" allowClear value={search} onChange={(event) => setSearch(event.target.value)} onSearch={() => void load()} /><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" disabled={!selected.length} onClick={() => void submit()}>确认并下载 ({selected.length})</Button></Space>}>
        <Table rowKey="candidate_id" loading={loading} columns={candidateColumns} dataSource={candidates} rowSelection={{ selectedRowKeys: selected, onChange: (keys) => void handleSelectionChange(keys.filter((key): key is string | number => typeof key === 'string' || typeof key === 'number')) }} pagination={false} locale={{ emptyText: '暂无待确认候选；请先同步资源包' }} />
      </Card>
      <Card title="下载任务进度" style={{ marginTop: 16 }} extra={<Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新任务</Button>}>
        <Table rowKey="remote_task_id" loading={loading} columns={taskColumns} dataSource={tasks} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无已同步的下载任务' }} />
      </Card>
    </PageScaffold>
  )
}
