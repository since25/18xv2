import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Checkbox, Input, Modal, Select, Segmented, Space, Table, Tag, Tooltip, Typography, message, notification } from 'antd'
import type { InputRef } from 'antd/es/input'
import type { ColumnsType } from 'antd/es/table'
import { SearchOutlined } from '@ant-design/icons'
import {
  ignoreChannel,
  ignorePackages,
  listDownloaderChannels,
  listInbox,
  quickAddKeyword,
  submitDownloaderBatches,
  submitDownloaderPackages,
  unignorePackages,
  type InboxItem,
  type KeywordQuickAddResult,
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

type InboxView = 'candidates' | 'ignored' | 'unmatched'

type ListType = 'whitelist' | 'blacklist'

const LIST_LABELS: Record<ListType, string> = { whitelist: '白名单', blacklist: '黑名单' }

function quickAddSummary(result: KeywordQuickAddResult) {
  const changes = [
    result.candidates_created ? `将新增 ${result.candidates_created} 条候选` : '',
    result.candidates_dismissed ? `将移走 ${result.candidates_dismissed} 条待确认候选` : '',
  ].filter(Boolean)
  return `涉及 ${result.packages_affected} 个资源包，${changes.length ? changes.join('，') : '候选不会变化'}`
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function CandidatesInbox({ onCountsChange }: CandidatesInboxProps) {
  const [view, setView] = useState<InboxView>('candidates')
  const [items, setItems] = useState<InboxItem[]>([])
  const [counts, setCounts] = useState({ candidates: 0, ignored: 0, unmatched: 0 })
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [downloadStatus, setDownloadStatus] = useState<string | undefined>()
  const [keywordEntryId, setKeywordEntryId] = useState<number | undefined>()
  const [channelTitle, setChannelTitle] = useState<string | undefined>()
  const [channels, setChannels] = useState<string[]>([])
  const [selected, setSelected] = useState<Set<number>>(() => new Set())
  const [fading, setFading] = useState<Set<number>>(() => new Set())
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // 行内「下载」正在提交的资源包，用于单行按钮的加载状态
  const [submittingRowId, setSubmittingRowId] = useState<number | null>(null)
  // 搜索词一键加黑/白名单：先预览，确认后再写入
  const [quickAdd, setQuickAdd] = useState<KeywordQuickAddResult | null>(null)
  const [quickAddLoading, setQuickAddLoading] = useState<ListType | 'confirm' | null>(null)
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
        channelTitle,
        page: requestedPage,
      })
      setItems(payload.items ?? [])
      setCounts({ unmatched: 0, ...(payload.counts ?? { candidates: payload.total, ignored: 0 }) })
      onCountsChange(payload.counts ?? { candidates: payload.total, ignored: 0 })
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }, [channelTitle, downloadStatus, keywordEntryId, onCountsChange, page, search, view])

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
    // 频道很少，进页面取一次作为频道筛选项
    listDownloaderChannels().then(setChannels).catch(() => setChannels([]))
  }, [])

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

  async function previewQuickAdd(listType: ListType) {
    const keyword = search.trim()
    if (!keyword || quickAddLoading) return
    setQuickAddLoading(listType)
    try {
      setQuickAdd(await quickAddKeyword(keyword, listType, true))
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setQuickAddLoading(null)
    }
  }

  async function confirmQuickAdd() {
    if (!quickAdd || quickAddLoading) return
    setQuickAddLoading('confirm')
    try {
      const result = await quickAddKeyword(quickAdd.keyword, quickAdd.list_type, false)
      message.success(`已加入${LIST_LABELS[result.list_type]}：${quickAddSummary(result).replace(/将/g, '已')}`)
      setQuickAdd(null)
      setSelected(new Set())
      await load(1)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setQuickAddLoading(null)
    }
  }

  function submitSelected() {
    if (!selectedItems.length || submitting) return
    return submitItems(selectedItems)
  }

  async function submitItems(targets: InboxItem[], rowId: number | null = null) {
    if (submitting) return
    const packageIds = targets.map((item) => item.package_id)
    const candidateIds = targets.flatMap((item) => item.candidate_ids)
    setSubmitting(true)
    setSubmittingRowId(rowId)
    try {
      // 未命中视图没有白名单候选，按资源包直接提交
      const result = view === 'unmatched' ? await submitDownloaderPackages(packageIds) : await submitDownloaderBatches(candidateIds)
      setFading(new Set(packageIds))
      setSelected((current) => {
        const next = new Set(current)
        packageIds.forEach((id) => next.delete(id))
        return next
      })
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
      setSubmittingRowId(null)
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

  async function ignoreWholeChannel(targetChannel: string) {
    try {
      const result = await ignoreChannel(targetChannel)
      // 忽略后清掉频道筛选，回到全部候选（筛选变化会自动重新加载）
      setChannelTitle(undefined)
      setPage(1)
      notification.open({
        key: 'downloader-ignore-channel',
        title: `已忽略频道「${targetChannel}」的 ${result.ignored} 个资源包`,
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
          <Button aria-label={`下载 ${item.title}`} className="downloader-row-action" size="small" type="primary" loading={submittingRowId === item.package_id} disabled={(submitting && submittingRowId !== item.package_id) || (item.boundary_status !== undefined && item.boundary_status !== 'stable')} title={item.boundary_status !== undefined && item.boundary_status !== 'stable' ? '上游还在整理，暂不可下载' : undefined} onClick={() => void submitItems([item], item.package_id)}>下载</Button>
          <Button aria-label="忽略" className="downloader-row-action" size="small" onClick={() => ignoreOne(item)}>忽略</Button>
        </Space>
      ),
    },
  ]

  return (
    <section className="downloader-inbox" data-testid="candidates-inbox" aria-label="候选收件箱">
      <DataToolbar
        left={<Segmented value={view} onChange={(value) => { setView(value as InboxView); setPage(1); setSelected(new Set()); if (value === 'unmatched') setKeywordEntryId(undefined) }} options={[{ label: `待确认 (${counts.candidates})`, value: 'candidates' }, { label: `未命中 (${counts.unmatched})`, value: 'unmatched' }, { label: `已忽略 (${counts.ignored})`, value: 'ignored' }]} />}
        right={<Space wrap><Input ref={searchRef} prefix={<SearchOutlined />} allowClear placeholder="搜索资源包" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} />{search.trim() ? <><Button loading={quickAddLoading === 'whitelist'} onClick={() => void previewQuickAdd('whitelist')}>加入白名单</Button><Button danger loading={quickAddLoading === 'blacklist'} onClick={() => void previewQuickAdd('blacklist')}>加入黑名单</Button></> : null}<Select allowClear placeholder="频道" aria-label="频道筛选" options={channels.map((value) => ({ value, label: value }))} value={channelTitle} onChange={(value) => { setChannelTitle(value); setPage(1); setSelected(new Set()) }} />{channelTitle && view === 'candidates' ? <Button danger onClick={() => void ignoreWholeChannel(channelTitle)}>忽略此频道</Button> : null}{view === 'unmatched' ? null : <Select allowClear placeholder="白名单命中词" options={keywordOptions} value={keywordEntryId} onChange={(value) => { setKeywordEntryId(value); setPage(1) }} />}<Select allowClear placeholder="下载状态" value={downloadStatus} onChange={(value) => { setDownloadStatus(value); setPage(1) }} options={[{ label: '全部', value: undefined }, { label: '未下载', value: 'never' }, { label: '有更新', value: 'outdated' }, { label: '曾失败', value: 'failed' }, { label: '已完成', value: 'completed' }]} /></Space>}
      />
      <Table<InboxItem>
        className="downloader-inbox-table"
        rowKey="package_id"
        loading={loading}
        columns={columns}
        dataSource={visibleItems}
        pagination={{ current: page, pageSize: 50, total: counts[view], hideOnSinglePage: true, onChange: (nextPage) => setPage(nextPage) }}
        rowClassName={(item) => fading.has(item.package_id) ? 'downloader-row-fading' : ''}
        locale={{ emptyText: <EmptyState title={{ candidates: '暂无待确认候选', unmatched: '暂无未命中资源包', ignored: '暂无已忽略资源包' }[view]} description="可以先同步资源包，或调整筛选条件。" /> }}
      />
      <Modal
        open={quickAdd !== null}
        title={quickAdd ? `把「${quickAdd.keyword}」加入${LIST_LABELS[quickAdd.list_type]}` : ''}
        okText={quickAdd ? `确认加入${LIST_LABELS[quickAdd.list_type]}` : '确认'}
        okButtonProps={{ danger: quickAdd?.list_type === 'blacklist', loading: quickAddLoading === 'confirm' }}
        cancelText="取消"
        onOk={() => void confirmQuickAdd()}
        onCancel={() => setQuickAdd(null)}
      >
        {quickAdd ? (
          <Space orientation="vertical" size={8}>
            <Typography.Text>{quickAddSummary(quickAdd)}</Typography.Text>
            {quickAdd.entry_status === 'existing' ? <Typography.Text type="secondary">该词已在{LIST_LABELS[quickAdd.list_type]}中，本次只重新计算候选。</Typography.Text> : null}
            {quickAdd.sample_titles.length ? (
              <>
                <Typography.Text type="secondary">示例资源包：</Typography.Text>
                {quickAdd.sample_titles.map((title) => <Typography.Text key={title}>{title}</Typography.Text>)}
              </>
            ) : null}
          </Space>
        ) : null}
      </Modal>
      <FloatingActionBar count={selectedItems.length} totalBytes={selectedBytes} onSelectAll={() => setSelected(new Set(visibleItems.map((item) => item.package_id)))} onClear={() => setSelected(new Set())} onIgnore={ignoreSelected} onSubmit={() => void submitSelected()} loading={submitting && submittingRowId === null} />
    </section>
  )
}
