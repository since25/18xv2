import { useCallback, useEffect, useState } from 'react'
import { Alert, Segmented, message } from 'antd'
import { useSearchParams } from 'react-router-dom'
import {
  getDownloaderStatus,
  getDownloaderSummary,
  listInbox,
  type DownloaderStatus,
} from '@/api/downloader'
import PageScaffold from '@/layout/PageScaffold'
import CandidatesInbox from './downloader/CandidatesInbox'
import DownloaderHeader from './downloader/DownloaderHeader'
import TasksBoard from './downloader/TasksBoard'
import TaskInspector from './downloader/TaskInspector'

type DownloaderView = 'inbox' | 'tasks'

function parseView(value: string | null): DownloaderView {
  return value === 'tasks' ? 'tasks' : 'inbox'
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function DownloaderPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<DownloaderStatus | null>(null)
  const [counts, setCounts] = useState({ candidates: 0, ignored: 0 })
  const [activeCount, setActiveCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const taskId = searchParams.get('task')
  const view = taskId ? 'tasks' : parseView(searchParams.get('view'))

  const loadOverview = useCallback(async () => {
    setLoading(true)
    try {
      const [statusPayload, inboxPayload, summaryPayload] = await Promise.all([
        getDownloaderStatus(),
        listInbox({ view: 'candidates' }),
        getDownloaderSummary(),
      ])
      setStatus(statusPayload)
      setCounts(inboxPayload.counts ?? { candidates: inboxPayload.total, ignored: 0 })
      setActiveCount(summaryPayload.active_count ?? 0)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadOverview() }, 0)
    return () => window.clearTimeout(timer)
  }, [loadOverview])

  function changeView(value: string | number) {
    const next = parseView(String(value))
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('view', next)
    setSearchParams(nextParams)
  }

  const openTask = useCallback((nextTaskId: string) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('view', 'tasks')
    nextParams.set('task', nextTaskId)
    setSearchParams(nextParams)
  }, [searchParams, setSearchParams])

  const closeTask = useCallback(() => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('task')
    setSearchParams(nextParams)
  }, [searchParams, setSearchParams])

  return (
    <PageScaffold
      className="downloader-page"
      title="下载器"
      description="在候选收件箱中确认资源包，并在任务看板中跟踪下载进度。"
      actions={<DownloaderHeader status={status} onSynced={() => void loadOverview()} />}
    >
      {status && !status.enabled ? (
        <Alert type="warning" showIcon title="RN 下载器未启用" description="请配置下载器连接后再同步资源包。" />
      ) : null}
      {status?.enabled && !status.remote_ready ? (
        <Alert type="error" showIcon title="RN 下载器不可用" description={String(status.remote?.message || '请检查网络和登录密码。')} />
      ) : null}
      <Segmented
        className="downloader-view-switcher"
        value={view}
        onChange={changeView}
        options={[
          { label: `候选收件箱 (${counts.candidates} 待确认)`, value: 'inbox' },
          { label: `任务看板与历史 (${activeCount} 活跃)`, value: 'tasks' },
        ]}
      />
      {view === 'inbox' ? (
        <CandidatesInbox onCountsChange={setCounts} />
      ) : (
        <TasksBoard onActiveCountChange={setActiveCount} onOpenTask={openTask} />
      )}
      <TaskInspector taskId={taskId} onClose={closeTask} onChanged={() => void loadOverview()} />
      {loading ? <span className="sr-only">正在加载下载器数据</span> : null}
    </PageScaffold>
  )
}
