import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Checkbox, Input, Select, Segmented, Space, Table, Tag, Tooltip, Typography, message, notification } from 'antd'
import type { InputRef } from 'antd/es/input'
import type { ColumnsType } from 'antd/es/table'
import { SearchOutlined } from '@ant-design/icons'
import {
  ignoreChannel,
  ignorePackages,
  listInbox,
  submitDownloaderBatches,
  unignorePackages,
  type InboxItem,
} from '@/api/downloader'
import EmptyState from '@/components/EmptyState'
import StatusTag from '@/components/StatusTag'
import TimeText from '@/components/TimeText'
import DataToolbar from '@/layout/DataToolbar'
import { formatBytes } from '@/utils/format'
import { downloaderErrorText } from '@/utils/statusText'
import FloatingActionBar from './FloatingActionBar'
import { useUndoableIgnore } from './useUndoableIgnore'

type CandidatesInboxProps = {
  onCountsChange: (counts: { candidates: number; ignored: number }) => void
}

type InboxView = 'candidates' | 'ignored'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function CandidatesInbox({ onCountsChange }: CandidatesInboxProps) {
  const [view, setView] = useState<InboxView>('candidates')
  const [items, setItems] = useState<InboxItem[]>([])
  const [counts, setCounts] = useState({ candidates: 0, ignored: 0 })
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [downloadStatus, setDownloadStatus] = useState<string | undefined>()
  const [keywordEntryId, setKeywordEntryId] = useState<number | undefined>()
  const [selected, setSelected] = useState<Set<number>>(() => new Set())
  const [fading, setFading] = useState<Set<number>>(() => new Set())
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const searchRef = useRef<InputRef | null>(null)
  const lastSelectedIndex = useRef<number | null>(null)

  const load = useCallback(async (requestedPage = page) => {
    setLoading(true)
    try {
      const payload = await listInbox({
        view,
        search: search.trim() || undefined,
        downloadStatus,
        keywordEntryId,
        page: requestedPage,
      })
      setItems(payload.items ?? [])
      setCounts(payload.counts ?? { candidates: payload.total, ignored: 0 })
      onCountsChange(payload.counts ?? { candidates: payload.total, ignored: 0 })
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }, [downloadStatus, keywordEntryId, onCountsChange, page, search, view])

  const commitIgnore = useCallback(async (packageIds: number[]) => {
    await ignorePackages({ packageIds })
    await load(1)
  }, [load])
  const { schedule, undo, pendingIds } = useUndoableIgnore({ commit: commitIgnore })

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const active = document.activeElement as HTMLInputElement | HTMLTextAreaElement | null
      const isTextInput = active?.tagName === 'TEXTAREA' || (active?.tagName === 'INPUT' && active.type !== 'checkbox')
      if (event.key === '/' && !isTextInput) {
        event.preventDefault()
        searchRef.current?.focus()
      }
      if (event.key === 'Enter' && selected.size && !isTextInput) {
        event.preventDefault()
        void submitSelected()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  })

  const visibleItems = useMemo(
    () => items.filter((item) => !pendingIds.has(item.package_id) && !fading.has(item.package_id)),
    [fading, items, pendingIds],
  )
  const selectedItems = useMemo(() => items.filter((item) => selected.has(item.package_id)), [items, selected])
  const selectedBytes = selectedItems.reduce((total, item) => total + (item.known_total_size || 0), 0)
  const keywordOptions = useMemo(() => {
    const values = new Map<number, string>()
    items.forEach((item) => item.keywords.forEach((keyword) => values.set(keyword.keyword_entry_id, keyword.keyword)))
    return [...values].map(([value, label]) => ({ value, label }))
  }, [items])

  async function submitSelected() {
    if (!selectedItems.length || submitting) return
    const packageIds = selectedItems.map((item) => item.package_id)
    const candidateIds = selectedItems.flatMap((item) => item.candidate_ids)
    setSubmitting(true)
    try {
      const result = await submitDownloaderBatches(candidateIds)
      setFading(new Set(packageIds))
      setSelected(new Set())
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      if (!reduced) await new Promise((resolve) => window.setTimeout(resolve, 200))
      setFading(new Set())
      setPage(1)
      await load(1)
      const skipped = result.skipped ? `，跳过 ${result.skipped} 个` : ''
      notification.success({ title: `已提交 ${result.submitted} 个下载批次${skipped}`, placement: 'bottomRight' })
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setSubmitting(false)
    }
  }

  function toggleSelection(packageId: number, shiftKey: boolean) {
    const index = visibleItems.findIndex((item) => item.package_id === packageId)
    setSelected((current) => {
      const next = new Set(current)
      if (shiftKey && lastSelectedIndex.current !== null) {
        const start = Math.min(lastSelectedIndex.current, index)
        const end = Math.max(lastSelectedIndex.current, index)
        visibleItems.slice(start, end + 1).forEach((item) => next.add(item.package_id))
      } else if (next.has(packageId)) {
        next.delete(packageId)
      } else {
        next.add(packageId)
      }
      return next
    })
    lastSelectedIndex.current = index
  }

  function toggleAll() {
    setSelected((current) => {
      const next = new Set(current)
      const allSelected = visibleItems.every((item) => next.has(item.package_id))
      visibleItems.forEach((item) => (allSelected ? next.delete(item.package_id) : next.add(item.package_id)))
      return next
    })
  }

  function ignoreSelected() {
    if (!selectedItems.length) return
    const titles = selectedItems.map((item) => ({ packageId: item.package_id, title: item.title }))
    setSelected(new Set())
    schedule(titles)
    showIgnoreNotification(titles)
  }

  function ignoreOne(item: InboxItem) {
    const title = [{ packageId: item.package_id, title: item.title }]
    schedule(title)
    showIgnoreNotification(title)
  }

  function showIgnoreNotification(ignored: Array<{ packageId: number; title: string }>) {
    const first = ignored[0]?.title ?? ''
    const text = ignored.length === 1 ? `已忽略《${first}》` : `已忽略《${first}》等 ${ignored.length} 个资源包`
    notification.open({
      key: 'downloader-ignore',
      title: text,
      description: '5 秒内可以撤销，之后将保存到忽略列表。',
      btn: <Button size="small" onClick={() => { undo(); notification.destroy('downloader-ignore'); void load() }}>撤销</Button>,
      placement: 'bottomRight',
      duration: 5,
    })
  }

  async function ignoreWholeChannel(channelTitle: string) {
    try {
      const result = await ignoreChannel(channelTitle)
      await load()
      notification.open({
        key: 'downloader-ignore-channel',
        title: `已忽略频道「${channelTitle}」的 ${result.ignored} 个资源包`,
        description: '可以在 5 秒内撤销，之后也能在「已忽略」里逐个恢复。',
        btn: <Button size="small" onClick={() => {
          notification.destroy('downloader-ignore-channel')
          void unignorePackages(result.package_ids).then(() => load()).catch((error) => message.error(errorText(error)))
        }}>撤销</Button>,
        placement: 'bottomRight',
        duration: 5,
      })
    } catch (error) {
      message.error(errorText(error))
    }
  }

  async function restore(item: InboxItem) {
    try {
      await unignorePackages([item.package_id])
      await load()
    } catch (error) {
      message.error(errorText(error))
    }
  }

  const columns: ColumnsType<InboxItem> = [
    {
      title: <Checkbox aria-label="全选当前页" checked={visibleItems.length > 0 && visibleItems.every((item) => selected.has(item.package_id))} indeterminate={visibleItems.some((item) => selected.has(item.package_id)) && !visibleItems.every((item) => selected.has(item.package_id))} onChange={toggleAll} />,
      key: 'selection',
      width: 56,
      render: (_, item) => <Checkbox aria-label={`选择 ${item.title}`} checked={selected.has(item.package_id)} onChange={(event) => toggleSelection(item.package_id, event.nativeEvent.shiftKey)} />,
    },
    {
      title: '资源包与来源',
      key: 'package',
      render: (_, item) => (
        <div className="downloader-package-cell">
          <Typography.Text strong ellipsis={{ tooltip: item.title }}>{item.title}</Typography.Text>
          <span className="downloader-secondary-line">
            {item.channel_title || '未标注频道'}
            {item.channel_error ? <Tooltip title={downloaderErrorText(item.channel_error)}><Tag color="error" className="downloader-channel-error">频道不可访问</Tag></Tooltip> : null}
            {' · '}#{item.remote_package_id}
            {item.keywords.map((keyword) => <span className="keyword-pill" key={`${item.package_id}-${keyword.keyword_entry_id}`}>{keyword.keyword}</span>)}
          </span>
        </div>
      ),
    },
    {
      title: '体量与发布',
      key: 'size',
      render: (_, item) => <div><div className="numeric-text">{formatBytes(item.known_total_size)} · {item.media_count} 媒体</div><TimeText value={item.published_at} relative /></div>,
    },
    {
      title: '版本与状态',
      key: 'status',
      render: (_, item) => <Space orientation="vertical" size={2}><StatusTag domain="package" value={item.current_download_status} suffix={item.new_media_count ? `+${item.new_media_count}` : undefined} tooltip={item.new_media_count ? `本地已完成 r${item.completed_revision ?? '-'}，远端新版 r${item.index_revision}` : undefined} /><Typography.Text type="secondary">r{item.index_revision}</Typography.Text>{item.last_download_error && item.current_download_status !== 'completed' ? <Typography.Text type="danger" className="downloader-error-line">{downloaderErrorText(item.last_download_error)}</Typography.Text> : null}</Space>,
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, item) => view === 'ignored' ? <Button aria-label="恢复" className="downloader-row-action" size="small" onClick={() => void restore(item)}>恢复</Button> : (
        <Space size={4} wrap>
          <Button aria-label="忽略" className="downloader-row-action" size="small" onClick={() => ignoreOne(item)}>忽略</Button>
          {item.channel_title ? <Button aria-label={`忽略频道 ${item.channel_title}`} className="downloader-row-action" size="small" type="link" danger={Boolean(item.channel_error)} onClick={() => void ignoreWholeChannel(item.channel_title as string)}>忽略频道</Button> : null}
        </Space>
      ),
    },
  ]

  return (
    <section className="downloader-inbox" data-testid="candidates-inbox" aria-label="候选收件箱">
      <DataToolbar
        left={<Segmented value={view} onChange={(value) => { setView(value as InboxView); setPage(1); setSelected(new Set()) }} options={[{ label: `待确认 (${counts.candidates})`, value: 'candidates' }, { label: `已忽略 (${counts.ignored})`, value: 'ignored' }]} />}
        right={<Space wrap><Input ref={searchRef} prefix={<SearchOutlined />} allowClear placeholder="搜索资源包" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /><Select allowClear placeholder="白名单命中词" options={keywordOptions} value={keywordEntryId} onChange={(value) => { setKeywordEntryId(value); setPage(1) }} /><Select allowClear placeholder="下载状态" value={downloadStatus} onChange={(value) => { setDownloadStatus(value); setPage(1) }} options={[{ label: '全部', value: undefined }, { label: '未下载', value: 'never' }, { label: '有更新', value: 'outdated' }, { label: '曾失败', value: 'failed' }]} /></Space>}
      />
      <Table<InboxItem>
        className="downloader-inbox-table"
        rowKey="package_id"
        loading={loading}
        columns={columns}
        dataSource={visibleItems}
        pagination={{ current: page, pageSize: 50, total: view === 'candidates' ? counts.candidates : counts.ignored, hideOnSinglePage: true, onChange: (nextPage) => setPage(nextPage) }}
        rowClassName={(item) => fading.has(item.package_id) ? 'downloader-row-fading' : ''}
        locale={{ emptyText: <EmptyState title={view === 'ignored' ? '暂无已忽略资源包' : '暂无待确认候选'} description="可以先同步资源包，或调整筛选条件。" /> }}
      />
      <FloatingActionBar count={selectedItems.length} totalBytes={selectedBytes} onSelectAll={() => setSelected(new Set(visibleItems.map((item) => item.package_id)))} onClear={() => setSelected(new Set())} onIgnore={ignoreSelected} onSubmit={() => void submitSelected()} loading={submitting} />
    </section>
  )
}
